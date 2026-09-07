# Bionic process factory: separate native supervisor

This is a real `NativeExecutorBackend.process_factory` implementation for the
fixed authenticated Shizuku Python/Bionic bootstrap. It runs dynamic executable
argv, cwd, environment and real stdin/stdout/stderr. It does not use PRoot,
ptrace, guest address-space emulation, bubblewrap, root, or an Android VM.

Factory: `tools.executor.bionic-supervisor.factory:factory` (importlib supports
the hyphenated module component). All production imports are package-relative
or under `tools`; no production import depends on cwd or a host checkout.

The factory accepts only bootstrap-owned options:

```json
{
  "helper": "/canonical/native/libfoldgpt_native_files.so",
  "handleHelper": "/canonical/native/libfoldgpt_native_file_handle.so",
  "processRunner": "/canonical/native/libfoldgpt_bionic_supervisor.so",
  "workspace": "/canonical/owned/workspace",
  "executables": {"bash": "/canonical/native/libfoldgpt_bash.so"},
  "runtime": [{"path": "/canonical/native", "execute": true}],
  "limits": {"wall_ms": 60000, "data_bytes": 268435456,
             "file_bytes": 16777216, "output_bytes": 8388608,
             "uid_task_budget": 8, "cpu_seconds": 30, "descriptors": 128},
  "parentEnvironment": {}
}
```

This example is a schema illustration, not an Android deployment: real Bionic
needs its exact reviewed linker/library/Python/timezone runtime paths. Runtime
and executables are not request-owned RPC arguments. Runtime must be immutable
and separate from the managed workspace. Native and advertised workspace paths
must match. Limits and parentEnvironment are optional; environment inheritance
requires an explicit snapshot, and an empty snapshot means exactly empty.

Optional `cwdShim: {"path": "/canonical/native/libfoldgpt_bionic_cwd.so",
"sha256": "<reviewed lowercase SHA256>"}` attests the separate libc chdir shim.
The factory verifies its canonical regular file and digest at construction and
before spawn, adds an exact immutable runtime mapping and reserves LD_PRELOAD.
Any request or parent environment supplying LD_PRELOAD is refused. The trusted
launch injects only this attested library; the supervisor itself has an empty
environment and does not preload it. The shim grants no extra sandbox authority.

The launch envelope is a sealed memfd; libc and NDK-verified Linux FD constants
are used on both Linux and Android. Native startup rejects uid0, unequal UID/GID,
capabilities, unsupported Landlock, invalid workspace identity and setup errors.
The child receives only stdio and temporary close-on-exec setup descriptors.
Landlock ABI6 filesystem rules and both scopes are a kernel ceiling. The strict
seccomp allowlist and a second USER_NOTIF filter mediate path acquisitions and
metadata. No pointer-bearing notification is continued. Broker reads pin the
target mm through `/proc/TID/mem` before checking notification validity. Open
results are injected atomically with `SECCOMP_ADDFD_FLAG_SEND`.

The complete portable managed policy is parsed for each process. Project
operations reuse the existing policy resolver and filesystem inspection,
including deny-read and `.git`/`.agents`/`.codex` protections. No additive
Landlock path lowering stands in for that policy. Ordinary opens, stat/lstat,
statx, mkdir and getdents64 are mediated. Directory listing uses the same rule
as fs/readDirectory: a directory with an unreadable child is refused; entries
are never hidden by producing a fabricated partial result. Symlink metadata,
readlink, and O_NOFOLLOW semantics for the immutable runtime are preserved.

Cancellation is a separate native socket, including EOF. The native owner kills
the still-owned process group while the leader is unreaped and reaps adopted
descendants. Timeout and output caps use the same lifecycle. A final trusted
cleanup record and actual native owner wait are mandatory before the shared
filesystem lease is released.
An unknown result quarantines the workspace; a delayed kernel cleanup retains
the actual native owner and descriptors, without a permissive retry. The UID
task RLIMIT includes observed same-UID tasks plus the configured budget; it is
not an aggregate memory/CPU or cgroup guarantee.

`build.sh` freezes source, compiles host helpers, builds dynamic Android PIE
with `/system/bin/linker64`, verifies ELF/16KiB/RELRO/NOW/NX, and runs real nonroot
host tests. It never invokes adb. Native Android deployment remains a separate
review and qualification gate.

Current verified host coverage: dynamic Bash→Python, project create/edit,
unittest discovery with real directory streams, real env/cwd and stdin EOF,
binary stdin with duplicate write IDs, interruption, termination, timeout,
descendants, output limit, runtime lstat/readlink/nofollow, invalid metadata
flags, private/metadata denial, channel EOF, pending-start cancellation and
supervisor loss quarantine. This is not yet a general command release:

- Native `chdir` is refused; `fchdir` accepts already admitted directory FDs.
  Relative acquisitions pin the calling task's real cwd before policy checks.
  The separate [attested runtime shim](../bionic-cwd/README.md) provides real
  Bash/Python libc chdir compatibility and is covered by host integration tests.
- Namespace deletion/rename/link/symlink and mutation through directory FDs are
  refused. Arbitrary workspace executable files are not granted execute.
- Workspace symlinks, hardlinks and gitdir/worktree aliases remain outside the
  existing strict file backend, and are refused rather than resolved loosely.
- Runtime directories are an explicit bootstrap authority. A policy containing
  any explicit denial intersecting a required runtime is refused before spawn;
  the policy is never silently overwritten by that runtime mapping.
- getdents64 duplicates the exact calling thread's FD with
  pidfd_open(PIDFD_THREAD)/pidfd_getfd. Main-thread and secondary-thread real
  directory entries and shared offsets are host-proven. Android SELinux access
  remains to be measured by the [fixed qualification](qualification.md).
  Broker setup ENOENT is reported as EOPNOTSUPP because libc readdir can turn
  ENOENT into false empty success; actual path open/stat ENOENT is preserved.
- Network and TTY remain unsupported and denied. Resource limits are per
  process/UID kernel limits, not aggregate per-workspace quotas.
- No phone qualification or production bubblewrap route replacement is claimed.

The O_PATH limitation is a kernel interface constraint, reproduced by an actual
host notification returning EBADF. Linux `seccomp_notify_addfd` calls
[`fget(addfd.srcfd)`](https://github.com/torvalds/linux/blob/master/kernel/seccomp.c#L1738)
(source blob `86cf4460d69eaa8e1c643e479118e29da00aca9d`), and
[`fget` excludes FMODE_PATH](https://github.com/torvalds/linux/blob/master/fs/file.c#L1110)
(source blob `628ca07dc4b179db98f0ac6e9f6d60dd7f3c5d3b`). Sources checked through
the GitHub repository connector on 2026-09-07 after the integrated browser was
unavailable. The compatible cwd shim therefore requests a real
O_RDONLY|O_DIRECTORY descriptor; requests explicitly asking for O_PATH remain
refused, never converted into a descriptor with different flags.
