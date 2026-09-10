# Laboratory v9 admission and explicit-launch diagnostic

**Historical v9 procedure.** The installed v10 trial now retains quarantine
after a real `/linkerconfig` refusal. Read the
[v10 report](../../../docs/research/native-v10-retained-session-2026-09-07.md)
before any device action; do not replay this earlier procedure.

This separate signed update makes real UserService admission failures observable.
It does not change the fixed native worker, supervisor, broker, bootstrap or any
native lifetime rule. All previous artifacts, reports and attempt reservations
remain preserved, including `files/kernel-v2`, `kernel-v3` and `kernel-v4`.

Final APK: `build/kernel-v9-launch/app-debug.apk`.
SHA256: `7fa98c225e88dc912620cc37fe178713c753a5168ee393b2f5feaa1edfb19819`.
Certificate SHA256:
`30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16`.
All 84 native ELF files and all 27 assets are byte-identical to v8. The 82-entry
native inventory and 22-entry source manifest were verified in the final APK.
The original five probe sources, guard hash, sole ProbeProvider and existing
API_V23 permission remain unchanged. The 24 passing transport JVM results are
reused from v8; they do not test the new Android Activity launch behavior.
The preflight-to-open path rechecks cancellation after the potentially long
file scan, as well as after open and before the fixed process/start request.

## Corrected v7/v8 chronology and actual v9 result

The retained v7/v8 admission reports were created automatically during package
updates when Android restored the previous Activity Intent, before the Python
aliases were restaged. They do not demonstrate new explicit executions after
restaging. The recorded times are in
`downloads/native-kernel-trial/lab-v8-inspection/report-times.txt`.
The first v8 preflight identifies an alias targeting the previous APK;
`preflight-restaged.json` in that directory then passes with the actual v8
UserService and no native spawn. The generic v7 error does not establish its
precise nested cause, nor does absence of its old service prove cleanup.

V9 rejects the inherited unversioned `KERNEL_RUN_FIXED` before reservation.
`lab-v9-inspection/inherited-intent-refusal.json` records that exact requested
action and diagnostic version 9; `inherited-intent-directory.txt` independently
shows that no `attempt-started` existed at that point. These paths are under
`downloads/native-kernel-trial`.

The later explicit `KERNEL_RUN_FIXED_V9` action is a distinct, recorded trial.
Its real preflight passed in installed version 9, service UID2000/PID9798,
before the bootstrap failed at `broker_open`: `PermissionError`, errno13,
`private_exec_broker.py:93`, the AF_UNIX `bind()` call. The transport reports
`bootstrapReaped=true`, `cleanupComplete=true`, `waitStatus=17920` (exit70),
`ownerRetained=false` and `quarantined=false`. It never became ready and no
worker or native `evidence.json` was produced. This confirms the failing bind
operation; the underlying Android policy responsible remains to be determined.

Evidence: `lab-v9-bootstrap-refusal/app-report.json` and
`independent-verification.json`, plus `lab-v9-cleanup-inspection/snapshot.json`
and `broker-and-marker-listing.txt`, under `downloads/native-kernel-trial`.
The independent snapshot confirms PID9798 absent, unchanged fixture, boot,
integrity indicators and installed package hashes; the broker contains only
the empty lock file. The v9 attempt marker is retained. The collector correctly
returns `success:false` because native evidence is absent. `/proc/TID/mem` and
`pidfd_getfd` remain unmeasured in this Android worker context.

## Bounded observations

The authenticated service retains the actual Java admission stage and nested
exception cause. The diagnostic records a fixed stage enum, one subject of at
most 192 ASCII characters, at most five predefined facts (integers or bounded
1024-character ASCII paths), exception class, errno 1–4095 or null, source basename,
line and at most 160 ASCII message characters. It never includes a stack trace,
local-variable dump, environment, credentials or arbitrary RPC input.

Stages distinguish deployment assets/schema, native directory/interpreter/
inventory, cwd shim, Python SELinux domain/manifest/root/data/aliases/tree,
transport load, owner registration, pipes, control flags, native fork and
observer startup. Python alias diagnostics show the actual expected path,
readlink target and Java canonical path. Tree mismatch reports one real missing
or unexpected path and the two file counts.

`service.status()` retains the existing lifetime fields at the same root level
and adds `admission` and `preflight`. No diagnostic promotes cleanup. The fixed
Activity now captures this service status if opening a session throws, even if
there is no session Binder. Its existing session cleanup checks are preserved.

## Fixed read-only actions

Both inspection actions write only application-private diagnostic reports in
`files/kernel-v5`. They do not reserve `attempt-started`. They require the
application's existing ordinary Shizuku authorization and do not request a new
grant. Intent extras cannot select a path, command, service version or operation.

```text
am start -W -n app.foldgpt.shizukuprobe/app.foldgpt.kernelqualification.QualificationActivity -a app.foldgpt.shizukuprobe.KERNEL_STATUS_V3
run-as app.foldgpt.shizukuprobe cat files/kernel-v5/previous-service-status.json
```

This uses SDK `peekUserService` with its official `NO_CREATE` flag for the fixed
previous tag/version3. If present, it calls only the existing `status` method.
It cannot open, preflight, cancel, restart or destroy that previous session.
It detaches only its observer with SDK `remove=false`. If absent, the report
explicitly leaves ownership unestablished. A package update can kill the old
application client; Shizuku can then remove a non-daemon UserService when its
last callback dies. Therefore a later absent old tag cannot establish that its
previous native lifetime was clean.

```text
am start -W -n app.foldgpt.shizukuprobe/app.foldgpt.kernelqualification.QualificationActivity -a app.foldgpt.shizukuprobe.KERNEL_PREFLIGHT
run-as app.foldgpt.shizukuprobe cat files/kernel-v5/preflight.json
```

This binds the current fixed tag `foldgpt-kernel-qualification-v5`, version5,
then runs the same installed-input
`Deployment` checks as `open` inside the real UserService. It never loads the JNI
transport, creates a session owner or pipes, forks a bootstrap, opens a broker,
creates a workspace marker or launches a worker. It also reports actual service
UID/PID and installed version, plus context and PackageManager native/APK paths
to investigate update-cache hypotheses without silently refreshing admission
inputs. The preflight report is not Android execution qualification.
Its `operation: preflight_v4` label is historical. Read `installedVersion` and
`diagnosticVersion` for the actual APK revision, rather than interpreting that
operation label as version 4.

Only after independent inspection of these reports and fixture ownership can
the versioned one-shot `KERNEL_RUN_FIXED_V9` action be considered. That action also
requires a successful real preflight before calling `open`. It still writes
`files/kernel-v5/attempt-started` once, preserves all previous attempts, and
requires separate native evidence plus the existing private cleanup/wait proof.
The fixed native base remains
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2`.
The recorded v9 trial has already consumed this reservation; these descriptions
are not instructions to retry it or remove its marker.

`onNewIntent` now handles an explicit action delivered to the existing Activity
instead of silently leaving the old report visible. It checks `finished` and
unresolved native ownership before recreation. This source/packaging review is
limited: the reporting deadline may set `finished` while the background Java
worker is still running. Do not reuse the Activity or send a replacement action
after a timeout; establish actual worker/session completion and cleanup first.
Neither `finished`, an old report, nor an elapsed deadline proves that completion.

## Source evidence for the SDK behavior

- `downloads/research/shizuku-api-source-20260907/api/src/main/java/rikka/shizuku/Shizuku.java`: `peekUserService` and `unbindUserService`.
- `downloads/research/shizuku-api-source-20260907/server-shared/src/main/java/rikka/shizuku/server/UserServiceManager.java`: `noCreate` returns the existing service before record creation/version handling; `remove=false` unregisters only a callback.
- `downloads/research/shizuku-api-source-20260907/server-shared/src/main/java/rikka/shizuku/server/UserServiceRecord.java`: non-daemon last-callback death handling.

The unchanged stage for this APK is `build/kernel-stage-v8`. It uses the same frozen
native inputs and JNI property as the v7 procedure in `KERNEL-QUALIFICATION.md`.
Its artifact, tests, source snapshots, manifest/signature verification and
provenance are frozen independently in `build/kernel-v9-launch/`. The previous
APK and its evidence remain in `build/kernel-v8-admission/`.
