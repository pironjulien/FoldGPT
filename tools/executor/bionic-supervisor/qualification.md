# Minimal Shizuku kernel qualification: prepared on PC, not run on Android

Checkpoint: `downloads/bionic-supervisor/foldgpt-bionic-supervisor-8Kd8xQRE`.
Native PC directory: `/var/tmp/foldgpt-bionic-supervisor-8Kd8xQRE`.
The build contains frozen sources, Android PIE files and ELF reports, 19 real
factory tests, the two original native kernel cases, and `qualification.json`.
All those PC tests passed as UID/GID 65534. No adb command or phone operation
was performed by this work.

Android supervisor SHA256:
`4652966bb36c388ee9c26a9b6e6432a09f4bbbb339c230e320511c512b7e5028`.

Android fixed worker `libfoldgpt_qualification_worker.so` SHA256:
`1f7054085ecfd920626cdf24603687cd5e9812b445cf171a2f4cff8efbecd3aa`.

## What the fixed worker actually proves

`qualification-worker.c` has no shell, command argument, environment-controlled
operation or network workload. It requires all real/effective/saved UID/GID
values to equal 2000 on Android or 65534 on the host, plus no_new_privs and
seccomp before touching its fixed workspace names. Under the real runner:

1. An openat of `input` requires reading the actual worker pointer through the
   supervisor's pinned `/proc/TID/mem`, a policy decision and real ADDFD. The
   worker reads and compares the exact 14 bytes `pin-memory-ok\n`.
2. A newfstatat of `input` requires writing the real stat result through that
   same memory API. The worker verifies type, size and owner.
3. A real getdents64 of `directory` requires pidfd_getfd. It checks the returned
   directory records and verifies that lseek on its own FD observes the exact
   returned d_off, proving a shared file description/offset rather than a
   separate `/proc/fd` reopening. The only names are `.`, `..`, `marker`.
4. Reading `private/secret`, writing `.git/config`, raw chdir, IPv4 socket,
   ioctl and opening `/dev/binder` must actually fail with the stated errno.
5. A real secondary pthread repeats all four mechanism groups and reports
   threadMemory and threadPidfdGetfd only after they all pass. The broker pins
   the notification's exact TID using pidfd_open(..., PIDFD_THREAD); it never
   substitutes the thread-group leader.
6. Success also requires one exact JSON worker record, empty stderr, worker
   exit0, supervisor exit0, native started=true/outcome=exited and a final
   cleanupComplete=true. The private sentinel must remain unchanged and no
   `.git/config` may have appeared.

The fixture validates these necessary mechanisms in the main and one secondary
thread of a real process. It does not claim general shell compatibility or
Android qualification from host results.

## Exact PC invocation

```text
wsl.exe -d Ubuntu-24.04 -u nobody --exec python3 -B /var/tmp/foldgpt-bionic-supervisor-8Kd8xQRE/package/tools/executor/bionic-supervisor/qualification.py /var/tmp/foldgpt-bionic-supervisor-8Kd8xQRE
```

The CLI exclusively creates a fresh workspace under `/var/tmp` and records its
evidence outside that workspace. It refuses uid0 and Android invocation. The
record's androidExecution field is observed from sys.platform, not supplied by
a test option. Successful PC evidence is already retained in the build; the
command is supplied for review, not an instruction to repeat unchanged tests.

## Android integration contract for independent review

Use the existing authenticated Shizuku ExecServer/JNI transport, in actual
UID/GID2000, SELinux `u:r:shell:s0`, with no effective/permitted/inheritable or
ambient capability. Do not invoke the old GNU/PRoot/ptrace runtime or replace
the previous successful fixed-lab probe. This is a new disposable qualification
deployment, for example:

`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v1/workspace`.

Prepare this previously nonexistent directory as shell-owned mode0700. Fixed
contents, all files mode0600 and directories mode0700:

```text
input                 pin-memory-ok\n
private/secret        probe-private-unchanged\n
directory/marker      marker\n
.git/                 empty directory
```

The installed, reviewed backendOptions must map only the logical executable
`kernel-qualification` to its packaged worker ELF. The runner and both file
helpers come from the frozen build and the APK native directory. The workspace
URI and actual pinned workspace must match. The worker argument vector is
exactly `["kernel-qualification"]`, with an empty explicit environment, no TTY
and closed stdin. No cwd shim is necessary for this minimal probe; direct
chdir remains a required negative check.

Required child runtime grants: the exact packaged worker RX, `/system/lib64`
RX, `/system/bin/linker64` RX, `/apex/com.android.runtime` RX,
`/linkerconfig/ld.config.txt` R, `/dev/__properties__` R and the exact official
`/apex/com.android.tzdata/etc/tz/tzdata` R. These reuse the previously measured
Bionic runtime contract. Do not grant `/linkerconfig` itself: Samsung's getattr
denial was observed. Do not grant `/proc` or general `/dev` to the worker.
The trusted Python bootstrap separately needs its attested installed Python
runtime; it is not a child runtime permission expansion.

Resource options are fixed for this small worker: wall_ms3000, cpu_seconds1,
uid_task_budget2, data_bytes16777216, file_bytes1048576, output_bytes8192,
descriptors32. They remain kernel per-process/shared-UID limits, not aggregate
physical memory or job cgroup guarantees. Native cleanup has its existing
five-second deadline and retains the actual owner if cleanup is still pending.

After the normal initialize / initialized handshake, send this exact start
request through the authenticated ExecServer session:

```json
{"id":2,"method":"process/start","params":{"processId":"kernel-qualification","argv":["kernel-qualification"],"cwd":"file:///data/local/tmp/foldgpt-bionic-supervisor-qualification-v1/workspace","env":{},"pipeStdin":false,"tty":false,"sandbox":{"permissions":{"type":"managed","file_system":{"type":"restricted","entries":[{"path":{"type":"path","path":"file:///data/local/tmp/foldgpt-bionic-supervisor-qualification-v1/workspace"},"access":"write"},{"path":{"type":"path","path":"file:///data/local/tmp/foldgpt-bionic-supervisor-qualification-v1/workspace/private"},"access":"deny"}]},"network":"restricted"},"cwd":"file:///data/local/tmp/foldgpt-bionic-supervisor-qualification-v1/workspace","workspaceRoots":["file:///data/local/tmp/foldgpt-bionic-supervisor-qualification-v1/workspace"],"windowsSandboxLevel":"disabled"}}}
```

Collect process/output, process/exited and process/closed notifications and the
equivalent process/read result. The expected worker JSON is:

```json
{"type":"kernel-qualification","success":true,"memoryRead":true,"memoryWrite":true,"pidfdGetfd":true,"sharedOffset":true,"privateReadDenied":true,"protectedWriteDenied":true,"rawChdirDenied":true,"networkDenied":true,"ioctlDenied":true,"binderDenied":true,"threadMemory":true,"threadPidfdGetfd":true}
```

No missing true field, extra output, wrong errno, setup diagnostic or missing
cleanup result is a pass. Retain native lifecycle evidence internally as well
as public RPC output. Close the session only through its normal control route;
the bootstrap must report closed/cleanupComplete=true and the JNI wait owner
must actually reap it. Independently collect process absence and the same boot
ID before/after, plus unchanged boot green/locked/warranty0 and SELinux state,
as in the previous report. Do not change any of those settings to make the
probe pass, delete a quarantine marker, kill its retained supervisor, or retry
automatically after an unknown cleanup result.

## Why Android must measure the two APIs

The Linux6.6 implementation of
[`/proc/PID/mem`](https://github.com/torvalds/linux/blob/v6.6/fs/proc/base.c#L802)
pins the mm but authorizes it through `mm_access` with ATTACH/FSCREDS; source
blob `ffd54617c35478e92a9f6bef67013e16e6cd3183`.
[`pidfd_getfd`](https://github.com/torvalds/linux/blob/v6.6/kernel/pid.c#L669)
checks `ptrace_may_access(...PTRACE_MODE_ATTACH_REALCREDS)`; source blob
`6500ef956f2f885793833e160891b4f441acd104`. These are kernel access checks, not
ptrace attach calls. This backend never invokes the ptrace syscall. The real
Android SELinux domain and dumpability must nevertheless allow these checks;
the previous fixed Shizuku trial did not exercise them. Refusal means this
backend has failed a necessary condition and must not be selected for model
commands. It does not authorize changing SELinux, root, Knox or dumpability.

Sources were checked via the GitHub repository connector on 2026-09-07. The
integrated browser was unavailable; no external browser was opened.

The observed Fold kernel is
`6.12.58-android16-6-p6370076-abogkiF971BXXS2AZH7-4k`. Matching upstream stable
[`v6.12.58/kernel/pid.c`](https://github.com/gregkh/linux/blob/v6.12.58/kernel/pid.c)
(blob `b80c3bfb58d07fbec23aed82a3592249f0cc6593`) admits PIDFD_THREAD in
pidfd_open and resolves pidfd_getfd with PIDTYPE_PID. Its real-credentials
access check remains required. The matching
[`pidfd.h`](https://github.com/gregkh/linux/blob/v6.12.58/include/uapi/linux/pidfd.h)
(blob `565fc0629fff5e575189078b9ce6a452e82c7ae5`) and NDK r29 both define
PIDFD_THREAD as O_EXCL. Host verification used WSL Linux6.18.33.2.

## Independent integration/security checks and remaining work

The JNI source was reread: it verifies shell identity and zero capabilities,
duplicates stdio/control before fork, closes every child FD >=4 and execs only
the installed fixed bootstrap. Its separate fd3 lifecycle channel is marked
close-on-exec by the Python host before worker creation. The native runner then
performs its own descriptor allowlist, fresh process group, PDEATHSIG, resource
limits, Landlock and two seccomp filters before executing the worker.

The separate cwd shim was reviewed: it calls only openat of a readable
directory, fchdir and close, preserves errno and has no cancellation-point
wrapper or privilege operation. Factory refusal now also checks the resolved
runtime path against the workspace: an alias cannot grant workspace execution.
A real constructor test proves this rejection and FD cleanup. Cwd-shim digest
reads are bounded even if a source grows; failed attestations retain no FD or
workspace flock. APK admission must establish the stronger nativeLibraryDir
immutability boundary; mode0644 alone does not isolate another writer sharing
the same UID.

Independent review found and corrected two real issues before this checkpoint:
pidfd_open with flags0 did not admit non-leader TIDs, and cleanup promotion in
the Python finally path could rely on a native record without an actual owner
wait. The current tests verify exact real threaded directory entries and keep
the lease/quarantine when a host-only fault supervisor stops after its final
record. A separate host-only fault supplies ENOENT during getdents memory
setup; the actual Python listing now raises EOPNOTSUPP, never a successful
empty list. The same error preservation covers descriptor pinning and other
broker setup before the actual getdents syscall. Neither fault runner is
compiled for Android. Older ZBbervqT/UwX0Qj9H checkpoints predate these fixes
and must not be selected for deployment.

Before expanding the process surface, retain this checkpoint for review. The
next Python-project mutations to implement are unlink/rmdir and atomic
rename/replace, with complete source/destination and protected-metadata policy
checks and native identity validation. Workspace symlink/hardlink/worktree
support and execution of newly compiled files remain separate capabilities.
None of these gaps should be hidden by disabling managed policy.
