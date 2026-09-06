# Native exec and concurrent peer isolation diagnostic

This increment extends the fixed A/B/C/A experiment with **real `execve`**, a
private-memory/descriptor check and concurrent attacks against an authorized
worker. It is not a general executor, an APK or proof of an Android runtime.
The original `native-abc-probe.c` is unchanged; the new C translation unit
includes its real-syscall fixture helpers under a renamed reference entry point.

## Run

```powershell
wsl --distribution Ubuntu-24.04 --exec bash /mnt/c/Dev/ChatgptFold/tools/executor/native-exec-peer-build.sh
```

The recipe uses Linux x86_64, GCC with static libc, readelf, Python 3 and the
verified Linux NDK r29 at `/opt/foldgpt/android-ndk-r29` (`ANDROID_NDK_HOME` may
select that installed toolchain elsewhere). It checks the NDK revision and
records compiler versions. Sources and binaries are built in a fresh ext4
`/var/tmp/foldgpt-exec-peer-build-*`; the resulting evidence is copied to a new
ignored `downloads/native-exec-peer/` directory. It never changes the existing
runtime, original probe, vendor sources, APK, account or global kernel policy.

The Linux binary refuses UID 0 and any effective/permitted capabilities. If the
build runs as root, the recipe invokes only the probe through `runuser -u nobody`;
otherwise it runs under the current unprivileged user. No user is created.
All test data lives in its own mode-0700 disposable directory, which is removed
after the workers are reaped. An unnamed memfd contains only random fixture data.
No user document is used as an attack target.

Both targets compile with `-std=c11 -O2 -static -Wall -Wextra -Werror`. The Android
target is API 35 AArch64, with 16 KiB LOAD alignment. The recipe verifies machine,
static ELF type, absence of dynamic table/interpreter, LOAD permissions/alignment
and non-executable stack. Static executables avoid granting a whole runtime or
loader directory; this choice serves this fixed diagnostic, not the future
general executor's executable/runtime contract.

## Exec and inherited authority

The parent creates one unpredictable 32-byte memory sentinel, a changed global
marker, a non-CLOEXEC memfd holding the sentinel, and a parent-only environment
variable. It retains those while forking. Each child:

1. Keeps only a command pipe on FD 0 and report pipe on FD 1, then calls the real
   `close_range` syscall. FD 2 is closed too. The deliberate non-CLOEXEC private
   memfd must not survive.
2. Applies `NO_NEW_PRIVS` and its Landlock policy **before `execve`**. A gets exact
   target read/write/truncate, B read only, and C no target access. All three get
   one exact positive-control file, the exact static executable and READ_DIR on
   their own `/proc/self/fd` for descriptor inspection. No rule grants `/`, broad
   runtime reads or access to another process's proc directory.
3. Executes the same static file with a deliberately empty environment. The
   fresh image checks that the modified parent global is reset, the parent
   sentinel's global storage is zero, the environment is empty, and the complete
   `/proc/self/fd` inventory contains only the two pipes plus its temporary
   enumeration handle. It also requires dumpability 1 and seccomp mode 0 so
   those cannot silently account for later peer denials.
4. Waits while the independent parent reads the child's actual readable memory
   mappings using `process_vm_readv` and searches for the private sentinel.
   The scanner's positive control first locates the sentinel in the parent's
   own memory. Kernel-generated `[vvar]`, `[vvar_vclock]` and `[vsyscall]` mappings
   are explicitly excluded; any failed/partial read of another readable mapping
   fails the diagnostic. This is a concrete sentinel test, not a claim that all
   possible secret channels have been eliminated.

After that handshake, A1/B/C/A2 perform the same direct file-data operations as
the earlier probe. The unrestricted parent checks actual bytes and original
inode/device/mode/owner/group/link count independently after each worker. A
separate excluded sibling must remain unreadable/unwritable to every worker.

## Concurrent peer control

An exec'ed A worker remains alive with a permitted target file open and its
contents in memory. Two further exec'ed siblings test that same live A:

| Sibling | `process_vm_readv` | `ptrace` | `pidfd_getfd` |
| --- | --- | --- | --- |
| Explicit unconfined positive control | Must read the known actual bytes | Must attach, wait for the actual ptrace stop, PEEKDATA the known word and detach | Must duplicate A's real FD and read the expected target bytes |
| Landlock C | Must return a permission error and no data | Attach must return a permission error | `pidfd_open` must succeed, then `pidfd_getfd` must return a permission error |

To distinguish Landlock from Yama's ordinary sibling restriction, **A grants
`PR_SET_PTRACER` to each exact live test sibling PID**, after the parent handshake.
This is confined to the disposable target process. There is no
`PR_SET_PTRACER_ANY`, capability gain, sysctl write, security-module disablement
or global permission change. The recipe records Yama's setting before and after
and requires them to match. The target's UID, dumpability and Landlock A domain
remain the same for both siblings; their credential/capability checks match.
Both siblings use the same executable, empty environment, descriptor cleanup and
`NO_NEW_PRIVS`; C additionally has the installed Landlock domain.

An unavailable or denied positive control is **INCONCLUSIVE/FAIL**, not a policy
pass. The test stops there. Missing syscalls, a failed `pidfd_open`, unreadable
memory, timeout, dead target, unexpected bytes, or failure after a successful
ptrace attach are not accepted as C's required access denial. Parent file checks
also run after each peer test. The parent kills only its unreaped direct children
on failure and has bounded protocol and reaping deadlines.

## Observed evidence and limits

Initial native run on 6 September 2026: WSL
`6.18.33.2-microsoft-standard-WSL2`, Landlock ABI 7, UID 65534 without effective or
permitted capabilities, Yama `ptrace_scope=1`, worker seccomp mode 0.
All seven exec'ed images contained only the two protocol pipes, an empty
environment and no parent sentinel in **1,208,320 readable user bytes each**.
A1/B/C/A2 passed; B rejected target writes and C target reads/writes with
`EACCES`. The concurrent positive control read 128 memory bytes, attached/read/
detached with ptrace, and duplicated/read A's actual FD. C returned **EPERM (1)**
for all three attacks. Counts and PIDs can vary on another build/run.

The recipe retains raw host output, ELF inspection and verification, compiler/
kernel information, before/after Yama values, source copies and SHA-256 sums.
Android ARM64 is **compiled and inspected only**. Nothing here establishes the
same result under Samsung SELinux, its kernel or the application UID.

This proof covers fixed native data operations, clean exec startup and these
three concurrent access paths. It does not cover metadata confidentiality,
hardlink/rename/path races, IPC descriptor passing, all process interfaces,
network isolation, arbitrary descendants, a dynamic loader or guest runtime,
policy compilation, cancellation protocol, executor RPC, Desktop commands,
`apply_patch`, Remote, updates or release readiness. PRoot and the official
client are not involved. A general executor still needs those separate checks.
