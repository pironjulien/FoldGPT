# Build an Android qualification candidate

This recipe packages a debug **update candidate** from explicit reviewed inputs.
It does not install anything on a phone or reconstruct a complete fresh Linux
runtime. Fresh installation remains gated by the
[daily-use qualification plan](daily-use-qualification.md).

Use Python 3.11 or later, JDK 21, Gradle 9.7.1, Android SDK API 37, build-tools
36.0.0, NDK 29.0.14206865 and CMake 3.22.1. Gradle source compatibility is Java 17.
All staging and output belong under this checkout's `work/` or `downloads/`.
The script works with explicit Windows or POSIX paths; no developer account,
private vault or dated build directory is discovered implicitly.

## 1. Select reviewed inputs

Prepare these independently before recording an inventory:

| Input | Contents |
| --- | --- |
| Executor package | `assets/` and `jniLibs/`, with deployment, source and qualification manifests and license notices. Current source bytes must match the staged Python runtime. |
| Runtime JNI | Exactly the five PRoot/loader/support libraries in `arm64-v8a/`. |
| X11 JNI | `arm64-v8a/libXlorie.so`; an included `build-manifest.json` must match that library. Use the matching reviewed native build, not an old staging receipt. |
| Transport JNI | The two transport libraries in `arm64-v8a/`, matching the executor deployment. |
| Debug JNI/assets | Explicit diagnostic libraries and Python debug assets required by the existing debug APK contract. |
| Toolchains | Explicit JDK, Gradle executable and SDK installation; select exact installed platform/build-tools directories. |

These inventories establish which local bytes were used; they do not authenticate
an arbitrary download. Retain upstream signatures, source/build receipts and
reviewed hashes alongside them. An executor Python change requires restaging;
passing an old manifest does not permit stale source bytes.

```sh
python tools/runtime/build-production-candidate.py record-inputs \
  --package "$EXECUTOR_PACKAGE" \
  --runtime-jni "$RUNTIME_JNI" --x11-jni "$X11_JNI" \
  --transport-jni "$TRANSPORT_JNI" \
  --debug-jni "$DEBUG_JNI" --debug-assets "$DEBUG_ASSETS" \
  --jdk "$JAVA_HOME" --gradle "$GRADLE_EXECUTABLE" --sdk "$ANDROID_HOME" \
  --sdk-platform android-37.0 --build-tools 36.0.0 \
  --output work/candidate-inputs.json
```

Use `android-37` if that is the installed stable API 37 directory. The descriptor
records paths and SHA-256/size for every selected input. Keep it local when its
paths identify your workstation. Retain the printed descriptor SHA-256 separately
as `INPUTS_SHA256`. Reuse the same descriptor for subsequent candidates only while
its inputs remain byte-identical. Existing files and attempts are never replaced.

## 2. Admit, build and verify

The preflight is read-only and does not run Gradle:

```sh
python tools/runtime/build-production-candidate.py build \
  --inputs work/candidate-inputs.json --inputs-sha256 "$INPUTS_SHA256" \
  --candidate r47 --output work/candidates/r47 --preflight-only
```

Then supply the original installation's signing identity explicitly:

```sh
python tools/runtime/build-production-candidate.py build \
  --inputs work/candidate-inputs.json --inputs-sha256 "$INPUTS_SHA256" \
  --candidate r47 --output work/candidates/r47 \
  --signing-keystore "$SIGNING_KEYSTORE" \
  --signing-cert-sha256 "$SIGNING_CERT_SHA256"
```

Keystore/entry passwords and alias can be provided only through
`FOLDGPT_SIGNING_STORE_PASSWORD`, `FOLDGPT_SIGNING_KEY_PASSWORD` and
`FOLDGPT_SIGNING_KEY_ALIAS`. Do not put secrets in the descriptor, shell history,
build log or repository. The usual Android debug defaults remain available for
an explicitly chosen debug key. A different key cannot update an existing install;
uninstalling to bypass that check would erase application data.

The builder runs lifecycle tests on the normal JDK and transport JVM tests,
assembles the APK, rechecks source
and selected input inventories, verifies embedded files and native executor
closure, checks APK contents and verifies the actual APK signing certificate.
Only then is `FoldGPT-r47.apk` exposed as a candidate. Failure retains its log and
an unsuccessful report; `unverified.apk` must not be distributed as a candidate.

`inputs.json`, `sources.json`, logs and `build-report.json` accompany the APK.
`deviceQualified` remains false: a successful build does not qualify sleep,
long sessions, focus or installation. Dependency repositories and SDK tooling
still participate in compilation; this recipe does not claim bit-for-bit rebuilds
or a qualified clean-clone native build chain.

The broader Android unit-test task contains a host-only HTTPS fixture that needs
`jdk.httpserver`, a generated local test CA and POSIX storage semantics. Its
dedicated Linux runner remains `tools/install/https-acquisition/run-jvm-tests.sh`.
It is not silently excluded to make the Android unit-test task appear green.
The candidate's lifecycle runner fetches three exact checksum-pinned Maven test
jars into the project cache when needed and records their hashes.

## 3. Qualify before calling it a beta

Follow [daily-use qualification](daily-use-qualification.md). Preserve the old
candidate and project data. Test update installation without removing the app,
then complete the device matrix. A fresh-install candidate additionally needs the
versioned integration bundle, separate GNU engine/companion, guest dependencies
and inactive-root coordinator; those are separate from APK assembly.
