# Build and validate FoldGPT

`v0.2.0-alpha.1` is a **source preview for contributors**. You can inspect the
Android host, run host regressions and work on the integration today. A complete
APK additionally needs native libraries, a reviewed executor package and Linux
runtime preparation. Those generated payloads and the proprietary ChatGPT client
are not distributed in this release.

## Start with the source checks

Clone the repository normally. `vendor/` contains source trees, not Git submodules;
there is no recursive submodule initialization step.

```sh
git clone https://github.com/pironjulien/FoldGPT.git
cd FoldGPT
python3 -m venv work/host-venv
work/host-venv/bin/python -m pip install -r tools/ci/requirements-host.txt
work/host-venv/bin/python tools/ci/check-source-integrity.py
work/host-venv/bin/python -m compileall -q runtime tools config tests
work/host-venv/bin/python tools/ci/run-host-tests.py
```

Use Linux with Python 3.12 and an ordinary, nonroot account for these host suites.
They exercise real archive handling, filesystem checks, protocol behavior and
offline input ordering. The runner selects named suites, reports their collection
counts and rejects empty collections. Some rootfs cases require root, a static
compiler or WSL/Windows fixtures and explicitly skip when unavailable. Separate native and Android tests
need their own compiled fixtures or a device; the host job does not run them.

## Android toolchain

The checked-in build configuration currently selects:

| Input | Version or requirement |
| --- | --- |
| Java | JDK 21 for the existing build workflow; Java source compatibility 17 |
| Gradle | 9.7.1 used by the development workflow; no root Gradle wrapper included |
| Android Gradle Plugin | 9.3.1 |
| Android SDK | Compile/target API 37; minimum API 30 |
| Android NDK | 29.0.14206865 (r29) |
| CMake | 3.22.1 for the Android Gradle build |
| Target ABI | `arm64-v8a` |
| Native build host | Linux x86_64; WSL Ubuntu 24.04 used during development |

Set `JAVA_HOME` and configure the Android SDK using `ANDROID_HOME` or the ignored
`android/local.properties`. Install Gradle on your build host. Keep Linux NDK and
native compilation directories on a filesystem with case-sensitive POSIX
semantics; ordinary Windows paths cannot represent all NDK header names correctly.

## Prepare the native inputs

1. **PRoot, loaders and support libraries.** Read the
   [native runtime recipe](../tools/install/native/README.md). It verifies the NDK
   archive, fetches the exact PRoot upstream commit into a new build directory,
   applies the published patches and produces five reviewed library candidates.
   It does not populate `android/native/runtime` or install anything on a phone.
2. **Embedded X11.** [build-x11.sh](../tools/gpu/build-x11.sh) snapshots the actual
   vendored sources and records hashes. The vendor tree already includes FoldGPT
   changes. Its patch checks run on the snapshot and avoid applying changes twice.
   The default Gradle configuration expects a prepared library under
   `android/native/x11/arm64-v8a`; `-PbuildX11FromSource` selects the upstream CMake
   build instead.
3. **Native executor.** Prepare and qualify a package containing `assets/` and
   `jniLibs/`, following the source recipes under `tools/executor/`. The
   [package contract](../config/android/executor-package.json) requires source,
   deployment, qualification and evidence manifests. The APK verifier validates
   the selected payload against those inventories. A directory of arbitrary
   libraries is insufficient.
4. **Guest runtime and client.** The rootfs, guest bundle and inactive integration
   tools under `tools/install/` prepare separate artifacts. The official client
   must be obtained from its authorized upstream source and integrated with the
   matching version of the adapter. No user profile or authenticated image belongs
   in a public build artifact.

For the native recipes, explicitly set `ANDROID_NDK_HOME` and
`FOLDGPT_NDK_ARCHIVE` to your Linux NDK installation and verified archive. Some
historical diagnostic scripts still carry local staging assumptions. The complete
package preparation sequence has **not been qualified from a clean public clone**;
it remains release engineering work on the [roadmap](roadmap.md). Two concrete
assembly gaps remain: the Python guest bundle now includes the native Codex
launcher, while the Android inactive-integration v2 reader still uses its older
exact file list; and the experimental audio bridge requires guest PulseAudio
setup that the source bundle does not yet assemble. They need versioned format
integration and package/device verification before a fresh-install APK release.

## Compile or package

After the native runtime inputs have been prepared, Android source checks use the
normal Gradle tasks from `android/`, for example:

```sh
gradle --no-daemon :app:compileDebugJavaWithJavac :app:testDebugUnitTest
```

The `preBuild` check requires exactly the expected five runtime libraries even for
these Android tasks. Building an APK additionally requires both explicit executor
inputs:

```sh
gradle --no-daemon \
  -PfoldgptExecutorAssets=/absolute/path/to/reviewed-package/assets \
  -PfoldgptExecutorJni=/absolute/path/to/reviewed-package/jniLibs \
  -PfoldgptRequireExecutor=true \
  :app:assembleDebug
```

These are build interfaces, not a verified end-to-end fresh-install recipe. The
packaging check deliberately refuses an APK with the executor omitted: such an
update can lose project access and produce `EACCES` in new conversations.

`tools/runtime/build-production-candidate.py` retains the original maintainer
workflow: it selects a dated output tree, fixed Windows JDK/Gradle locations and
an already frozen transport. It is not the portable contributor entry point.
Use its verification logic as a reference when preparing a new package, and
retain the complete build and source evidence for any candidate.

## Signing and private keyring import

Public builds use Android Gradle Plugin's normal local debug keystore by default.
Your key will differ from another installation's key; Android only accepts an
in-place update signed with that installation's original identity. Do not remove
an existing installation merely to bypass this check: its private workspace may
contain user data.

To sign a debug candidate with an explicitly supplied existing key, set
`FOLDGPT_SIGNING_KEYSTORE`. Optional environment variables are
`FOLDGPT_SIGNING_STORE_PASSWORD`, `FOLDGPT_SIGNING_KEY_ALIAS` and
`FOLDGPT_SIGNING_KEY_PASSWORD`. The defaults are Android's standard debug key
values. Set `FOLDGPT_SIGNING_CERT_SHA256` to enforce the expected certificate
fingerprint for an update. No public build searches the maintainer's private
storage, and no keystore belongs in this repository.

The development-only `tools/provision-keyring.py` requires both `--serial` and
`--secret-file`. It stages an existing credential through private stdin for
Android Keystore import, without printing the credential. This is a migration
tool, not a normal-user setup step.

## What counts as a release candidate

Successful host tests or compilation do not qualify a mobile package. Before
offering an installable release, record a clean installation, login, local command
execution, independent conversations, stop/crash cleanup, fold/unfold behavior,
background recovery and reboot, along with process and memory observations.
Check the proprietary client integration and preserve upstream source/license
obligations. See [compatibility](compatibility.md), [security](../SECURITY.md) and
[contributing](../CONTRIBUTING.md) for the acceptance boundaries.
