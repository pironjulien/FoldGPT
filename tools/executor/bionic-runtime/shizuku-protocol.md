# Fixed Shizuku/Bionic qualification

This fixture qualifies a specific offline Python/Bash workload. It does not
implement Codex's managed sandbox policy, replace bubblewrap, expose a general
shell command service, or qualify arbitrary model-generated commands. It uses
no PRoot, ptrace, seccomp user notification, VM, root or client modification.

## Invocation and deployment

The independent Shizuku UserService must launch exactly
`/data/local/tmp/foldgpt-shizuku-lab/probe`, with no arguments. Its effective,
real and saved UID must be 2000, all three GIDs equal, and effective, permitted,
inheritable and ambient capabilities zero. The ordinary shell bounding set is
not treated as a granted capability. The wrapper supplies empty stdin, captures
both output pipes, and hashes the executable against its compiled expected SHA.
There is no required inherited environment or working directory. The native
guard supplies its target environment and working directory itself.

The deployment root must be an ordinary directory owned by UID 2000, mode 0700.
Required artifacts:

- `native/libfoldgpt_bash.so`: authentic compiled Bionic Bash executable.
- `native/libfoldgpt_python_cli.so`: Bionic CPython CLI, default home compiled
  as `/data/local/tmp/foldgpt-shizuku-lab/python`.
- `native/`: authenticated native dependency closure and declarative aliases.
- `python/`: authenticated official Python distribution data/extension aliases.
- `probe`: standard dynamically linked PIE ARM64 Bionic guard, 16 KiB ELF
  LOAD alignment, using Android's `/system/bin/linker64` and system `libc.so`.

`workspace` and `outside-sentinel` must not exist before this single run. The
guard creates both exclusively. It embeds the complete fixed Python fixture in
the hashed executable and passes it via a fixed Bash `exec` command. No Python
fixture file, user-supplied command, environment override or argv is accepted.

The operator must exclude concurrent writers sharing UID 2000 while verifying
and using the deployment. Directory modes and child Landlock permissions do
not isolate the runtime against a hostile external process with that same UID.
This is a qualification lab without secrets, not a production multi-client
deployment boundary.

## Startup correction after the first real launch

The original `-static-pie` build (`b4579de9...`) exited with SIGSEGV before
creating the workspace. The exact ARM64 artifact reproduces the crash on the
PC under QEMU user mode with the same environment (`PATH=/system/bin`): its
only logged syscall is `getpid`, followed by SIGSEGV at `0x78018`. The NDK
symbol table identifies that address as the Bionic `page_size` guard variable.
The image has 430 RELR relocations, no PT_INTERP, and unrelocated GOT pointers.

The Bionic [static initialization source](https://android.googlesource.com/platform/bionic/+/main/libc/bionic/libc_init_static.cpp),
blob `9cc3060f60a220456a96c740ae5c381f5c97f18b`, assumes load bias zero for TLS,
MTE and RELRO initialization; it does not perform static-PIE self-relocation.
Inspection of the actual NDK r29 startup disassembly confirms that the GOT is
read before any relocation. The identical C built as a conventional static
ET_EXEC is a **PC-only diagnostic control**: it reaches `main` and returns the
expected UID admission refusal, exit 70, under the same QEMU/environment.

The deployment build now uses the standard Android dynamic PIE startup with
the system `linker64`, `libc.so` and `libdl.so`. ASLR, RELRO/NOW, NX stack and
16 KiB LOAD alignment remain enabled; the confinement C and embedded fixture
are unchanged. `shizuku-check-elf.py` now enforces this loader contract in the
build itself. It rejects the original faulty artifact and accepts the corrected
dynamic PIE. No static diagnostic control is intended for phone deployment.

This identifies the first guard startup failure. It does not explain or
reproduce the earlier unrelated phone reboot events. A real Android run of the
corrected dynamic image is still a separate qualification step.

## Enforcement before the interpreter

The supervisor closes inherited descriptors 3 and above. The child receives
new private stdin/stdout/stderr pipes, closes all other descriptors except its
close-on-exec setup pipe, enables `no_new_privs`, installs resource limits, then
installs Landlock ABI 6 or newer and the existing explicit seccomp allowlist.
The child verifies restrictions before invoking Bash/Python. No Binder or
Shizuku control descriptor is passed to the interpreter.

Landlock handles filesystem rights 0 through 15, and both signal and abstract
Unix-socket scopes. The only writable tree is the fresh workspace. It allows
ordinary directories/files, including rename/removal, but no execute right or
device, FIFO, socket or symlink creation. Native binaries are readable and
executable; Python data is read-only. Android runtime read grants are:

- `/system/lib64` and `/apex/com.android.runtime`: read and execute.
- `/system/bin/linker64`: read and execute of the resolved regular file.
- `/linkerconfig/ld.config.txt` and `/dev/__properties__`: read-only runtime configuration.
- `/apex/com.android.tzdata/etc/tz/tzdata`: the official read-only Bionic timezone database.

The exact linker configuration file is readable under Samsung's shell domain;
the containing `/linkerconfig` directory denies `getattr`. The rule targets
the file directly instead of requesting access to that inaccessible directory.

No broad `/proc`, `/dev`, home-directory or shared-storage grant is installed.
There are no device grants, including `/dev/null` or `/dev/urandom`; the fixed
fixture uses pipes and `getrandom`. All sockets and ioctls are refused by
seccomp, including Binder ioctls. Foreign process interfaces are refused and
Landlock's signal scope denies the harmless `kill(supervisor, 0)` check.

The guard first confirms the outside sentinel can be opened read/write before
confinement. Both opens must fail with EACCES/EPERM after confinement. It also
checks real IPv4/Unix socket refusal, ioctl refusal, outside signal refusal and
opening a pre-existing Binder node. Python repeats six denials itself.

## Bounds and lifecycle

Command wall deadline is 30 seconds, followed by a five-second cleanup deadline.
CPU is at most 15 seconds per process, file size at most 8 MiB, data-segment limit
at most 256 MiB, stack at most 8 MiB, open descriptors at most 128. Output is
limited to 64 KiB total. The actual fixed fixture emits about 1.2 KiB on the host.
`RLIMIT_NPROC` is measured existing real-UID task count plus eight, or a lower
inherited hard limit; it is a shared-UID admission constraint, not a job cgroup.
These limits do not claim an aggregate physical memory cap. No RLIMIT_AS value
is guessed for Bionic's address-space reservations.

The guard is a subreaper. The child owns a fresh process group; seccomp prevents
session/group escape. The group leader remains unreaped until the guard sends
group SIGKILL, so the numeric group cannot be recycled before that operation.
No group signal is sent after reaping the leader. The guard also reaps adopted
descendants before confirming completion. Child death-of-parent protection is
set before target execution.

If cleanup cannot complete in five seconds, a `probe-cleanup-pending` event
reports `cleanup_complete=false`, `owner_retained=true`, `supervisorPid` and
`childPid`. The actual supervisor stays alive and retains ownership while
waiting; it never launches another command. The Java wrapper must retain this
process and UserService when its own 45-second deadline expires. It must not
pretend that a dead Process handle owns surviving descendants, nor destroy the
native supervisor to force a timeout result. An uninterruptible kernel task
cannot be made reapable by declaring a deadline.

## Results

Mixed stdout contains fixed Python test output and JSONL control events.
The final control object has `type=probe-result`, booleans `success`,
`setupCompleted`, `cleanup_complete`, string `outcome`, integer `exitCode` and
`signal`, and `supervisorPid`/`childPid`. A successful qualification requires
native process exit 0, `success=true`, `outcome=exited`, `exitCode=0`, `signal=0`,
`setupCompleted=true`, `cleanup_complete=true`, and complete captured streams.
Setup completion never claims an exec event based on EOF alone. Before-fork
refusals emit a final false result with cleanup true because no child exists.
Native exit is 70 on refusal/failure, 124 on a wall timeout, and 0 on success.

The fixture creates and edits a real Python project, runs three actual unittest
tests in a subprocess, creates and executes a zipapp, verifies real stdin,
stdout, stderr and exit 23, and launches children with an empty environment.
It retains `workspace/qualification-result.json` and the built zipapp.

`shizuku-verify-host.py` performs PC-only Linux checks using the same guard:
the fixed qualification, second-run rejection, output limit, descendant
termination/reaping, real 30-second timeout, and SIGTERM cancellation with a
final result. This host validation does not establish Android compatibility or
explain the previous phone reboot events.
