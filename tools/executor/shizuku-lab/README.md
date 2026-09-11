# FoldGPT Shizuku qualification

Separate diagnostic APK, package `app.foldgpt.shizukuprobe`. It neither patches
FoldGPT nor the official client. This is a qualification instrument, not the
production command executor and not a sandbox claim.

The 7 September development trial (its full report and APK are not distributed
in this source release) passed in the frozen `build/fixed-v5-7fa4f638/app-debug.apk`: native
Bash/Bionic Python, three tests, actual zipapp build/run, six interpreter
denials and complete cleanup. Its pinned guard is
`7fa4f638c431866e69dcda8618a3e8872b19861941d5d7bd1dbc8ec92352893b`.
Earlier builds and failures below are retained as historical evidence.
The final result covers the fixed offline operation, not generic commands or
ordinary model/client routing. No phone reboot or autostart test was performed.

## Context-only build

The frozen first APK exposes one fixed operation: collect the real Shizuku UserService
process context. It does not execute a shell, supplied command, native fixture,
namespace/seccomp/ptrace probe, or change a system setting.

- Official Maven SDK `dev.rikka.shizuku:api:13.1.5` and `provider:13.1.5`.
- Maven Central and Google's Android repository only; dependency artifact
  SHA-256 values are retained in `gradle/verification-metadata.xml`.
- Shizuku 13.x server protocol; root/Sui backends are excluded. The SDK provider
  has Sui auto-initialization disabled before its `onCreate`.
- Exported `.ProbeActivity` requires Android `DUMP` permission. The provider
  preserves the official `INTERACT_ACROSS_USERS_FULL` access restriction.
- Shizuku's standard authorization dialog is requested automatically after its
  Binder arrives. The app does not grant itself Shizuku permission.
- `UserServiceArgs.daemon(false)`, tag `foldgpt-context-v1`, version 1. The
  service requires UID 2000 and accepts `collectContext()` only from this APK's
  UID, derived from its trusted package context.
- Service destruction uses Shizuku's specified AIDL code `16777114` and exits
  only its own process. It has no descendants in this context-only build.
- Read errors remain explicit per observation. Core status/SELinux read failure
  makes the context report's `success` false. Parent/FD observations can become
  unavailable and are never invented.

The UserService is an ordinary process under the shared shell identity. Its
extra Android permissions must not be made available to arbitrary model code.
This context-only APK does not address the later worker confinement contract.

## Build on the PC

Prerequisites to install on the contributor's machine: Java 21, Android SDK API 37,
Android Gradle Plugin 9.3.1, Gradle 9.7.1. The project is independent of the
existing FoldGPT Android build. Configure `JAVA_HOME` and `ANDROID_HOME` for your
installation and put the Gradle 9.7.1 `bin` directory on `PATH`.

```powershell
gradle --no-daemon :app:assembleDebug
```

Run from this directory. The first build generated dependency verification
metadata; subsequent builds verify the recorded artifacts. Regenerating that
metadata is a deliberate source/dependency review action, not a way to accept
an unexpected hash.

Frozen context-only artifact:

```text
tools/executor/shizuku-lab/build/context-v1/app-debug.apk
SHA256 5cb61e3eb279a25bd9775c03d4005e010909bf8350936f19e77a3c77478cb20b
```

Host build and APK v2 signature verification passed. No on-device success is
implied by the APK being present. The initial compiler emitted seven missing
compile-only AndroidX annotation warnings; compilation and DEX packaging
succeeded. The SDK's annotation dependency is present in runtime metadata.

## Controlled device use by the main task

The following are operator instructions, **not commands executed by this
subtask**. Root starts official Shizuku in authorized ADB mode separately. This
APK does not enable wireless debugging, change its authorization timeout, or
automatically bootstrap Shizuku.

```powershell
adb -s <device-serial> install -r tools/executor/shizuku-lab/build/context-v1/app-debug.apk
adb -s <device-serial> shell am start -W -n app.foldgpt.shizukuprobe/.ProbeActivity -a app.foldgpt.shizukuprobe.COLLECT
adb -s <device-serial> shell run-as app.foldgpt.shizukuprobe cat files/report.json
```

Use the package's official permission dialog when it appears. After permission
is granted, binding and collection continue automatically. No successful
permission is inferred from elapsed time. `report.json` starts as `pending`,
then becomes `complete` or `failed`; bind/collection is bounded to 30 seconds
after binding begins. The Activity also displays the complete JSON.

An unknown action fails closed. This build supports only the exact `COLLECT`
action. The report is overwritten on a new attempt, so copy each finished
report into a separate host evidence directory before the next test. Do not
mistake `am start -W` completion for a completed Shizuku operation.

Required result checks:

1. `state == complete`, `success == true`, `serviceUid == 2000` and
   `shizukuServerUid == 2000`.
2. `authorizedClientUid == clientUid == callingUid`, while service/client UIDs
   differ. `servicePid != clientPid`.
3. Read `status`, `threadStatus`, `selinux`, `cwd`, parentage and FDs from this
   report; do not substitute earlier ADB-shell measurements for them.
4. Confirm the owned `app.foldgpt.shizukuprobe:qualification` process exited
   after unbinding. A service-removal error appears in the Activity and must
   be investigated; the report alone does not prove cleanup.

The main task subsequently ran this frozen context-only APK on the Fold. The
retained [context report](../../../downloads/shizuku-lab/attempt-20260907/context-report.json)
and [brief](../../../downloads/shizuku-lab/attempt-20260907/context-brief.json)
show the real UserService PID 32106, UID/GID 2000, SELinux `u:r:shell:s0`, process
and Binder-thread `Seccomp: 0`/filters 0, effective capabilities 0, and authorized
client UID 10350. This is now a UserService measurement, not an inference from
the earlier ADB-shell inventory. It executed zero commands. The main task also
confirmed this owned service disappeared after unbinding; no reboot occurred.

## Fixed native operation, version 2

The version 2 source adds a second fixed action, `app.foldgpt.shizukuprobe.RUN_FIXED`, using exactly
`/data/local/tmp/foldgpt-shizuku-lab/probe`, without arguments, and a SHA-256
embedded at build time. A build without an expected hash refuses the operation;
the hash cannot be supplied in an Intent or Binder request. Version 1 above is
unchanged and still has no execution API.

Build version 2 with `-PprobeSha256=<reviewed-native-executable-SHA256>` added to
the Gradle command. The file and its parent directory must be real filesystem
objects owned by UID 2000, with no group/other write permissions; the file must
be a regular executable. The UserService only reads/checks these properties.
It never fixes their permissions or substitutes another command. Java supplies
an otherwise empty environment with `PATH=/system/bin`; the native fixture
reconstructs its own environment and chooses its own workspace.

The native fixture owns its descendant cleanup, FD closure, confinement and
30-second deadline plus 5-second cleanup budget. Java captures stdout/stderr
independently, retains at most 32 KiB per stream and waits at most 45 seconds.
The native program must close all inherited FDs above 2 itself; this is not
assumed solely from Java's `ProcessBuilder`. The calling Activity's reporting
deadline is 60 seconds. There is one native attempt per service instance and
no automatic retry.

`success` requires actual process exit 0, complete untruncated stream capture,
and exactly one native JSON-line `type: "probe-result"` record. Its success,
cleanup and setup fields must be real JSON booleans, its exit/signal fields
integers, and its success outcome must be coherent with exit 0 and signal 0.
The full
output and final record are retained, so the main task must additionally
inspect the native fixture's real test and denial evidence. A process being
launched is not a successful fixture.

If the native guard has not exited by the outer deadline, Java **does not kill
the owner and orphan its descendants**: it retains the Process handle and the
UserService. Missing explicit cleanup evidence also retains the service. Its
`destroy()` refuses to exit while cleanup is unresolved. The Activity reports
that condition and schedules no new attempt; the main task must inspect the
owned process state before any further action. Version 2 uses a different tag
(`foldgpt-qualification-v2`) and service version (2).

After staging the reviewed native closure and installing the pinned version 2
APK, the main task invokes:

```powershell
adb -s <device-serial> shell am start -W -n app.foldgpt.shizukuprobe/.ProbeActivity -a app.foldgpt.shizukuprobe.RUN_FIXED
adb -s <device-serial> shell run-as app.foldgpt.shizukuprobe cat files/report.json
```

This is still a fixed diagnostic. Hashing a pathname before launch is a
provenance check for the controlled test, not a general solution to races with
another process under the shared UID 2000. No untrusted program is authorized
to alter this qualification's staged directory during the test. Production
isolation and the ordinary official-client routing remain separate criteria.
