# Managed filesystem policy: next native increment

Status: implementation contract and test inputs, **not an implemented executor**.
No device, account, model request, or official binary is changed by these files.
The existing fixed native probes remain useful evidence for their own scope.

This review uses official Codex `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`. The current checkout HEAD is different;
resolve all source references against this tag. The accompanying
`managed-policy-vectors.json` contains expected policy decisions, not measured
kernel results. It can seed the native policy compiler's conformance suite.

## Boundary to implement

Normal model execution and `apply_patch` can use the official exec-server
environment protocol. Each `process/start` and filesystem request carries a
`FileSystemSandboxContext`. An executor owned by FoldGPT can enforce that context
without changing the official executable. The unmodified stock exec-server
still constructs its existing namespace sandbox: wrapping it in the fixed
native probe does not replace that implementation.

The separate `tools/probe-exec-server-policy.py` deliberately exercises the
stock executor. A namespace/helper initialization failure in that probe is a
failed execution stage, never evidence that a requested file access was denied
by a working policy. It is not yet a probe of a FoldGPT replacement executor.

Implement a policy compiler and per-request native workers before connecting
real conversations. Initially expose only the explicitly implemented operations
in a private test executor. An unsupported field, policy, network requirement,
or operation must return a clear error before spawning or modifying files.
That bounded milestone does not qualify as a fully functional public release.

## Input and semantic authority

| Topic | Exact source in the reviewed tag | Required behavior |
| --- | --- | --- |
| Wire filesystem policy | `file-system/src/lib.rs:174-210,237-291,330-348` | Preserve the managed profile, path URI/glob/special entry, access, missing-path behavior, scan depth, cwd, roots, home, temporary directories, and enforcement options. The entry fields are snake_case; the context is camelCase. |
| Entry precedence | `protocol/src/permissions.rs:83-119,926-967` | Most specific path wins; at equal depth use `deny > write > read`. Entry order is not an override mechanism. A more specific write may override a broader deny. No matching rule means deny. |
| Protected metadata | `protocol/src/permissions.rs:970-1001` | Apply metadata write restrictions in addition to ordinary access resolution. An explicit narrower writable metadata entry can grant an exception. A blanket ban on every `.git` component is not the full official policy. |
| Runtime metadata expansion | `protocol/src/permissions.rs:2189-2226,2399 onward` | Account for existing `.git` directories/files, a worktree's `gitdir:` target, `.agents` directories, and the missing workspace `.codex` protection. Preserve both raw alias and effective path protections. |
| Dynamic roots | `protocol/src/permissions.rs:1173-1228,1767 onward` | Expand project roots/subpaths and executor-owned temporary roots from this context, not from the UI host or a command-supplied environment fallback. |
| Helper runtime | `exec-server/src/fs_sandbox.rs:90-136` | Official filesystem helpers add their specific executable/runtime permissions. Do not translate one executable into read access to its whole parent directory. |
| Process launch | `exec-server-protocol/src/protocol.rs:256-290` | Preserve cwd, argv, environment policy, stdin/tty behavior, and the full sandbox. Managed network requirements must fail closed when they cannot be enforced. |

The first compiler may support only managed/restricted profiles with explicit
POSIX file URIs, `root`, `project_roots`, `tmpdir`, and `slash_tmp`, plus the
metadata semantics above. Require an explicit native cwd in this initial API.
Reject globs, `minimal`, unknown special tokens, missing-path options, shell
snapshots, or other unimplemented inputs as a whole request, with their exact
field named. This is an explicit initial compatibility limit, not a claim that
the official protocol itself rejects those inputs. In particular, the official
configuration parser intentionally preserves/ignores unknown special tokens;
the new enforcing boundary must not silently widen permissions by doing so.

Do not emit a successful policy object merely from string prefix matching.
URI decoding, path convention, component boundaries, effective aliases, and
the runtime view must be resolved by audited native filesystem code. Avoid
maintaining a second incomplete interpretation of globs or metadata expansion;
prefer reusing the pinned official resolver where practicable, with native
enforcement consuming its complete result.

## Native policy representation

The trusted side constructs one immutable `CompiledPolicy` for each request:

1. Full original context plus a deterministic digest for audit correlation.
   The digest identifies input; it is not an authentication mechanism.
2. Explicit guest-to-native mount/bind map for that worker. A guest URI must
   resolve through this map without falling back to the application's home.
3. Pinned `O_PATH` root/cwd objects and component-based rules with effective
   access, original source entry, metadata carveouts and explicit exceptions.
4. A reviewed runtime executable/loader read-and-execute grant set, separate
   from project grants. No account, session, keyring, or broker directory grant
   is inferred from proximity to an executable.
5. The Landlock rights and syscall/descriptor mediation strategy needed for
   every path and operation. An unresolved case prevents admission.

The transport passes immutable policy data to a trusted native supervisor;
command input is never a shell expression used to construct this data. The
supervisor owns the policy and notification listeners. Workers cannot read or
write this control channel or choose a wider policy identifier.

Use a new worker, descriptor table, Landlock domain, private scratch, and
seccomp listener for each different policy. Never reuse a broader worker and
attempt to replace its policy with a narrower one. Existing file descriptors
and mappings retain authority after a path policy changes.

## Why a write broker is insufficient

Landlock grants are additive within a ruleset and restrictions accumulate
across domains. Granting `READ_FILE`/`READ_DIR` on `/` does not permit a later
child rule to subtract `/workspace/private`. The present global-read probe
therefore cannot implement a managed deny-read exception.

Two honest mechanisms can be evaluated:

- Grant direct access only to subtrees whose entire reachable contents have
  homogeneous permissions and whose namespace stability is guaranteed. A
  one-time directory scan is not that guarantee; newly created or renamed
  children and aliases must remain confined.
- Mediate acquisitions, including read-only opens, for policy-sensitive trees.
  The broker resolves a copied path against its own pinned roots and supplies
  an authorized descriptor. Direct worker opens cannot bypass that broker.

The second route is the next experiment. It does **not** make metadata,
executable loading, or every filesystem mutation automatically safe:

| Surface | Required handling before general commands |
| --- | --- |
| Reads and execution | Cover `open/openat/openat2`, descriptor reopen, mmap, execute/interpreter paths, and executable runtime grants. Landlock execute permission must really allow the intended program; supplying an FD alone is not a substitute for execute enforcement. |
| Metadata and traversal | Define and test `stat/statx`, access checks, `readlink`, directory listing and canonicalization under the requested policy. Landlock read denial alone does not hide every filename or metadata query. |
| Hardlinks | `RESOLVE_NO_SYMLINKS` does not reject hardlinks. An inode can have a writable project name and a protected/outside name. `st_nlink == 1` before use is not a complete solution against concurrent creation of another link. The first fixture excludes links by construction; arbitrary workspaces require an enforced ownership/alias strategy. |
| Renames and removals | Authorize source and destination, and protect pinned policy roots from renaming/replacement. A pinned directory FD follows its inode after a rename; lexical permission alone cannot establish its current location. |
| Cwd and dirfds | Do not inspect `/proc/PID/cwd` or an FD symlink and then allow the original syscall to continue. Another thread can change the referent. Resolve through kernel-pinned objects or reject that form until implemented. |
| Mutation beyond open | Audit chmod/chown, timestamps, xattrs, truncate, fallocate, unlink, rename, hard/symbolic links, device/FIFO creation and relevant ioctls. Opening a writable descriptor is only one operation family. |
| Inherited FDs | Close everything except explicitly assigned stdin/stdout/stderr/control endpoints before untrusted code. Use output pipes; do not let the command inherit a writable diagnostic log file outside its policy. Reject cross-policy FD passing and test `/proc/*/fd`, `pidfd_getfd`, `SCM_RIGHTS`, and io_uring acquisition paths. |
| Process boundaries | Prevent a worker from ptracing, reading/writing memory, changing limits, or signaling the broker and sibling workers. PRoot's legitimate tracing of its own descendants must remain possible. Test PID reuse and descendant escape/cleanup rather than relying only on one parent-ptrace denial. |

With seccomp notification, copy pointed-to input once, validate it, resolve and
perform the operation in the broker, and use `ADDFD_FLAG_SEND` where appropriate.
Never approve a mutable pointer by replying `CONTINUE`. `ID_VALID` prevents some
stale operations but is not a transaction: cancellation after a create/truncate
can leave that side effect. Document the actual cancellation semantics.

The native boundary must apply before PRoot starts and survive PRoot children.
PRoot path translation is compatibility machinery, not a security assertion.
Recheck the actual ordering for the mediated syscalls under
`PROOT_NO_SECCOMP=1`; the existing fixed-open proof is not proof for all syscall
families. The namespace shim is not part of the new trusted enforcement path.

## Filesystem RPCs and protocol lifecycle

Use the same compiled policy for `fs/*` operations. For a streaming `fs/open`,
bind the handle to its creating connection, policy, access mode, and lifetime;
another request cannot supply a different policy and inherit its authority.
Do not advertise `sandboxedFileStreaming` before that behavior works.

Protocol logical process IDs are session-scoped keys, not Android PIDs. Output
must have one monotonic sequence, bounded buffering, correct `process/read`
cursor handling, and cleanup on cancellation/disconnection. Process exit is not
proof all descendants exited. Decide whether disconnected sessions survive and
implement that contract; do not accidentally kill genuine Remote tasks.

Return `sandboxType: linuxSeccomp` only after the required native setup succeeds
and the requested managed policy is enforced. That label is not itself a test.
Do not map a managed policy to `external`, `disabled`, or an unsandboxed retry.

The Desktop app-server's local-host methods remain a separate integration
surface: configuring an environment does not automatically route `command/exec`,
`process/spawn`, local `fs/*`, or `thread/shellCommand` through it. Preserve the
existing official binary and make environment selection and compatibility
checks explicit. These files do not resolve that separate integration gap.

## Next decisive test, without a model request

Use only a fresh native-owned fixture, absent accounts/startup files, and a
fixed command sequence. The supervisor must independently verify final bytes,
modes, links, output and absence of surviving children. Never use user files as
negative-test targets.

1. Create `workspace/value.txt`, protected metadata markers, a sibling outside
   marker, and separate private scratch directories. Record inode identities.
2. Under policy A, start a fresh worker that reads and overwrites `value.txt`.
   Verify both succeed. This is the positive control.
3. Under policy B, grant that same file **read**. A fresh worker must read it,
   but an actual open for writing must return `EACCES` or `EPERM`. Verify bytes
   are unchanged. Failure to start the program is a failure, not a pass.
4. Under policy C, give that same file **deny**. Another worker must start and
   perform unrelated permitted work, but cannot read or write that file. Then
   run A again to prove that the file still exists and remains accessible to an
   allowed policy. This is the missing read-confidentiality proof.
5. Run A and C concurrently. Hold an A file descriptor open and explicitly
   attempt cross-worker descriptor acquisition/passing and process inspection.
   C must not obtain its contents or writable authority.
6. Repeat the relevant conformance cases below through both filesystem RPCs
   and the fixed shell. Separately test aliases, changing cwd/dirfds, metadata,
   hardlinks and cancellation. An unsupported case remains a failed release
   gate; it is never removed from the final requirement.

First validate this in a native fixed test, then under PRoot with the real
Debian shell, then through a private implementation of the official executor
protocol. Only after those pass should one ordinary Codex command and patch be
used as integration proof. No model credits are needed for the preceding work.

## Conformance fixture interpretation

`managed-policy-vectors.json` uses the actual portable profile/context shape.
Each resolution case defines explicit `entries`; queries use POSIX paths for
readability and identify expected **pure resolver** access and write eligibility.
These expectations are derived from the exact source above, not run against
the official resolver in this change. For example, the nested `.git` case
distinguishes top-level symbolic metadata protection from a universal component
ban; runtime repository/alias expansion still has to be tested separately.

The `native_cases` section is a required test matrix. It contains expected
outcomes and evidence requirements, no generated PASS values. Passing JSON
syntax validation only verifies that the fixture is readable.
