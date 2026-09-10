# Fixed native runner diagnostic for Android debug builds

This prepares a device test of the limited `landlock-basic-data-v1` backend.
The same native fixture passed on Linux as `nobody`; the Android ARM64 files
compile with NDK r29 and 16 KiB segment alignment. The service compiles against
Android API 37. The parent's initial Zygote run of the earlier revision failed
with a denied scheduler query and insufficient Scudo virtual address space.
The corrected revision was installed and run through the real Zygote service
on 6 September 2026: UID 10412, inherited seccomp 2. All eight cases passed,
including real pthread allocation, outside-read/network refusal, virtual-address
limits, failed exec, timeout, cancellation, output limit and descendant cleanup.
The parent independently reread the created and protected files. This remains
the limited native backend, not the full Codex executor.

Run under WSL with GCC and `/opt/foldgpt/android-ndk-r29`:

```sh
bash tools/executor/native-runner-android-build.sh
```

The script snapshots inputs, compiles three native executables for Linux and
Android, runs the Linux checks without privileges, then retains logs, ELF
headers and hashes under `downloads/native-runner/`. It does not change the
APK's native library inputs, package an APK or invoke ADB.

For a separately authorized debug build, copy **only** the three `.so` files
from that run's `android/` directory into `android/native/debug/arm64-v8a/`:

- `libfoldgpt-native-runner.so`: unchanged general native backend.
- `libfoldgpt-native-runner-fixture.so`: static fixed test executable.
- `libfoldgpt-native-runner-probe.so`: independent native supervisor/checker.

These are executables named for Android's existing extracted-native-library
packaging convention. They are not loaded through JNI. The debug manifest
registers `app.foldgpt.NativeRunnerProbeService` in a separate process with
`android.permission.DUMP` protection. Release builds contain neither that
service nor these debug-library inputs. The service accepts no command/path
extras and derives its paths exclusively from the Android context.

After the parent builds and installs the debug APK, the intended explicit
diagnostic entry point is:

```sh
adb -s DEVICE_SERIAL shell am start-foreground-service \
  -n app.foldgpt/.NativeRunnerProbeService
```

Results are in the app's
`cache/native-runner-probe.log`; each invocation also retains its own private
cache fixture directory. A subsequent explicit invocation replaces the common
log. The ordinary Linux runtime, profiles, keyring and official client are not
opened, started, stopped or changed by this probe.

## Actual assertions

The unconfined fixed control first proves that the outside fixture is readable,
the test peer exists and an unconnected network socket can be created. The
confined executable must then observe real outside-file, socket and peer-signal
denials. It must also observe `no_new_privs`, active seccomp, an absent synthetic
parent environment variable and closure of an explicitly inherited file FD.

Eight invocations exercise:

1. Real file creation and append, fork/pipe/wait, separate exact stdout/stderr.
2. A read-only workspace rejecting truncation of an existing file.
3. The exact soft/hard address limit, real malloc/free and pthread creation,
   a small mapped/touched page, `ENOMEM` for a `PROT_NONE` mapping larger than
   the full limit, and `EPERM` when trying to raise the hard limit.
4. Missing execute permission producing setup failure and no `started` event.
5. Wall timeout with a reaped command.
6. SIGTERM cancellation after the actual exec handshake.
7. A real output flood stopped at exactly 8,192 bytes.
8. A forked background child, followed by independent verification that it no
   longer exists after the runner reports cleanup.

The harness independently reads the created and protected file bytes after
all commands. Its success marker is `independent_native_runner_verification=PASS`.
Any failed assertion exits nonzero. Failed runs try to terminate and reap their
own children, confirmed by kernel `waitid`, including adopted descendants.
This does not promise recovery after SIGKILL or an unkillable kernel task.

The policy is deliberately unchanged: no PRoot, real Linux shell, TTY, account,
model request, managed-policy adapter or Remote integration is introduced here.
The static fixture tests Android-native execution; the existing host suite
separately validates a real `/bin/sh`. Android's inherited Zygote filter, SELinux,
Landlock ABI, exec/ptrace handshake and per-UID process accounting can still
refuse this profile. Such a refusal is diagnostic evidence, never a reason to
disable a protection or print a success result.

The fixture declares `uidProcesses=256`, the supported upper bound of the real
per-UID `RLIMIT_NPROC`. Other processes/threads belonging to the app count toward
that limit; it is not a private per-command allowance. The service's outer
deadline is 80 seconds plus a cancellation grace period, while each harness
invocation has its own 10-second failure bound.

## Android allocator and scheduler corrections

The previous on-device failure reported Scudo's exact requested size of
8,650,752 KiB. `native-runner-scudo-check.py` reads the **actual linked ARM64
ELF's DWARF**, checks its region geometry and records the relevant disassembly:

- `external/scudo/config/custom_scudo_config.h:144`: `RegionSizeLog=28`.
- `external/scudo/standalone/primary64.h:524`: region size 268,435,456 bytes.
- `primary64.h:525`: 33 classes; total initial reservation 8,858,370,048 bytes.
- `SizeClassAllocator64::init` passes that exact size to `createImpl`, which
  calls `mmap64` with `PROT_NONE` and `MAP_PRIVATE | MAP_ANONYMOUS | MAP_NORESERVE`.

The default Scudo allocator remains linked and unchanged. The fixture explicitly
declares that 8.25 GiB virtual reservation plus its pre-existing 256 MiB workload
address budget, yielding **9,126,805,504 bytes (8.5 GiB)**. The equivalent Linux
fixture keeps 256 MiB because it does not link Android Scudo. The control logs
its real `VmSize`, `VmPeak`, `VmRSS` and `VmHWM` after allocator/thread startup.
If a future NDK changes the checked allocator geometry, the build refuses to
reuse this derivation and requires review.

This is **not 256 MiB of resident RAM**. Primary regions can acquire physical
pages within their reservation; RLIMIT_AS limits each process's total virtual
space. No process-tree RSS budget is claimed. The overflow test requests only
a `PROT_NONE` mapping, so it verifies the real kernel limit without committing
gigabytes or provoking the system OOM killer.

The exact NDK Bionic `__init_thread` disassembly uses `sched_getscheduler(0)`
and `sched_getparam(0)` for inherited scheduling. Seccomp now permits those
read-only operations and `sched_getaffinity(0)` only for PID zero. Peer queries,
high-bit PID tricks and scheduler mutations are tested and denied. The fixture
also requires an actual successful `pthread_create`/`pthread_join`, so the
original thread-initialization error cannot be hidden by merely allowing a
query that is never exercised.
