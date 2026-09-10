# Bionic libc cwd compatibility

This independently packaged shared library exports exactly `chdir`. Its real
implementation obtains a directory FD through `openat` and applies `fchdir`.
The native supervisor can therefore mediate acquisition using its existing
filesystem policy, then allow the descriptor operation. The `chdir` syscall
remains denied. There is no pointer-bearing `SECCOMP_USER_NOTIF_FLAG_CONTINUE`,
invented working directory, PRoot, VM, kernel change or official ChatGPT edit.

The implementation uses `O_RDONLY | O_DIRECTORY | O_CLOEXEC`. The kernel's
`SECCOMP_IOCTL_NOTIF_ADDFD` rejects `O_PATH` source FDs with `EBADF`, as observed
in the actual supervisor test. A read-only directory descriptor accurately
implements the executor's existing requirement that an admitted directory be
readable. This deliberately cannot reproduce POSIX `chdir` into a directory
that is searchable but unreadable; such a request fails with `EACCES`. The
library also requires one temporary descriptor and reports `EMFILE` honestly
when none is available. It does not convert a failure into a successful result.

The shim uses libc's `syscall` errno wrappers for openat, fchdir and close.
Those calls introduce no pthread cancellation points. It preserves a failing
fchdir's errno across close, never retries close on EINTR, and leaves no FD
behind on ordinary success or failure. Successful calls change the real
process cwd, which is inherently shared by its threads. Concurrent fd/cwd
changes have the normal process-wide semantics; this library is not a lock.

## Trusted integration contract

The host-owned backend option is `cwdShim = {"path": "absolute ELF path",
"sha256": "actual lowercase SHA-256"}`. The native backend verifies this
file, includes the exact immutable library in its runtime authority, reserves
`LD_PRELOAD` from request-controlled environment settings, and injects this
absolute path before invoking the worker.

The Android deployment asset instead uses the exact fixed marker
`"path": "@nativeLibraryDir/libfoldgpt_bionic_cwd.so"`. Java resolves and
verifies the library against PackageManager's actual `nativeLibraryDir` before
the Shizuku fork. The bootstrap resolves that same filename alongside its
actual `/proc/self/exe`, verifies sys.executable and the configured interpreter
basename, refuses aliases and rechecks the digest before backend construction.
No caller chooses a random `/data/app` or shell-writable path. This marker is
specific to this one library and is not arbitrary string interpolation.

The transport CMake build compiles and packages the shim inside our signed
FoldGPT APK. The deployment digest must match that actual packaged artifact;
debug/release/compiler settings can differ from this independent build. A
checksum alone does not make a shell-writable directory immutable. No qualified
deployment has been activated by bundling the library.

The supervisor must permit only directory FDs acquired through its mediated
open operation, close setup FDs before worker exec, and pin each caller's
actual `/proc/TID/cwd` before resolving subsequent relative operations.
Both the current cwd and its acquisitions are checked against the full policy.
Allowing fchdir without these constraints is not this integration.

Reserved preload is compatibility plumbing, not a security boundary. A worker
can unset `LD_PRELOAD` before spawning another executable, use a statically
linked program, or issue a raw syscall. In those cases unsupported native
chdir remains denied by the kernel. Removing the library does not grant any
extra authority. Loader interposition on the particular Bionic runtime must
be qualified on Android before activating a deployment.

## Verification and status

Run `bash tools/executor/bionic-cwd/build.sh` in the existing Linux build
environment. It creates a fresh frozen build under `/var/tmp` and a verified
copy under `downloads/bionic-cwd`. The script contains no phone access.

The host test executes as an ordinary UID under a real seccomp filter refusing
the raw `chdir` syscall. It proves that the baseline libc call fails, while
the preload changes cwd and directs relative file output to the actual child
directory. It checks missing paths, non-directory paths, unreadable directories,
fchdir refusal for an acquired directory without search permission, bad pointers,
direct syscall refusal, repeated operation FD lifetime and an
actually exhausted FD table. This narrow filter is not a production sandbox;
the separate bionic-supervisor tests qualify policy mediation and lifecycle.

`test-supervisor.py FROZEN_SUPERVISOR_DIR HOST_CWD_LIBRARY` composes that actual
factory with the shim. It checks Bash `cd` followed by Python `os.chdir`, real
relative output after both cwd changes, denied-directory entry/read, reserved
preload rejection, incorrect attestation rejection, and kernel refusal after a
worker unsets preload. It runs separately against a frozen supervisor build,
as an ordinary UID, and records the actual lifecycle and test results there.

The NDK builds a standard ARM64 Bionic shared library linked to `libc.so`.
Checks require a stable SONAME, exactly one exported symbol, 16 KiB alignment,
RELRO/NOW, a non-executable stack, no writable executable segment, no RPATH and
no text relocations. Unlike the executor PIE binaries, a loadable library must
have neither an entrypoint nor `PT_INTERP`. The system linker loads it.

The four composed factory tests passed against the actual frozen supervisor
`foldgpt-bionic-supervisor-ZBbervqT`. The transport's installed-path admission
has four Java tests plus actual copied-interpreter PC checks for the changing
package directory, symlinks, digests, schema, missing files and writable files.

Compilation and PC tests do not demonstrate Android execution, full Codex
integration or production bubblewrap replacement. No phone was used by this
work, and no APK deployment/qualification evidence is fabricated here.
