# Native interpreted-runtime qualifications V1 and V2

The PC tools accept only `--version 1` (historical default) or `--version 2`.
V2 is `app.foldgpt.runtimequalification.v2`, based at
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v2`, with report directory
`runtime-v2`, run action `.RUNTIME_RUN_FIXED_V2` and distinct service/attempt
identities. V2 retains the V1 APK and its evidence. It pins supervisor source
build `qKM94iHA` and the separately compiled CLI with native `DT_RUNPATH`
`/data/local/tmp/foldgpt-bionic-runtime-qualification-v2/python/lib:$ORIGIN`.
The wrapper factory fixes that V2 base in APK-owned code; RPC requests cannot
choose a new base or revise runtime grants. The workload remains identical.

Select `-PfoldgptRuntimeQualificationVersion=2` in addition to
`-PfoldgptRuntimeQualification=true` for V2 Gradle tasks. Its pin, staging,
outputs and verifier are separate from V1:
`runtimequalification-inputs-v2.json`, `build/runtimequalification-v2`, and
`runtime-stage-v2`. Run both stage/verifier and collector with `--version 2`.
The Python device stager takes the exact V2 package/base and
`--report-version 2`. Omitting version continues to select historical V1.

Seven JVM contract tests, eight PC packaging tests, six staging tests and
nineteen synthetic collector tests cover both profiles, cross-version refusal
and evidence ownership. They are not Android execution evidence.

## Historical V1 diagnostic

This is a separate diagnostic application, `app.foldgpt.runtimequalification.v1`,
with the native home `/data/local/tmp/foldgpt-bionic-runtime-qualification-v1`.
It does not reuse the V11/V12 kernel probe package, worker, report parser, service
tag, or attempt marker. FoldGPT and the official ChatGPT application keep their
existing packages and files.

The fixed workload uses the production Shizuku transport and dynamic native
backend. It starts packaged Bash, changes directory, executes the separately
compiled Bionic Python 3.14.7 CLI, and receives `native input\n` through the actual
`process/write` RPC. Python creates and edits a calculator project, runs three
unit tests, builds and executes a compressed zipapp, checks separate binary
child streams and an empty child environment, and exercises eight real denied
operations. The client reads the resulting JSON through `fs/readFile` and
compares those bytes to actual stdout. This fixed diagnostic does not prove
ordinary model-driven commands from the FoldGPT UI.

## PC preparation

`../runtimequalification-inputs-v1.json` pins the supervisor, helper inventories,
Bash, separate Python CLI and transport JNI. `../stage-runtime-qualification.py`
checks these actual files before producing a fresh stage. The frozen Python
sources are copied from that build's authenticated source inventory.

Gradle requires `-PfoldgptRuntimeQualification=true` and places all outputs under
`../build/runtimequalification-v1`. Use the reviewed frozen transport JNI path
with `-PfoldgptFrozenTransportJni=...`. The required tasks are
`:runtimequalification:assembleDebug`, `:runtimequalification:testDebugUnitTest`
and `:transport:testDebugUnitTest`.

`../verify-runtime-qualification.py --output <new-directory>` verifies the
finished APK's complete assets/native inventory, runtime DEX identity, manifest,
signature, actual Gradle test XML files and preserved diagnostic sources. Its
provenance explicitly reports `androidExecution: false`: packaging and JVM
tests are not phone execution evidence.

## Device ownership and evidence

Only the coordinator performs phone operations. The device must retain stock
SELinux enforcement, a locked bootloader and the existing verified boot/Knox
indicators. Shizuku must run as Android shell UID 2000; root is refused before
requesting authorization. No security policy change, root, flashing, VM or
bootloader operation is part of this qualification.

The component `app.foldgpt.runtimequalification.RuntimeQualificationActivity`
requires Android's `DUMP` permission. Its actions are the package name followed
by `.RUNTIME_COLLECT_INFO`, `.RUNTIME_AUTHORIZE`, `.RUNTIME_PREFLIGHT` or
`.RUNTIME_RUN_FIXED_V1`. The actual run requires prior official Shizuku
authorization. It reserves one app-private attempt and does not retry.

The fixture contains empty `directory` and `.git` directories plus
`private/secret` with `probe-private-unchanged\n`. The parent staging helpers
support this exact package/base and Python report version 1. They retain the
main FoldGPT package, the Shizuku lab package, and kernel qualification V11/V12.

Actual application evidence is `files/runtime-v1/report.json` under `run-as`.
Private native evidence is `<native-home>/evidence.json`. The runtime collector
`../../../runtime/collect-runtime-qualification.py` takes `--adb`, `--serial`,
`--apk`, `--before` and a fresh `--output` directory. It only reads evidence and
snapshots; it launches no workload and retries none.

The collector requires matching runtime identities, distinct real bootstrap
and supervisor PIDs, actual supervisor and JNI wait/cleanup proof, exact sent
requests and observed responses/events, actual stdin and stream bytes,
independently verified project sources/archive, unchanged sentinel and `.git`,
unchanged retained APK hashes, and unchanged boot/stock indicators. It traverses
the material workspace only after clean ownership is proven. Kernel success,
PC results, synthetic test fixtures and missing cleanup cannot become a runtime
success report.
