# Run-as V1 qualification: identity and four FDs

Separate APK `app.foldgpt.runasqualification.v1`. It does not update FoldGPT
or ChatGPT. Its shell2000 Shizuku UserService exclusively launches
`/system/bin/run-as app.foldgpt <its signed Bionic ELF> --identity-fds-v1 …`
through the unchanged production `NativeSpawn`. The target package must carry
the preserved FoldGPT signature and be debuggable. PackageManager identities,
install paths, APK fingerprints and libraries are explicitly cross-checked on
the Activity and UserService sides before launch, then again after the real
waitpid.

The ELF checks real/effective/saved UID/GID, capabilities, context,
NoNewPrivs/Seccomp, the real parent, the owner/resolution of the private
directory, four pipes and that every other FD is closed. Two exact nonce
challenges followed by EOF arrive on FD0/FD3; independent receipts go out on
FD1/FD2. The program has no children. An alarm caps its lifetime at 20 seconds.
It launches no earlier probe and changes no policy, identity or protection.

This phase qualifies **neither the broker, nor Python, nor PRoot sharing**.
Success on Android remains to be demonstrated with the real APK, not with a PC
fixture.

## Explicit actions

Component:
`app.foldgpt.runasqualification.v1/app.foldgpt.runasqualification.RunAsQualificationActivity`

Exact actions, restricted to the shell launcher by the Android DUMP permission:

- `app.foldgpt.runasqualification.v1.COLLECT_INFO`: local installed identity, no UserService.
- `app.foldgpt.runasqualification.v1.AUTHORIZE`: official Shizuku request, no native launch.
- `app.foldgpt.runasqualification.v1.PREFLIGHT`: Activity/service identity comparison, no native launch.
- `app.foldgpt.runasqualification.v1.RUN_IDENTITY_FDS_V1`: single attempt; reserves `files/runas-identity-v1/attempt-started-v1` before bind.

Never delete the marker, clean the data or replay the consumed attempt.
A rejection keeps the real outputs and the waitpid status; no success is
inferred from a timeout. An owner that was not reaped stays in quarantine.

The final report is collected with `run-as app.foldgpt.runasqualification.v1 cat
files/runas-identity-v1/run_identity_fds_v1.json`. The other actions write
sibling `collect_info.json`, `authorize.json` and `preflight.json` files.
The independent verifier is `python -B runasqualification/verify-identity.py <report>`.
Also cross-check from the PC the boot ID, the PID being gone after wait and the
target APK being unchanged.

## Windows build

Java 21, Android SDK 37/NDK 29.0.14206865, Gradle 9.7.1, preserved key provided
by `tools/recovery/android-signing.gradle`.

```powershell
# From tools/executor/shizuku-service
gradle :runasqualification:assembleDebug -PfoldgptFrozenTransportJni=C:/Dev/FoldGPT/tools/executor/shizuku-lab/build/frozen-transport-jni --no-daemon --console=plain
```

The APK is under `build/runasqualification-v1/modules/runasqualification/outputs/apk/debug/`.
Builds/artifacts stay inside the project. The phone attempt is separate from the
build and must wait for review of this APK and its fingerprints.
