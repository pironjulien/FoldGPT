# Fixed Android supervisor qualification

The frozen standalone APK documented here retains its original actions and
report paths. Current shared Activity source is also included in laboratory v7,
with fixed KERNEL_* actions and isolated kernel-v3 report storage; see
`../../shizuku-lab/KERNEL-QUALIFICATION.md` for that additive update.

Separate package: `app.foldgpt.kernelqualification`. This APK includes the
existing authenticated Shizuku UserService/JNI/bootstrap transport and the
reviewed `8Kd8xQRE` supervisor, file helpers and fixed C worker. Its facade accepts
one exact `process/start`, then only that process's read/terminate controls.
There is no shell, general command, filesystem RPC or model execution route.

Frozen APK:
`../build/qualified-apk-v2-admission/qualification-debug.apk`.
SHA256: `1d41258772e0a27191e60430d4dce82065ec6a3b34964f0387918b037dc2fdf4`.
Certificate SHA256:
`30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16`.

PC verification: Android debug build and APK v2 signature passed; 82 packaged
native digests and 22 source digests match the deployment/manifest. Seventeen
transport JVM tests pass. Real nonroot Linux package-path tests validate all
three helper roles, executable/runtime marker resolution, modified bytes,
aliases and absent libraries. The actual bootstrap EOF/cancel/quarantine
regression passes. These checks do not establish Android kernel support.

## Preparation contract

All paths are under the dedicated, shell-owned mode0700 base:
`/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2`.
The main task prepares a previously nonexistent `workspace` with the exact
fixtures described in `../../bionic-supervisor/qualification.md`, plus empty
mode0700 `broker`. Keep existing unresolved markers and evidence; do not retry.

The new interpreter was built with this base's `python` as its default home:
`/var/tmp/foldgpt-bionic-python-rsemaYBI/libfoldgpt_python_cli.so`.
Its SHA256 is `8061a79064317aaeccfb9a70ddb2bb5167c5bbf97b3eff06263ff8b970d972e9`.

After installing this separate APK, first invoke only:

```text
am start -W -n app.foldgpt.kernelqualification/.QualificationActivity -a app.foldgpt.kernelqualification.COLLECT_INFO
run-as app.foldgpt.kernelqualification cat files/package-info.json
```

`COLLECT_INFO` queries actual PackageManager nativeLibraryDir/sourceDir and
reserves no execution. It does not bind Shizuku. Use that exact native directory
to resolve the 81 ELF aliases in the packaged `foldgpt-python-runtime.json`.
All alias targets must retain the manifest's exact name and SHA256.

Copy the staged ordinary Python data from `../build/qualification-stage/staged-python-data`
into the new shell-owned mode0700 `python` directory. The complete inventory is
`../build/qualification-stage/assets/foldgpt-python-runtime.json`. Preserve its
relative paths; make its ordinary files shell-owned with no group/other write,
directories shell-owned with no group/other write. Create the declared aliases
only to the actual installed APK ELF paths. No staged ELF is executed directly.

The actual UserService verifies its shell SELinux domain, each installed ELF
SHA256, every staged data byte, exact alias target, ownership/modes and absence
of extra files before native fork. The JNI independently requires UID/GID2000
and zero effective/permitted/inheritable (therefore ambient) capabilities.
The application UID never reads the private staged runtime.

## Single invocation and separate evidence

After independent staging verification and official Shizuku authorization:

```text
am start -W -n app.foldgpt.kernelqualification/.QualificationActivity -a app.foldgpt.kernelqualification.RUN_FIXED
run-as app.foldgpt.kernelqualification cat files/report.json
```

The Activity reserves `files/attempt-started` once and never deletes it or
automatically retries. Its report uses `foldgpt.android-kernel-rpc.v1` and
contains `rpcSuccess`, actual protocol frames and `transportCleanupComplete`.
The latter requires both private bootstrap cleanup and the actual JNI wait.
It does not claim total success by itself. The separate shell-side
`evidence.json` uses `foldgpt.bionic-kernel-qualification.private.v1` and records
real `nativeResult`, `supervisorReturncode`, process identity, output and
quarantine. Both evidence layers and the independent before/after device
snapshot must agree. Neither missing output nor process absence is a pass.

Shizuku's official permission dialog can appear for this new package. Until
permission is granted, there is no service bind or native fork. The reporting
deadline cancels through the normal control pipe and retains ownership if
cleanup is unknown; it never kills the native owner to produce a clean report.
Late service admission after timeout, Binder loss or Activity destruction is
rejected before the fixed process/start; the cancellation pipe remains the
normal native shutdown route.

Prepared and tested exclusively on PC by this subtask; deployment and device
verification belong to the main task.
