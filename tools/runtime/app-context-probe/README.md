# App-context feasibility probe

Prepared on PC on 8 September 2026. **Not executed on Android yet.** The current
source is this directory. Compiled candidates, keys and captured output remain
under `work/feasibility-survey-20260908/app-context/`. Earlier work-only build
directories are preserved development artifacts; use the current build report.

The separate application ID is `app.foldgpt.contextprobe`. It has target SDK 37,
minimum SDK 30, one DUMP-protected foreground Service, no Activity, no launcher
icon, no Shizuku service dependency, permission or call, and no internet permission.
The unchanged r25 inventory includes a transport ELF that this probe never loads
or invokes. A shell
command asks Android ActivityManager to start that component; Android creates
the process through Zygote. **The Python process is then launched by Java
ProcessBuilder inside that application**, never directly by shell or run-as.

The installed FoldGPT application and its native owner are not replaced or
stopped. No production configuration, bootstrap guard, phone setting, privileged
system operation or protection is modified. Probe output remains in the new
application's private files directory. Installation/uninstallation of this
separate diagnostic remains the root agent's responsibility.

## Existing entry points

`android/app/src/debug/java/app/foldgpt/NativeProcessRpcProbeService.java` is the
existing real Zygote entry (`app.foldgpt/.NativeProcessRpcProbeService`, process
`:processRpcProbe`). It starts the historical static process fixture and accepts
no command override. `NativeFilesRpcProbeService` and
`NativeManagedProcessProbeService` similarly run fixed older diagnostics.
They cannot select r25 pipe/PTY adapters. Replacing FoldGPT to change one would
stop its current runtime, so this independent APK is the smaller isolated test.

## What the test discriminates

The APK includes **89 byte-identical ELF files and 95 source files from the
verified r25 APK**, plus its 2,447 Python data files and this fixed harness.
Every extracted native library/source/data hash is checked when building and
again by the app before execution. The code is compiled with javac/D8/aapt2 in
under a minute, without Gradle, and signed with a newly generated diagnostic-only
key stored under its build directory. It has no production signing authority.

Two cases use the unchanged r25 `DirectProcesses` and `TtyProcesses` adapters:

1. Pipe: execute actual Bionic Python, create and independently read a file,
   spawn and wait for a second actual Bionic Python, roundtrip stdin, exit 23,
   actual owner wait 0, pipe EOF, native cleanup receipt and released lease.
2. PTY: same file/subprocess checks, actual fd 0/1/2 tty and 24 x 80 size,
   actual `process/signal interrupt`, KeyboardInterrupt and exit 130, then the
   same actual cleanup/wait/EOF conditions.

Java, Python supervisor and workers report real UID/PID/PPID/status. The harness
requires equal nonroot app UID, inherited seccomp 2, tracer 0, no effective or
permitted capabilities and no PRoot/GNU loader maps. The startup Python's PPID
must be Java; each worker's PPID must be its actual r25 native owner. Cgroup,
CPU allowance and total/available memory are recorded without changing them.
Owner status/cgroup are best-effort observations because r25 deliberately makes
its supervisor nondumpable. This does not alter that production behavior.

The separate package has a **different UID, app process, cgroup and storage
layout** from FoldGPT. It does not prove the complete production bootstrap can
be attached from the existing FoldRuntimeService. It does not test X11 rendering,
same-process GUI requirements, private controller sockets, network restrictions,
the managed dynamic broker, reboot recovery, or model/interface behavior.

Python data is relocated to the probe's own files. The unchanged CLI supports
ordinary `PYTHONHOME`; the fixed Java and worker environment selects that path
explicitly and uses `-B -s`. `-I` would ignore this necessary relocation, so it
is not used. No production guard is removed and no environment variable is
inherited from a user or shell. The r25 runtime itself is not rebuilt.

## Timeouts and ownership

Each worker arms its own eight-second alarm before exercising work. Each native
owner has a twelve-second wall limit and five-second cleanup grace. On failure,
the harness requests the normal native close/cancel path. Unproven cleanup keeps
the adapter, asyncio loop, native owner and foreground service alive; no PID kill,
synthetic cleanup success, forced-stop or recursive deletion is issued. Java
reports a timeout at 90 seconds and preserves that ownership for examination.
An ordinary successful test should finish in seconds. Evidence directories are
retained after success/failure, never silently removed.

## Device procedure (root agent only; not yet run)

Build from the project root, with a new output directory:

```powershell
python tools/runtime/app-context-probe/build.py --output work/feasibility-survey-20260908/app-context/versioned-build-v1
```

`--source-apk` and `--expected-apk-sha256` accept an explicitly selected verified
APK. Defaults point to the current r25 artifact and its exact SHA-256. The output
must be a new subdirectory beneath this project's `work`; source snapshots,
intermediate files, diagnostic signing key and logs stay there. The build
performs no device operation. SDK tools are read from the existing Android SDK.

First verify the live phone boot, FoldGPT APK hash, native owner readiness and
current owner PID/starttime. Install **only the separate diagnostic APK** after
checking that output's `build-report.json`, using `adb install` without replacement.
Then:

```text
adb shell am start-foreground-service -n app.foldgpt.contextprobe/.ContextProbeService
adb shell run-as app.foldgpt.contextprobe cat files/latest.txt
```

Read only the exact `probe-...` relative directory returned by `latest.txt`:
`report.json`, `java-identity.json`, `inventory.json`, `output.txt`, and
`android-completion.json` (or the explicit failure/timeout record). `run-as` is
only an evidence reader here. It must not run Python or any test executable.

Independently verify `passed=true`, two case successes, inherited seccomp 2,
Java/supervisor/worker lineage, real owner wait 0, `cleanupComplete=true`, no
quarantine and no retained ownership. Recheck the current production owner and
boot against the pre-test identities; avoid stale hardcoded PIDs.

Do not interpret `compiledAndVerified=true` as Android test success.

## Upstream sources actually read

GitHub connector reads and line-numbered excerpts are retained in
`work/feasibility-survey-20260908/app-context/upstream-source-excerpts.json`. They establish architectural possibilities,
not the exact Samsung current kernel result:

- [AOSP Zygote](https://github.com/aosp-mirror/platform_frameworks_base/blob/master/core/jni/com_android_internal_os_Zygote.cpp)
  applies `set_app_seccomp_filter()` to app UIDs during specialization. Matching
  the app UID via another launcher does not reproduce the inherited context.
- [Termux terminal JNI](https://github.com/termux/termux-app/blob/master/terminal-emulator/src/main/jni/termux.c)
  opens `/dev/ptmx`, sets tty dimensions, forks, calls `setsid`, redirects the
  slave onto standard streams, then execs and waits in the app process lineage.
  This supports the hypothesis that PTY primitives need no Shizuku, but does not
  qualify r25's additional ownership operations on the Fold.

Historical Fold evidence remains separate: `tools/executor/native-files-android-rpc.md`
records 34 responses/12 groups under Zygote/seccomp 2, and
`tools/executor/native-managed-android.md` records 17 static managed tests/46
process observations. Those September 6 APKs are not this new r25 probe.
