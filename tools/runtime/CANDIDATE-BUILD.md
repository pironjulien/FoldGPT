# Explicit candidate assembly

`build-production-candidate.py` packages an existing reviewed native executor,
PRoot runtime, X11 library, frozen transport and debug fixtures. It does not
rebuild those dependencies, install a Linux rootfs or contact a device. A public
clone still needs these separate inputs; this is not a clean-install claim.

Python 3.11+ is required. Select an installed JDK 21, Gradle 9.7.1, Android SDK
API 37, NDK 29.0.14206865, CMake 3.22.1 and an exact build-tools version. The
script accepts native Windows and Linux toolchains. Use the actual API directory
name (`android-37` or `android-37.0`). No environment-specific default locates
these inputs. Payload directories must contain regular files, with ABI JNI
subdirectories; toolchain file symlinks are recorded with their effective bytes.

First record all explicit inputs into a **new local file** beneath `work/` or
`downloads/`. Replace the paths with reviewed artifacts for the current build:

```sh
python -B tools/runtime/build-production-candidate.py record-inputs \
  --package /path/to/executor-package \
  --runtime-jni /path/to/proot/runtime \
  --x11-jni /path/to/x11-jni \
  --transport-jni /path/to/frozen-transport-jni \
  --debug-jni /path/to/debug-jni \
  --debug-assets /path/to/python-debug-assets \
  --sdk /path/to/android-sdk --sdk-platform android-37.0 \
  --jdk /path/to/jdk-21 --gradle /path/to/gradle-9.7.1/bin/gradle \
  --build-tools 36.0.0 --output work/candidate-inputs/inputs.json
```

`foldgpt.candidate-inputs.v1` stores each selected tree's path, complete file
inventory, byte sizes and SHA-256 digests. It includes the full selected JDK,
Gradle distribution and SDK platform/build-tools/NDK/CMake package directories.
The printed descriptor SHA-256 is retained separately for the next step.
Capturing local hashes does not establish upstream authenticity: retain the
original source, build and qualification evidence alongside the selected inputs.
Do not reconstruct missing provenance by treating arbitrary binaries as reviewed.

The executor must pass its existing package contract and contain the current
checkout's Python sources. Source changes require restaging. The transport must
match its deployment inventory. X11's optional `build-manifest.json`, when
present, must identify the selected library. SDK/NDK overrides in
`android/local.properties` must agree with the selected toolchain.

Read-only preflight checks the complete descriptor and prints the Gradle command:

```sh
python -B tools/runtime/build-production-candidate.py build \
  --inputs work/candidate-inputs/inputs.json --inputs-sha256 RETAINED_SHA256 \
  --candidate r47 --output work/candidates/r47 --preflight-only
```

For the real candidate, remove `--preflight-only` and supply the existing signing
identity explicitly:

```sh
python -B tools/runtime/build-production-candidate.py build \
  --inputs work/candidate-inputs/inputs.json --inputs-sha256 RETAINED_SHA256 \
  --candidate r47 --output work/candidates/r47 \
  --signing-keystore /private/path/existing.keystore \
  --signing-cert-sha256 EXPECTED_CERTIFICATE_SHA256
```

Signing passwords and alias use `FOLDGPT_SIGNING_STORE_PASSWORD`,
`FOLDGPT_SIGNING_KEY_PASSWORD` and `FOLDGPT_SIGNING_KEY_ALIAS`; defaults match the
standard Android debug identity. Key material is not copied into the input
descriptor or output. The script does not search private storage or create keys.

Builds run against the current checkout, so finish source edits first and avoid
concurrent Gradle builds. Generated Gradle outputs remain in their standard
project directories; the project-local Gradle cache remains in
`work/build-cache/gradle`. A new candidate directory retains input/source
inventories, actual Java/Gradle version logs, command, unit-test/build output,
executor/content/signature checks and `build-report.json`. Inputs and sources
are rechecked after compilation. The named `FoldGPT-<candidate>.apk` is published
only after all verifiers and the expected signing certificate pass. Failed
attempts are preserved, report `success: false`, and require a new output path.

This verifies candidate assembly from a fixed local snapshot. Dependency supply
reconstruction, Maven dependency locking, bit-for-bit APK rebuilds, installation,
login, lifecycle endurance and Knox/bootloader/One UI checks remain separate
qualification work. Debug fixtures are explicit inputs because the existing APK
content verifier requires them; no diagnostic checks are disabled for packaging.

Host regression command:

```sh
python -B -m unittest discover -s tools/runtime -p test_candidate_build.py -v
```
