# Additive kernel diagnostic in laboratory version 7

This is a normal signed update of our existing `app.foldgpt.shizukuprobe`.
It adds the already reviewed fixed kernel diagnostic and reuses the application's
existing official Shizuku authorization through the SDK. It never writes Shizuku
configuration, grants permissions, changes a system setting or handles the PIN.

Final APK: `build/kernel-v7-setup/app-debug.apk`.
SHA256: `0f7a673f8b5ec14f09368ebd31d974bbc5d0540617ff91e7d433fe65a072c82d`.
Certificate SHA256:
`30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16`.
Full build evidence: `build/kernel-v7-setup/provenance.json`.
The v6 APK and its evidence remain at `build/kernel-v6-canonical/`.

The five original Java/AIDL files match the frozen v5 provenance byte for byte.
The guard digest remains
`7fa4f638c431866e69dcda8618a3e8872b19861941d5d7bd1dbc8ec92352893b`.
The old Activity, guard operation and `files/report.json` remain separate. As
before, the old UserService tag incorporates the APK version, now 7; no old
operation is automatically run by this update.

The new Activity comes from the same Java sourceSet as the independent kernel
APK. Its actions and report subdirectory are fixed source constants. Its files
are exclusively `files/kernel-v3/package-info.json`, `report.json` and
`attempt-started`. It does not read report locations or execution parameters
from Intent extras. The merged manifest retains only the original
`ProbeProvider` and the existing `API_V23` permission.

The 84 native ELF entries are byte-identical to v6 and the reviewed standalone
`1d412587...` APK, including JNI transport and cwd shim. The only asset changes
from v6 are the bootstrap and its source-manifest hash. The deployment remains
byte-identical. The complete 82-entry native inventory and 22-entry source
manifest have been reverified in the final APK. The binary manifest still has
one provider, the two DUMP-protected Activities and the original API_V23 permission.

## Setup-error diagnostic

The real v6 attempt forked its bootstrap under Shizuku UID2000, then exited70
before `ready`; actual JNI wait and independent snapshots confirmed cleanup.
No native qualification worker ran. The original reports remain in
`downloads/native-kernel-trial/lab-v6-bootstrap-refusal/` and `files/kernel-v2`.

Version7 adds a private `setup_failed` frame before the existing final lifecycle
frame. It reports a fixed stage enum, bounded exception class, errno1–4095 or
null, source basename and line, and at most160 printable ASCII message
characters without JSON escapes. It never includes a traceback, local variables,
environment or RPC payload. The Java parser admits only the canonical complete
shape before `ready`, rejects duplicate/late failures and rejects success0 after
a setup failure. The existing maximum remains two frames, each at most512 bytes.

This diagnostic does not establish cleanup. Releasing ownership still requires
the final `closed cleanupComplete:true exitCode:70` frame and actual wait status
17920. Missing/import-failed factories retain marker/quarantine as before.
Twenty transport JVM tests pass, together with the real host bootstrap lifecycle
tests and four actual setup failures (bad deployment, broker mode, absent broker,
missing factory). Final JVM XMLs and the exact diagnostic sources are retained
beside the v7 APK.

The suspected broker bind/chmod restriction is still a hypothesis. Version7 does
not change the listener or any native protection; its source/line diagnosis is
intended to identify the actual failure before designing a correction.

## Official permission behavior

The locally retained official source shows `ShizukuService.attachApplication`
checking that the requested package belongs to the actual Binder UID, then
returning the registered client's allowed state. `ClientManager.addClient`
looks up the existing permission state by UID. `Shizuku.checkSelfPermission`
uses that actual server state. There is no APK-version-specific approval in
this path. A normal same-package, same-certificate update preserves the Android
application identity; the new Activity still checks permission on attachment
and cannot assume it from packaging alone. If unavailable, only the ordinary
SDK permission request is possible and execution remains pending.

Source references retained locally:

- `downloads/research/shizuku-source-20260907/server/src/main/java/rikka/shizuku/server/ShizukuService.java`, lines 187–238.
- `downloads/research/shizuku-api-source-20260907/server-shared/src/main/java/rikka/shizuku/server/ClientManager.java`, `addClient`.
- `downloads/research/shizuku-api-source-20260907/api/src/main/java/rikka/shizuku/Shizuku.java`, lines 865–872.

## Main-task deployment sequence

Install the final APK as an ordinary update with `adb install -r`, preserving
application data and existing authorization. The standalone kernel package is
independent and does not need to be removed or restarted.

First collect PackageManager information only:

```text
am start -W -n app.foldgpt.shizukuprobe/app.foldgpt.kernelqualification.QualificationActivity -a app.foldgpt.shizukuprobe.KERNEL_COLLECT_INFO
run-as app.foldgpt.shizukuprobe cat files/kernel-v3/package-info.json
```

Use the actual new `nativeLibraryDir` to stage the Python runtime from
`build/kernel-stage-v7/staged-python-data`. Its exact manifest/deployment are
`build/kernel-stage-v7/assets/foldgpt-python-runtime.json` and
`foldgpt-executor-deployment.json`. All 81 runtime aliases must point to this
package's current installed ELF files, never the standalone package's earlier
path. The fixed shell base remains
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2`. Reuse of that
previously prepared fixture is valid only after independent proof that no
worker was launched and no unresolved broker marker/evidence exists.

After staging verification and independent review, invoke once:

```text
am start -W -n app.foldgpt.shizukuprobe/app.foldgpt.kernelqualification.QualificationActivity -a app.foldgpt.shizukuprobe.KERNEL_RUN_FIXED
run-as app.foldgpt.shizukuprobe cat files/kernel-v3/report.json
```

The Activity retains the one-shot reservation. It cancels normally on deadline
or ownership loss and rejects late admission. The separate private native
evidence remains `BASE/evidence.json`; combine it with the RPC/JNI report and
independent device snapshots. The RPC report alone never establishes native
cleanup or Android qualification success. The complete native contract is in
`../bionic-supervisor/qualification.md`.

## Reproduce the PC build

The staged deployment is produced by `../shizuku-service/stage-qualification.py`
with `--package app.foldgpt.shizukuprobe --output build/kernel-stage-v7`, the frozen
`8Kd8xQRE` build and interpreter CLI compiled for `BASE/python`.
The `build/frozen-transport-jni/arm64-v8a` directory contains the exact two JNI
libraries extracted from the reviewed standalone APK. Gradle verifies their
actual hashes and rejects additional files before packaging them.

From this laboratory project using the configured JDK21/Android SDK:

```text
gradle --no-daemon :app:assembleDebug -PprobeSha256=7fa4f638c431866e69dcda8618a3e8872b19861941d5d7bd1dbc8ec92352893b -PfoldgptFrozenTransportJni=C:/Dev/ChatgptFold/tools/executor/shizuku-lab/build/frozen-transport-jni --console=plain
```

This subtask built, inspected and verified exclusively on PC. Device operation
and its actual outcome belong to the main task.
