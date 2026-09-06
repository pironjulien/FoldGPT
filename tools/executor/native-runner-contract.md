# Native runner v1: implementation contract

This is a new bounded process backend, not the full managed Codex policy.
Implemented and tested on Linux without root/capabilities. The corrected
Android Zygote fixture now passes all eight cases on the Fold; see
`native-runner-android-test.md`. This does not establish full managed-policy
support or PRoot integration.

Invocation: `native-runner --result-fd N`. FD 0 carries one compact UTF-8 JSON
manifest and then EOF. The command receives an empty stdin pipe. The native
supervisor forwards command stdout/stderr on its own FD 1/2. FD N is a distinct
private pipe, closed in the command, carrying JSONL events:

```json
{"type":"started","pid":123,"policy":"landlock-basic-data-v1"}
{"type":"result","outcome":"exited","exitCode":0,"signal":null,"stdoutBytes":12,"stderrBytes":0,"cleanupComplete":true,"errorStage":null,"errno":0}
```

`started` is emitted only after native setup and successful exec are confirmed.
The supervisor observes the kernel's `PTRACE_EVENT_EXEC` and immediately detaches
before target userspace runs; it does not infer exec from EOF on an error pipe.
Ptrace is then unavailable to command code under seccomp. This extra startup
requirement must be validated in the eventual Android environment.
Outcomes: `exited`, `timeout`, `output_limit`, `cancelled`, `setup_error`,
`cleanup_error`. No `started` is emitted for a failed setup/exec. A normal
command's nonzero exit remains `exited` with its actual exitCode. The runner exits
0 for `exited`, 1 for other outcomes, and 2 for an invalid invocation/manifest.
SIGTERM/SIGINT request cancellation; descendants are terminated and reaped before
the result. Output is byte-exact up to the shared bound. No TTY, interactive stdin,
filesystem RPC, resumable/disconnected execution or protocol server is advertised.

The manifest has exactly these fields (no unknown keys or duplicate keys).
Its native UTF-8 JSON parser accepts strings, nonnegative bounded integers,
objects and arrays only; booleans/null/floats are not fields of this schema.
Escapes and Unicode are decoded before duplicate/name/path validation. NUL,
invalid UTF-8, malformed/extra content, excessive depth/size and unknown access
tokens are rejected. There is no JSON library or Python dependency in the runner.

```json
{"schema":"foldgpt.native-runner.v1","policy":"landlock-basic-data-v1","metadata":"visible","network":"deny","ipc":"private-pipes-only","workspace":"/absolute/private/workspace","cwd":"/absolute/private/workspace","executable":"/usr/bin/dash","argv":["/bin/sh","-c","printf success > value.txt"],"env":{"PATH":"/usr/bin:/bin","LANG":"C"},"grants":[{"kind":"directory","path":"/absolute/private/workspace","access":["read","write"]},{"kind":"file","path":"/usr/bin/dash","access":["read","execute"]},{"kind":"file","path":"/usr/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2","access":["read","execute"]},{"kind":"file","path":"/usr/lib/x86_64-linux-gnu/libc.so.6","access":["read"]}],"limits":{"wallMs":10000,"outputBytes":1048576,"addressSpaceBytes":268435456,"fileBytes":1048576,"openFiles":64,"uidProcesses":64}}
```

Paths must be canonical absolute existing filesystem objects. The sample runtime
paths must be resolved from the installed host, not copied blindly to another OS.
Only explicit additive Landlock grants are supported. Unknown fields, denied
subpaths/carveouts, globs, URI rules and other profiles fail before exec.
The workspace is an owned mode-0700 directory; all writes remain within it. Its
existing tree must contain only owned private regular files and directories;
symlinks, special files and pre-existing regular-file hardlinks are refused.
Inspection pins entries with O_PATH before reading directories, so it does not
activate a device or FIFO while deciding its type. Directory grants are supported
only inside that workspace; external runtime dependencies require exact regular
file grants. `/`, `/proc`, `/sys`, and `/dev` are refused. External administrators
must not mutate the workspace or runtime namespace during a command. This is not
hostile-host isolation. The bounded initial scan accepts at most 100,000 objects
and depth 64; it is not a substitute for excluding hostile outside writers.

`metadata: visible` explicitly admits path metadata visibility. `write` supports
ordinary file data, regular file/directory creation, removal and renames within
the granted workspace, not chmod,
chown, timestamps, xattrs or arbitrary ioctls. Those unimplemented syscall families
are refused. A future managed-policy adapter must reject policies whose semantics
cannot be preserved; it must never flatten protected metadata or deny exceptions.

Security setup: fresh process group/domain; Landlock ABI >= 6 before exec; explicit
runtime grants; no inherited command environment or non-protocol descriptors;
seccomp with architecture validation and a syscall allowlist, no sockets, System V
or POSIX message queues, process-memory/ptrace/foreign-FD interfaces, io_uring,
namespace creation or process-group escape. Clone flags are constrained; clone3
returns ENOSYS so libc can use the inspected clone path. Signals remain constrained
by Landlock's signal scope. CPU/address-space/FD/file/process limits complement wall/output
limits; uidProcesses is an actual per-UID RLIMIT_NPROC ceiling, not a fictional
per-command count. No root or effective/permitted capabilities are allowed.
The accepted bounds are wallMs 1..3,600,000; outputBytes 1..67,108,864;
addressSpaceBytes 16,777,216..17,179,869,184; fileBytes 1..1,073,741,824;
openFiles 16..1024; uidProcesses 1..256. Core files are disabled, umask starts
at 077, and the CPU hard/soft limit is derived from the declared wall budget.

`addressSpaceBytes` sets both the soft and hard **RLIMIT_AS** exactly as declared.
It is a per-process virtual-address-space ceiling, including `PROT_NONE` and
`MAP_NORESERVE` mappings. It is not an RSS/physical-memory ceiling and is not
aggregated across descendants. No unsupported resident-memory guarantee is
advertised. A caller needing such a guarantee cannot substitute this profile.
The upper accepted bound is 16 GiB, the smallest binary-sized ceiling containing
the inspected NDK r29 Scudo fixture's 8.5 GiB envelope; it is not a default or a
hidden allowance. Existing Linux shell tests still declare only 256 MiB.
Scudo's 33 regions of 256 MiB reserve 8.25 GiB virtually, which explains why the
old 256 MiB Android fixture and even the old 8 GiB validation maximum failed.
The Android fixture now declares 8.25 GiB plus its separately named 256 MiB
address-space headroom, totaling 9,126,805,504 bytes. See the exact ELF/DWARF
evidence and the actual over-limit mmap test in `native-runner-android-test.md`.

Read-only scheduler queries `sched_getscheduler`, `sched_getparam`, and
`sched_getaffinity` accept only argument PID zero, whose kernel meaning is the
calling thread. Explicit PID/TID values and nonzero high bits are refused,
including a numeric caller PID. That rule remains correct after fork and for
new threads. Scheduler mutations remain denied. The default Bionic inheritance
path uses PID zero; custom scheduler policies are not advertised.

The supervisor is a child subreaper and owns one process group. It kills that group
on timeout/cancel/output exhaustion and when the command leader exits, then reaps
its descendants. Background children therefore belong to this command's lifetime.
Cleanup failure is reported, never a successful completed command. This initial
contract does not promise cleanup after SIGKILL/crash of the supervisor itself or
termination of a kernel-stuck task; a future persistent exec-server needs a separate
crash-recovery design.

Run `bash tools/executor/native-runner-build.sh` under WSL with GCC and NDK r29.
It records sources, static host/Android builds, ELF headers, hashes and actual
test output under ignored `downloads/native-runner/`. The Linux suite runs as
`nobody` if the build caller is root. It exercises the real shell, data grants,
output accounting, exec refusal, cancellation/timeouts, descendant cleanup,
strict manifest rejection and real refused IPC/process/network syscalls. A
separate test runs the parent's real `NativeRun` streaming client against this
backend and validates actual command results. No official executor RPC or model
request is involved yet.
