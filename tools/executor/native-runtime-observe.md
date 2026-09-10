# Diagnostic SIGSYS observer

This executable observes a fixed argv supplied by the trusted debug supervisor.
It does not accept shell text or rewrite the command, environment, system call,
signal information, seccomp filter or credentials. It is not the production
runtime and must never supply successful untraced-runtime evidence.

```text
libfoldgpt-runtime-observe.so --timeout-ms 10000 -- /absolute/packaged-gnu-loader --library-path /absolute/trusted/arm64-libraries /absolute/python3.13 -I -S -B /absolute/trusted-fixture.py ...
```

The timeout must be 1..120000 ms. The supervisor owns every argument/path. The
child creates its own process group, requests TRACEME, stops before exec, then
executes exactly the supplied absolute command. The parent attaches fork/vfork/
clone/exec event tracking with EXITKILL and acts as a child subreaper. It retains
the target's actual exit code (or 128+signal), reports deadline as 124 and
observer failure as 125. Signal-delivery SIGSYS is forwarded unchanged, including
the kernel siginfo; a guest SIGSYS handler can still receive it.

JSON diagnostic lines use `observer` as a discriminator. A `sigsys` line includes
the actual `si_code`, `si_errno`, `si_syscall` and `si_arch`. `syscallKnown` is true
only for Linux SYS_SECCOMP (si_code=1); userspace-generated SIGSYS has no reliable
syscall identity. A seccomp KILL action may provide only a signaled exit, without
a SIGSYS delivery stop; this tool must then leave the syscall unknown. It uses
PTRACE_CONT, not syscall emulation or syscall stepping.

The child keeps standard streams; unexpected inherited descriptors are closed.
Observer diagnostics reopen stderr with a separate nonblocking file description
and CLOEXEC, leaving the tracee's stderr flags unchanged. The supervisor must own
that pipe/file, as the Android app does. Missing/non-reopenable diagnostic output
fails before spawning. Dropped diagnostic bytes make the result fail. The service
must still drain and bound stdout/stderr from the actual trusted command.

Cleanup kills only tracked, unreaped child PIDs, never parsed PPid values or
unrelated process groups. On cancellation, deadline, error or root-child exit it
reaps the traced descendants, including detached children; cleanup has a 5-second
bound. An uninterruptible child can make complete reaping impossible: that is
explicit failure, with EXITKILL still active, never a cleanup success claim.

Build with `tools/executor/native-runtime-observe-build.sh` in WSL. Host and NDK
Android ARM64 executables are built using -Wall -Wextra -Werror; the Android
binary uses the project's 16 KiB ELF alignment. No Android build, manifest,
installation, or Git operation is performed by that script.

Latest reviewed build:
`downloads/native-files/foldgpt-runtime-observe-zDKNPzQl/`.
Android SHA256:
`9403f5571e984308dd375c3dbc7eee83862836965166e96d8b414afcb84fd708`.

Host nonroot checks pass for an actual seccomp-TRAP getppid (syscall 110 on
x86_64), unchanged signal delivery to the guest's SIGSYS handler, default fatal
SIGSYS exit159, detached child cleanup, deadline exit124 and removal of an
actually inherited FD9. Evidence:
`/var/tmp/foldgpt-observer-test-_hx_wet7/results.json`. These are observer checks,
not Android runtime qualification and not an inference about the Fold's failing
syscall.
