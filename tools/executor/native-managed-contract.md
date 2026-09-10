# Private native managed acquisition contract

This increment proves policy-mediated file acquisition by a real native
process. It does not implement an official `process/start` RPC endpoint or
activate a Desktop executor. The native supervisor and Python policy parent
are trusted; the executable is the confined subject. Android root, PRoot,
user-namespace emulation and a privileged helper are not involved.

## Admission and policy

The parent keeps the complete immutable `PolicyIntent` and passes its context
through the existing managed-policy parser and `NativeFilesBackend` inspection.
No read/write root list replaces the resolver. Unsupported context is rejected
before a process is spawned. Each acquisition is evaluated again, including
narrower overrides, denied descendants, existing protected metadata and explicit
metadata-write exceptions.

The admitted filesystem is one exclusively owned ordinary workspace, with a
fixed cwd and no concurrent unconfined writer. Existing symlinks, multiply linked
files, special files, aliases and gitdir-file worktrees are outside this profile.
These restrictions are checked by the existing native and Python tree inspection.
They are assumptions about external access as well as restrictions on the target;
they are not an inode lock against unrelated same-UID processes.

Only native ELF64, little-endian, architecture-matching static `ET_EXEC` files
without `PT_INTERP` or writable/executable load segments are admitted. The
executable is pinned with a close-on-exec descriptor, executed through real
`execveat(AT_EMPTY_PATH)`, and its successful exec is observed through
`PTRACE_EVENT_EXEC`. The supervisor detaches before target userspace and emits
`started` after that event. Environment is empty. The target inherits only
stdin/stdout/stderr; stdin is currently an empty pipe.

## Native mediation

The target gets Landlock execute/read permission for its exact static executable,
with no direct workspace grant or global filesystem read grant. A stacked seccomp
filter sends `openat`, `openat2`, and architecture-available `open`/`creat` calls to
the native listener. The existing seccomp allowlist remains in force. Network,
directory acquisition, cwd changes, pathname metadata, namespace mutations and
file-mode mutation remain refused. This is not full POSIX syscall compatibility
or a metadata-confidentiality guarantee.

For every admitted acquisition the supervisor:

1. Validates the live kernel notification, scalar flags and supported syscall form.
2. Copies the target pathname once through `process_vm_readv`. For `openat2`, it
   independently copies `open_how` once. It never resumes a pointer-bearing syscall
   through `SECCOMP_USER_NOTIF_FLAG_CONTINUE`.
3. Validates the copied path against the pinned workspace and sends a relative
   UTF-8 path as hex bytes over the private policy channel. Relative paths require
   `AT_FDCWD`; absolute paths must be beneath the known native workspace spelling.
4. Receives a strict decision carrying target and parent device/inode identities.
5. Resolves the copied path beneath pinned descriptors using `openat2` with
   `BENEATH | NO_SYMLINKS | NO_XDEV`, verifies ordinary type and actual identities,
   and opens the actual permitted file. Existing files are reopened through a
   pinned `/proc/self/fd` reference; absent files are created with `O_EXCL`.
6. Installs that real open descriptor with `SECCOMP_IOCTL_NOTIF_ADDFD` and
   `SECCOMP_ADDFD_FLAG_SEND`, preserving requested access, append, nonblocking
   and close-on-exec flags.

The copied decision binds the name and scalar flags used for native acquisition.
Target mutation of the original pathname or `open_how` after the copy cannot
redirect the later kernel operation. Acquiring a file can have a real creation or
truncation side effect before FD injection; cancellation is not a rollback.

The private socket must be a connected `AF_UNIX/SOCK_SEQPACKET` socket whose
kernel peer credentials match the supervisor's parent PID and real UID. Packets
are bounded; malformed, duplicate-field and stale decision frames fail closed.
The control socket and listener are closed before the target executes. This
transport is not a public worker protocol.

## Private CLI and frames

```
native-managed-runner ROOT_FD CONTROL_FD STATIC_ELF WALL_MS ADDRESS_BYTES OUTPUT_BYTES UID_TASK_BUDGET -- ARGV...
```

`native-managed-test.py` accepts `--runner`, `--fixture`, optional `--parent`,
`--evidence`, `--address-space-bytes` and `--uid-task-budget`. The Python diagnostic
driver preserves raw native events and independently records policy decisions.

An acquisition request contains exactly `type`, `id`, `syscall`, `flags`, `mode`,
`pathHex`, `pid`, `pathAddress` and `howAddress`. The last three are kernel
observations for the diagnostic mutation tests; they never grant permissions.
The response contains exactly `id`, `allow`, `device`, `inode`, `parentDevice`
and `parentInode`. The C parser validates that its id matches the pending request.

`started` records the native PID, profile `managed-acquisition-v1` and the resource
accounting fields below. `result` records the actual outcome, exit code or signal,
cleanup result, whether exec started, grants/denials, byte counts, setup stage and
errno. A successfully supervised program may exit nonzero; the runner's exit code
does not replace the actual program exit code in `result`.

## Resources and lifecycle

Linux `RLIMIT_NPROC` counts tasks sharing the target's real UID, including the
Android GUI and trusted processes. A fixed ceiling below the GUI's population
prevents even a legitimate fork with `EAGAIN`. Admission therefore measures native
`/proc/PID/status` `Uid:`/`Threads:` values and computes:

```
child NPROC soft = child NPROC hard
                = min(observed UID tasks + declared additional task budget,
                      inherited NPROC soft, inherited NPROC hard)
```

No inherited ceiling is raised. Admission fails if the result leaves no room.
`started` exposes `uidTasksObserved`, `uidTaskBudget`, `uidNprocLimit`,
`inheritedNprocSoft` and `inheritedNprocHard`. The diagnostic default budget is 128
additional tasks; it is an explicit resource allowance, not an invented measured
population or an exact per-command quota. The snapshot is non-atomic, skips
vanished or unreadable foreign proc entries, and reserves no capacity against
concurrent GUI growth. On Android its visible same-UID population must be checked
against an independent shell task count while the GUI remains active.

Other current limits include wall time, CPU time, aggregate captured output,
address space, core dumps, open descriptors and file size. The Android fixture's
Scudo address-space reservation is extracted by `native-runner-scudo-check.py`;
the measured 33 regions of 256 MiB plus separate 256 MiB headroom require
9,126,805,504 bytes. That address-space budget is not a resident-memory claim.

The target is placed in a process group it cannot change; the supervisor is a
child subreaper. On termination it retains the leader PID until signaling the
group, then reaps actual descendants. A bounded cleanup failure is reported as
failure. Kernel-blocked tasks and supervisor crash/SIGKILL do not have guaranteed
wall-bounded cleanup; `cleanupComplete` is asserted only after actual reaping.
This diagnostic currently has no streaming stdin, TTY, public cancellation RPC,
dynamic runtime closure or general-purpose native command support.

## Reproducible evidence

`native-managed-build.sh` freezes C and Python source dependencies, builds static
host and ARM64/API35 binaries with warnings treated as errors and 16 KiB Android
load alignment, runs the frozen Python test closure as a real nonroot user, and
records hashes, ELF reports, Scudo geometry and raw kernel observations.

The 17 tests cover real exec and successful brokered read; same-inode write/read/
deny/write; nested policy overrides; protected metadata and explicit exceptions;
available acquisition syscalls and escapes; create/exclusive/missing/denied
cases; real nonzero exit; timeout and cancellation; forked descendant reaping;
malformed/duplicate/stale decisions; stale inode before truncation; unsupported
policy before spawn; actual child NPROC values; forbidden primitives and empty
environment/descriptor boundary; exact FD flags; and two deterministic mutations
of real target memory after the broker copied pathname and `open_how`.

The snapshot `foldgpt-native-managed-build-3uWethND` passed all 17 host nonroot
tests (49 real process observations) using the frozen Python closure and compiled
for Android. Its native binaries and runtime Python sources match the earlier
`foldgpt-native-managed-build-KbjCL7Kd` snapshot. The supervisor also passed the
malformed-response, UID-accounting and two real-pointer-mutation tests with
AddressSanitizer and UndefinedBehaviorSanitizer; that evidence is in
`downloads/native-managed/sanitize-3uWethND`.

Android execution and the same-UID population check must be established from the
independently collected device report; compilation and host success alone do not
establish them.
