# Explicit PRoot strict sandbox compatibility mode

`proot-strict-sandbox.patch` adds `--strict-sandbox` to the pinned PRoot source.
The new mode is opt-in, stored in tracer-owned state and inherited across guest
forks and execs. Without the option, the existing compatibility mode remains.
No environment variable in the guest turns strict mode off.

The pinned source already contains namespace and mount emulation, proc user-map
redirection and guest-intent `no_new_privs` reporting. Those are unsuitable as
evidence that an actual kernel sandbox was established. Strict mode removes
these simulated successes from the protected GNU execution path:

| Operation | Strict behavior |
| --- | --- |
| `unshare`, `setns` | Submit the actual syscall and retain its real result; do not create a fictitious network namespace. |
| `clone`, `clone3` | Preserve namespace flags, including the caller's `clone3` argument buffer. Ordinary native forks and threads still work. |
| `mount`, `umount`, `pivot_root` | Do not update virtual mount bindings or overwrite kernel errors with success. Translate target paths and bind sources before submitting the syscall. |
| `/proc/self/` and numeric-PID `uid_map`, `gid_map`, `setgroups` opens | Keep the actual proc files; never redirect them to `/dev/null`. |
| `PR_GET_NO_NEW_PRIVS` | Return actual kernel state, including inherited NNP and NNP required by PRoot's own seccomp optimization. Invalid arguments keep the real kernel error. |
| Security `SIGSYS` traps | Deliver the actual signal for namespace, mount, clone, setgroups and NNP/dumpability requests before compatibility extensions can consume it. |
| `PR_SET_DUMPABLE(0)` | Return explicit `EOPNOTSUPP`: making the tracee inaccessible would break PRoot memory access. Never report the protection as enabled. |
| `openat2` with nonzero resolution restrictions | Return explicit `EOPNOTSUPP` during translation, or preserve an outer `SIGSYS` trap. Absolute host-path rewriting cannot retain these restrictions. Ordinary zero-resolution opens still use the existing GNU translation. |
| `-i`, `-0`, `-S` | Reject together with strict mode, in either option order, with a diagnostic. Fake identities must not be presented as security state. |
| First guest launch | Require Landlock ABI 6 or newer, set NNP, and enter a child domain with signal and abstract-socket scopes before `PTRACE_TRACEME` or any guest code. Failure stops launch with a real diagnostic. |

This is a compatibility mode for a separately enforced kernel policy. It does
not supply a filesystem/network policy, prevent nested guest emulators, or make
PRoot into a complete isolation boundary. Its additional Landlock layer protects
the tracer from its guests; a trusted supervisor must still
select it and confine both PRoot and its descendants using actual kernel
mechanisms. Successful privileged mount/namespace operations have not been
qualified; the intended unprivileged executor denies those operations. Other
legacy filesystem/network compatibility helpers remain and require review in
the full executor policy. GNU ABI fallbacks, including `set_robust_list` to
`ENOSYS` after a real trap, remain enabled.

`PROOT_NO_SECCOMP=1` still controls only PRoot's optional `RET_TRACE` acceleration.
It does not disable an inherited Android or executor filter. With acceleration,
an inherited `RET_ERRNO` takes precedence before a `RET_TRACE` syscall-entry
event. The tests exercise both paths explicitly.

## Reproducible host regression

The versioned `test-proot-strict.sh` archives the exact source commit into fresh
baseline and patched directories, applies the existing header, shmat and SIGTERM
patches to both, then applies the strict patch only to the second. It builds
actual host PRoot binaries and C guests. All test processes run as a genuine
nonroot Linux x86_64 user; no syscall result is mocked.

```powershell
wsl -d Ubuntu-24.04 -u nobody --exec /bin/bash /mnt/c/Dev/ChatgptFold/tools/install/native/test-proot-strict.sh
```

Dependencies are the host C compiler, GNU Make, talloc development package,
Python 3, Git, tar and patch. The recipe refuses UID 0. Retained sources, test
programs, raw output, exact commands, restricted environment values, compiler
identity and binary hashes are written under a new
`/var/tmp/foldgpt-proot-strict-XXXXXXXX` directory.

The final run on 6 September 2026 passed **286 native observations and eight
process lifecycle cases** under WSL UID 65534. Evidence is copied to:

`downloads/install/native/foldgpt-proot-strict-Eu22Ab0a`

The cases include:

- Actual inherited seccomp `EACCES` denials and `SIGSYS` with verified
  `siginfo.si_syscall`, with acceleration enabled/disabled; kernel errors remain
  visible after a real fork/exec as well.
- Baseline versus new-binary legacy controls, exposing old false successes and
  the old `clone3` buffer modification on the full ptrace path.
- Direct native versus strict reads and invalid writes for all three proc
  files, using raw `open`, `openat`, and numeric PID paths. The deliberately
  invalid write payload cannot change real mappings.
- `prctl` NNP compared with actual `/proc/self/status`, before/after guest SET,
  with inherited NNP and after fork/exec; real invalid-query `EINVAL`.
- Real GNU Bash cwd/bind translation, source editing, GCC compilation, ELF
  creation and execution of a pthread program, plus actual exit status 23.
- Actual `set_robust_list` traps retaining the GNU `ENOSYS` fallback, explicit
  unsupported-security errors and incompatible fake-ID option rejection.
- SIGTERM cleanup of native descendants, including detached session leaders and
  active fork storms; independent host PID/start-time observations, subreaper
  waits and stopped heartbeat writes confirm completion. Without
  `--kill-on-exit`, the historical SIGTERM-ignore behavior remains; SIGQUIT
  still cleans up. Main exit 23 also reaps its live descendants.

The earlier retained run `foldgpt-proot-strict-k9z6fuon` failed a test expectation:
it assumed legacy emulation would run before an inherited errno filter with
acceleration enabled. Observed kernel precedence disproved that expectation.
The corrected test keeps the legacy simulation control on the full ptrace path
and checks strict real errors and actual traps with both modes. It does not
ignore a runtime failure. Intermediate passing runs `hRYYxGpk` and the final
`Eu22Ab0a` remain separate on WSL; only the final evidence is copied above.

| Evidence | SHA-256 |
| --- | --- |
| Exact PRoot source archive | `50b137e0db64b1e75c3e58964569325a4f167147c747e523fa9fe7c9070617e4` |
| Strict patch | `65979b9cdb7462089d34596706c74bbbca14bbf4ab44bb41a842269ad1fe2689` |
| Host patched PRoot | `257d768547fdf6fe2dc48a206acb375ba976297b81c9a0ef1549f0287f3fe591` |
| Host final `report.json` | `162d0ed8fe9a6848e69ef72ac4d94992b7e37d9d13db7805943cebb5893f0677` |

## ARM64 cross-build candidate

The canonical `build-native.sh` applies the strict patch to a fresh archive
snapshot, together with the existing fixes. `verify-elf.py` requires the strict
CLI option in the resulting PRoot executable. The NDK r29/API 30 build passed
88 real talloc compile/link checks and verification of all five runtime ELF
files, including both matching loaders, 16 KiB LOAD alignment, NX stacks,
interpreters, SONAMEs and declared dependencies.

Candidate with sources, recipe, notices and exact compiler provenance:

`downloads/install/native/foldgpt-native-ZSLV1IVf`

| Evidence | SHA-256 |
| --- | --- |
| ARM64 `libproot.so` | `8fe77e62189749114f9ee44d0d2d4d1f52c4b9505f3f097712f105f6db66ed51` |
| Build `manifest.json` | `59004d8aee6fe616776c84d547a150b1e34832568bd7a778182d562fa5d264a3` |

This candidate has **not run on Android** and has not replaced the packaged
runtime or existing client. No ADB, Gradle, APK installation, native managed
runner or broker change belongs to this patch. The host result does not qualify
the Fold kernel, ARM-specific SIGSYS register behavior, actual bubblewrap,
Landlock/USER_NOTIF composition, GPU behavior or production Desktop routing.
Those require the separate GNU policy and Android integration before adoption.

## Native protection of the tracer

The subsequent strict-mode correction enters a **new Landlock child domain**
in `launch_process()` immediately after the initial fork, before
`PTRACE_TRACEME` and before the first guest instruction. The tracer remains in
its existing parent domain. This uses the kernel's ptrace hierarchy: tracing
and memory access can flow from the tracer into its descendants, while the
reverse access is rejected. A guest cannot remove an inherited domain by
forking, executing another program or changing a PRoot option.

The ruleset has `handled_access_fs = 0`, `handled_access_net = 0`, and the ABI 6
signal/abstract-UNIX-socket scopes. It supplies no filesystem or network policy
and does not revoke already acquired descriptors. An outer native executor
must still enforce those policies and control inherited FDs. A real scope-only
test confirms that this layer does not add a filesystem restriction: ordinary
cross-directory `rename` remains successful. The implementation requires ABI 6
or newer and fails before any guest runs if kernel admission is unavailable.
Its outer seccomp filter must allow `landlock_create_ruleset` and
`landlock_restrict_self`; `landlock_add_rule` is unnecessary. These operations
cannot loosen an existing Landlock domain.

The [kernel Landlock documentation](https://docs.kernel.org/userspace-api/landlock.html)
describes the ptrace hierarchy, inherited domains and ABI 6 scopes. They are
also verified through native controlled processes, independently of Yama.

The final nonroot host regression is retained in
`downloads/install/native/foldgpt-proot-strict-Jd1EO0cW`:

- All existing **286 observations and eight lifecycle cases** pass, including
  the new binary's unchanged legacy behavior and the real GNU compiler test.
- **Eleven additional cases** establish scope-only admission and the ptrace
  hierarchy, including an already active outer domain inherited by both test
  processes. The parent actually reads, writes and attaches to its child.
  The child initially succeeds in the reverse direction; after the additional
  layer, `process_vm_readv/writev`, `/proc/parent/mem`, real `PTRACE_ATTACH`, and
  a signal are denied. Parent-side marker and signal counts confirm the result,
  and the actual child is reaped with `waitpid`.
- A test-only preload makes a marker inside the **actual PRoot tracer**
  observable and explicitly relaxes Yama. Baseline and patched legacy guests
  really modify it; strict guests cannot. Both ptrace acceleration settings
  pass. PRoot's emulated guest `ptrace` already refuses its own tracer; the
  separate native hierarchy case proves the kernel ptrace restriction.
- A real inherited seccomp refusal of `landlock_restrict_self` makes strict
  PRoot exit 125 with the expected diagnostic, without executing the guest.

The preload and probes belong only to the host test fixture; none is packaged
as a runtime dependency. Test sources and exact outputs are frozen alongside
the binaries. Report SHA-256:
`e4f4a8acd97196c33985947b9f37d663e7add80b45227d9e7428f6e72fbd2005`.
The patched host PRoot SHA-256 is
`50755cd686d4cde2dba809ed05188b5bfac13508573526f35f3ab139c3202db5`.

The same canonical patch compiles with NDK r29 for ARM64 in
`downloads/install/native/foldgpt-native-1fHJZzxt`. All 88 talloc compile/link
checks and all five ELF verifications pass. Its `libproot.so` SHA-256 is
`eb55d3a719877e39649670fdc06b43bbb2b068e3cdc8b49d5d8b18d3c2bd2916`;
manifest SHA-256 is
`7f6ea196b5d2bdbf93b446d9165f1a7b9027e0eb5b1401c99a30a32135451629`.
The final host test strengthens the outer-domain control after this cross-build;
the production patch and compiled host binary are unchanged.

This new candidate has not been executed on Android. These controlled results
do not establish the complete GNU executor policy, scratch/temporary isolation,
arbitrary workload containment or Desktop tool routing. No phone, official
client payload, or currently installed runtime was modified by this work.
