# Laboratory v8 admission diagnostic

This separate signed update makes real UserService admission failures observable.
It does not change the fixed native worker, supervisor, broker, bootstrap or any
native lifetime rule. All v7 artifacts and reports remain preserved.

Final APK: `build/kernel-v8-admission/app-debug.apk`.
SHA256: `76f58714ac9900c7162b291822cd8b620916766c87945bdcf9e607beee26fee4`.
Certificate SHA256:
`30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16`.
All84 native ELF files and every asset are byte-identical to v7. The82-entry
native inventory and22-entry source manifest were verified in the final APK.
The original five probe sources, guard hash, sole ProbeProvider and existing
API_V23 permission remain unchanged. Twenty-four transport JVM tests pass.
The preflight-to-open path rechecks cancellation after the potentially long
file scan, as well as after open and before the fixed process/start request.

The v7 device attempt returned `Executor admission failed` before any session
Binder reached the Activity. Its cause was lost across Binder because only the
outer exception message was reported. `transportCleanupComplete:false` therefore
remains unresolved in that report, even though independent inspection found no
native worker. The precise admission cause has not yet been established.

## Bounded observations

The authenticated service retains the actual Java admission stage and nested
exception cause. The diagnostic records a fixed stage enum, one subject of at
most192 ASCII characters, at most five predefined facts (integers or bounded
1024-character ASCII paths), exception class, errno1–4095 or null, source basename,
line and at most160 ASCII message characters. It never includes a stack trace,
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

Both new actions write only application-private diagnostic reports in
`files/kernel-v4`. They do not reserve `attempt-started`. They require the
application's existing ordinary Shizuku authorization and do not request a new
grant. Intent extras cannot select a path, command, service version or operation.

```text
am start -W -n app.foldgpt.shizukuprobe/app.foldgpt.kernelqualification.QualificationActivity -a app.foldgpt.shizukuprobe.KERNEL_STATUS_V3
run-as app.foldgpt.shizukuprobe cat files/kernel-v4/previous-service-status.json
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
run-as app.foldgpt.shizukuprobe cat files/kernel-v4/preflight.json
```

This binds the new fixed tag/version4, then runs the same installed-input
`Deployment` checks as `open` inside the real UserService. It never loads the JNI
transport, creates a session owner or pipes, forks a bootstrap, opens a broker,
creates a workspace marker or launches a worker. It also reports actual service
UID/PID and installed version, plus context and PackageManager native/APK paths
to investigate update-cache hypotheses without silently refreshing admission
inputs. The preflight report is not Android execution qualification.

Only after independent inspection of these reports and fixture ownership can
the existing one-shot `KERNEL_RUN_FIXED` action be considered. That action also
requires a successful real preflight before calling `open`. It still writes
`files/kernel-v4/attempt-started` once, preserves all previous attempts, and
requires separate native evidence plus the existing private cleanup/wait proof.
The fixed native base remains
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2`.

## Source evidence for the SDK behavior

- `downloads/research/shizuku-api-source-20260907/api/src/main/java/rikka/shizuku/Shizuku.java`: `peekUserService` and `unbindUserService`.
- `downloads/research/shizuku-api-source-20260907/server-shared/src/main/java/rikka/shizuku/server/UserServiceManager.java`: `noCreate` returns the existing service before record creation/version handling; `remove=false` unregisters only a callback.
- `downloads/research/shizuku-api-source-20260907/server-shared/src/main/java/rikka/shizuku/server/UserServiceRecord.java`: non-daemon last-callback death handling.

The stage for this APK is `build/kernel-stage-v8`. It uses the same frozen
native inputs and JNI property as the v7 procedure in `KERNEL-QUALIFICATION.md`.
Its artifact, tests, source snapshots, manifest/signature verification and
provenance are frozen independently in `build/kernel-v8-admission/`.
