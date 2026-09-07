# Independent read-only Android GNU collection

`collect-android.py` reads a completed fixed `gnu-log-*` service report and its
exact `foldgpt-gnu-project-*` case. It starts no Android service, model, PRoot,
shell build or fixture. Android `stat`, `find`, digest and process queries run
outside PRoot through binary `subprocess` / `adb exec-out`.

```powershell
python -B tools/executor/gnu-runtime/collect-android.py `
  --serial DEVICE_SERIAL `
  --log gnu-log-EXACT_DIGITS `
  --fixture foldgpt-gnu-project-EXACT6 `
  --build downloads/gnu-runtime/ANDROID_BUILD `
  --native-build downloads/install/native/STRICT_PROOT_BUILD `
  --llvm-strip C:/PATH/TO/NDK/toolchains/llvm/prebuilt/windows-x86_64/bin/llvm-strip.exe `
  --verify-official --official-deb downloads/chatgpt_arm64.deb
```

Each invocation creates a new `downloads/gnu-runtime/collected-UUID` directory.
Failure retains `failure.json` and collected evidence; it cannot produce PASS.
The optional `--output` must name a nonexistent local directory. No remote file
is written or deleted, including reports and compiled artifacts.

The independent checks cover:

- Exact native service exit, ordinary application UID and native restriction
  observations, tied to the requested physical evidence directory.
- Ten project artifact bytes/hashes, three real test results, edited Python
  source, CPython bytecode presence and ZIP members matching the source tree.
  Neither Python code nor the ZIP application is executed by the collector.
- Outside/protected file contents and 0600 modes, refused targets absent, and
  the deliberate outside symlink intact.
- Eight named denial outcomes. These remain historical observations from the
  APK-owned probe, whose complete frozen source is retained; the collector does
  not manufacture new syscall evidence from a report string.
- Native parent `ECHILD` cleanup plus a current independent process snapshot
  refusing any identifiable probe launcher, strict PRoot or cwd inside the case.
  A post-run snapshot cannot reconstruct every historical descendant identity.
- The actual Package Manager base APK, every required extracted native library
  compared byte-for-byte with its packaged copy, and each library bound to the
  supplied build manifest. Where AGP stripped the library, the specified NDK's
  real `llvm-strip --strip-unneeded` must reproduce the installed bytes exactly.
  Stripping operates on a new local output only, preserving its source artifact.
- Current Knox/verified-boot/lock/SELinux indicators before and after collection;
  these observations do not establish a contractual warranty guarantee.

`--verify-official` hashes the installed client package with Android's native
`md5sum`, without executing the client or using PRoot. With `--official-deb`,
the collector first streams the historical Debian payload locally and derives
its complete regular-file inventory. That must equal the installed dpkg
inventory. SHA-256 values of ChatGPT, app.asar and Codex must separately match
the historical payload. The local historical package's digest/version are
reported; this collector does not establish publisher authenticity by itself.
It reads no user configuration, authentication file, conversation or keyring.

Collected file identities and SHA-256 values, APK identity and security
properties are checked again at completion. The snapshot of the current Java
service source is descriptive; the actual APK digest identifies the compiled
service. This is not a reproducible source-to-DEX proof.

The result proves this fixed GNU project and its retained artifacts. It does
not prove Desktop tool routing, full managed policy, interactive terminals,
network-enabled dependencies or arbitrary hostile-workload isolation.

## Collected Android result — 6 September 2026

`downloads/gnu-runtime/collected-5bbaba704f5e4903b94749293c4341f1`
passed against `gnu-log-47936116558622675` and
`foldgpt-gnu-project-tivnT0`: ten project artifacts, three tests, eight denials,
the real ZIP output, protected bytes/modes and native cleanup observations.
The independent current process snapshot found no identifiable GNU worker.

Installed APK SHA-256:
`1b108243eb6a212ec16b38f6d04b9fb67e2486ed47eb1296c29fd4ce193175f0`.
The launcher input from
`android-218375652e2e4e37a3b531db2dbe78db` is
`f6ae13b3bce27ee88daced5b7013b6207f205d69ef7dc5488c4c90357a7446e4`;
NDK r29 `llvm-strip --strip-unneeded` reproduces the actual APK/extracted
launcher exactly:
`3e01d50cb78e6b3f7cb87bf9b7026bdc28d4411864068c7ec8c1aba3c0833d28`.
The four PRoot/loader/talloc libraries match their frozen native manifest.

All **6,200 regular official-client files** match the installed dpkg inventory,
which independently matches the data archive derived from historical package
`chatgpt_arm64.deb`, version **26.901.41600**, SHA-256
`8d5141b299ca593255fa25760895e84375937cc305197528c822dfa71ac2a3bf`.
The actual ChatGPT, app.asar and Codex SHA-256 values also match that package.
This is not the separately prepared newer client release.

Verified boot remained green, flash locked, warranty bit 0 and SELinux Enforcing
at both ends. The verification report SHA-256 is
`c3127e69a7b35e82a2c7bc288f85f9b35e085d663749cccd24391f76abe3b69a`.

The retained earlier collector failures are not relabeled as passes: one lacked
the required AGP stripping reproduction, one assumed a control-archive md5sums
file that this actual Debian package does not contain, and one attempted input
streaming to an output-only ADB invocation. The final collector derives the
inventory from the actual data archive and checks the existing on-device
inventory natively, without uploading it or changing any remote file.
