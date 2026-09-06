# Native filesystem RPC integration

`NativeFilesBackend` connects `fs/readFile`, `fs/writeFile` and
`fs/createDirectory` from the audited Codex exec-server protocol to actual native
file operations. It retains each
request's complete portable policy, resolves the supported policy semantics,
and checks access before starting `native-files`. It does not flatten a deny
rule or protected metadata into a writable-root grant.

The supervisor configures one guest workspace mapping and owns its physical
directory FD. Requests cannot select a host path, root FD or a wider mapping.
The helper receives that FD through explicit descriptor inheritance; it resolves
relative paths with openat2 BENEATH/NO_SYMLINKS/NO_XDEV. Existing files are pinned
with O_PATH, checked for regular type, owner and one link, then reopened by the
helper's own /proc/self/fd entry. New files use exclusive creation. The helper
never executes caller code and is only the native half of this trusted backend;
calling the helper directly is not policy authorization or a process sandbox.

Writes verify the complete declared input length before opening the target,
then preserve the existing inode and propagate truncate/write/fsync failures.
They are not atomic replacements or rollback transactions. Cancellation after
mutation starts can leave that mutation; the backend terminates and waits for
the helper before releasing its workspace. Read/write data is bounded to 16 MiB.

Directory creation follows the reviewed upstream default: absent or null
`recursive` means true. Recursive creation succeeds for an existing admitted
directory without replacing its inode; nonrecursive creation reports failure
if the target already exists or its parent is absent. The workspace root can
be the existing recursive target. Every request still requires a writable
target and the complete supported sandbox context. `followSymlinks` is preserved
and type-checked, but a workspace containing any symlink remains inadmissible
under either option value.

Before starting the helper, the backend inventories the exclusively owned
workspace and authorizes **every missing directory component**, including all
missing ancestors. A writable leaf grant never grants implicit creation rights
to a read-only or denied ancestor. An existing ancestor requires no new creation
right, so an explicit child write can override its broader deny. Existing
metadata protection and explicit exceptions are checked for each creation.
The complete plan is rejected before mutation if it would exceed 64 directory
levels or the 100,000-entry workspace admission bound.

The additional native invocations are:

```text
native-files mkdir  ROOT_FD RELATIVE_PATH MISSING_COUNT PARENT_DEVICE PARENT_INODE
native-files mkdirs ROOT_FD RELATIVE_PATH MISSING_COUNT PARENT_DEVICE PARENT_INODE
```

`mkdir` is nonrecursive; `mkdirs` is recursive. `MISSING_COUNT` is the exact
number of trailing components authorized for creation. The last two fields
identify the nearest existing directory from the trusted inventory. They are
consistency checks, not authentication or standalone policy authorization.
Only these directory operations accept `.` to refer to the already pinned
workspace root. Their stdin must reach EOF with no body. All numeric fields,
component lengths and depths are checked before any mutation.

The helper opens the existing prefix with openat2
BENEATH/NO_SYMLINKS/NO_XDEV, verifies its actual device and inode and checks that
the first planned component is still missing. Unexpected existing objects,
missing prefixes and replacement inodes fail; they are never adopted through
a retry. It creates each component by `mkdirat` relative to a held directory
FD, opens the child without following links, checks owner/type/exact 0700 mode,
and synchronizes child and parent before proceeding. A syscall, cancellation
or synchronization failure can leave already created directories: this is a
bounded filesystem operation, not an atomic recursive transaction. The existing
exclusion of unconfined outside writers remains necessary throughout the call.

Admission currently requires an exclusively owned ordinary workspace. An
advisory lease serializes cooperating backend sessions. Symlinks, hardlinks,
special files and gitdir worktrees are rejected before an operation; aliases
are not silently followed under a weaker policy. Nested existing .git/.agents
directories are protected, while explicit narrower write exceptions retain
their meaning. Scans are bounded to 100,000 entries and depth 64. An unconfined
concurrent writer is outside this contract: a scan/advisory lock alone would
not provide exclusion against it. Command workers therefore cannot be admitted
into this workspace until their native mutation boundary is connected.

This backend advertises no process, TTY, network, filesystem streaming or
session-resumption capability. The default CLI server still uses the refusing
backend; the real file backend is injected in its integration tests. The guest
bridge and native supervisor transport are not yet an Android product service.

Run `bash tools/executor/native-files-build.sh` under Linux/WSL. It builds the
host helper and two Android debug executables, records hashes, and runs 41 real
transport/native tests as a nonroot user. Tests include A/B/C/A decisions on one
inode, unchanged denied bytes, explicit metadata exceptions, aliases, malformed
policies and incomplete write input. Ten directory regressions additionally
cover recursive/nonrecursive behavior, Unicode paths, effective ancestor rights,
metadata exceptions, depth bounds, invalid native plans and a real parent
replacement. A separate server subprocess receives the actual stdio handshake,
creates directories, writes/reads real bytes and rejects a denied intermediate
component without creating its permitted ancestor. EOF releases the real lease.

The 6 September 2026 directory increment passed all 41 tests under WSL UID
`nobody` with no skips. Evidence is in
`downloads/native-files/foldgpt-native-files-build-QtGKBx57/tests.txt` and its
`SHA256SUMS`. The tested Linux helper SHA-256 is
`0e8c385d7f43debf6f5c1d190ed357142385986e1ef5a62ecdeeb70f78249714`;
the compiled Android helper SHA-256 is
`62d91fec93464e4301e43657d2902ec1a2c114209cf8da7f1d4ab71f2da234c9`.
The new directory operation has not been executed on Android or used by a real
model request. Other filesystem methods, the Android broker transport and
managed arbitrary processes remain unimplemented integration requirements.

On 2026-09-06, `NativeRunnerProbeService` also ran the same native file helper
under Android's actual Zygote UID and inherited seccomp filter. File creation,
read, same-inode overwrite, symlink/escape refusal and incomplete-write refusal
passed. This establishes native file semantics on Android, not the complete
Python policy RPC path there or arbitrary-command confinement.

Separately, `verify_official_environment.py` connected the untouched official
Codex 0.153.4 executable (SHA-256
`4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6`)
to `exec_server.py` on the Fold. The official app-server returned matching
environment metadata and `ready`; it then exited normally. The test used a
new temporary CODEX_HOME with no account and sent only initialize,
environment/info and environment/status. It made no model request and proves
transport compatibility only.
