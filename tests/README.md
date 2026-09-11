# Development checks

Keep regression tests with the code they protect. They cover input, credentials,
installation, files, process ownership and recovery; they are not application
features or generated build output. Retired one-off inspection scripts are not
part of the maintained test suite.

## Linux host tests — the CI entry point

Run from the repository root with Python 3.12 and an ordinary nonroot Linux
account. Windows contributors can use Python inside WSL.

```sh
python3 -m venv work/host-venv
work/host-venv/bin/python -m pip install -r tools/ci/requirements-host.txt
work/host-venv/bin/python tools/ci/run-host-tests.py
```

The runner selects 26 suites, prints the actual collection count for each and
rejects empty collections. Each suite runs in a fresh process to isolate local
imports. To run one suite:

```sh
work/host-venv/bin/python tools/ci/run-host-tests.py --suite tests/test_foldgpt_ime.py
```

These checks exercise archive integrity, client installation, keyring and IME
protocols, execution messages, runtime identity and ownership. Filesystem and
process checks use real local fixtures; the IME transport is offline. Some rootfs
cases require a separate privileged/static-compiler fixture and report a skip
when unavailable. A successful host run does not qualify an Android package.

Do not run a recursive discovery over every `test*.py`: specialized integration
scripts require explicit native binaries, APKs, dedicated UIDs or an Android
device. Python on Windows also lacks the POSIX descriptors, permissions and
process behavior required by the complete host selection.

## Input and Android

| Check | Command and prerequisites |
| --- | --- |
| Offline focus bridge | `python tools/ci/run-host-tests.py --suite tests/test_foldgpt_ime.py`; Python dependencies above. |
| DOM focus behavior | `node tests/keyboard-focus.test.cjs`; a development installation of Node.js, Playwright and its matching Chromium. This optional test is not installed or run by the Python CI job. |
| Android unit tests | From `android/`: `gradle --no-daemon :app:compileDebugJavaWithJavac :app:testDebugUnitTest`; configure the Android/JDK toolchain and prepare the five native runtime libraries required by `preBuild`. |

The DOM fixture blocks network access and uses a temporary headless browser
without a personal profile. It covers taps, the Send button, frame/shadow-DOM
focus and listener replacement. It does not prove Samsung keyboard composition
or cross-process frame support on a phone.

Android unit tests stay in the standard `android/app/src/test` tree. They cover
launch/stop generations, recovery, concurrent conversations, callbacks, URLs,
SMS, accessibility and installation. Tests under `src/androidTest` require a
separately prepared device. APK packaging additionally requires the reviewed
executor inputs; see the [build guide](https://github.com/pironjulien/FoldGPT/blob/main/docs/build.md).

## Native and integration checks

These suites remain next to their runtime or build recipe so their fixtures,
imports and source snapshots stay together. Select the recipe for the code being
changed rather than treating every experiment as a release check.

| Area | Entry point | Required environment |
| --- | --- | --- |
| PRoot cancellation and strict behavior | [Native regression recipes](../tools/install/native/README.md#host-regression-tests) | Nonroot Linux x86_64, host C toolchain, talloc headers/library, Git, Make, Python and network access to the pinned upstream source. |
| Native files and processes | `tools/executor/native-host-files-test.sh` / `native-bootstrap-files-test.sh` | Linux toolchain and an explicitly supplied compiled host supervisor. See the [supervisor recipe](../tools/executor/bionic-supervisor/README.md). |
| Installation transactions | `bash tools/install/transaction/run-jvm-tests.sh` | Linux, JDK, curl; checksum-pinned JVM dependencies are downloaded into ignored project storage. |
| Integration bundle installation | `bash tools/install/integration-native/run-jvm-tests.sh` | Linux/JDK and the dependencies prepared by the transaction runner. |
| HTTPS acquisition | [HTTPS test recipe](../tools/install/https-acquisition/README.md) | Linux/JDK, transaction test dependencies and the configured Android SDK jar. Uses a test-only truststore. |
| Native recovery | `python -B -m tools.executor.test_native_session_recovery` | A dedicated nonroot Linux UID with no other workload; run alone because recovery checks the complete UID process population. |
| Package and device qualification | Explicit drivers under `tools/executor/runas-runtime/` and `tools/runtime/` | The exact reviewed libraries, APK and/or device requested by each driver. Host tests cannot replace this evidence. |

Keep real qualification results separate from synthetic protocol fixtures.
Retain source revisions and artifact identities when reporting device behavior.
Historical kernel experiments and their limits are recorded in the
[native startup audit](../docs/history/native-startup-2026-09-05.md); they do not
establish that a current package or a different phone has passed those checks.
