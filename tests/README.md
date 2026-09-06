# Development checks

## Filesystem policy and GPU deployment

```powershell
python -m unittest discover -s tests -p 'test_managed_policy.py' -v
python -m unittest discover -s tests -p 'test_gpu_archive.py' -v
```

The 23 policy tests validate the preparatory resolver's immutable lexical
decisions and explicit rejection of unsupported input. They do not enforce
native filesystem permissions; see `tools/policy/README.md`.

GPU deployment tests use an ADB stand-in to reproduce archive replacement and
transfer tampering, without touching a device. On Linux, a sixth test also runs
the real extraction shell with a truncated archive, retries successfully and
checks that an existing revision is preserved. That test is skipped on Windows;
run it with Python inside WSL to obtain all six results. These host tests do not
replace GPU pixel tests or Android deployment verification.

## Focus bridge

Run from the repository root:

```powershell
python -m unittest discover -s tests -p 'test_foldgpt_ime.py' -v
node tests/keyboard-focus.test.cjs
```

The Python checks require `websockets` and use an in-memory CDP transport. The
DOM checks require Node.js, Playwright and its bundled Chromium. They launch a
temporary headless browser, block network requests and use an inline fixture.
They do not use a personal browser profile, contact ChatGPT, run paid tasks or
control the phone.

The checks cover deliberate touch/re-tap signals, same-process frame handover,
open shadow DOM, CDP response matching, navigation context cleanup and concurrent
intent ordering. A Send-button regression verifies that the application's later
programmatic prompt focus cannot reopen the keyboard, while a new deliberate tap
can. Initialization, reconnection, window focus and visibility resume never open
the keyboard. Disposal and replacement leave one listener with increasing
sequence IDs. The hook transmits only boolean visibility, a fixed reason and a
sequence number.

Hook V5 supports `globalThis.__foldgptImeHook.dispose()` for live replacement.
V4 lacked removable listener handles and requires one document reload when
upgrading; replacing its global guard alone cannot remove its old listeners.

They do **not** establish that Android actually showed its keyboard, that Samsung
composition/autocorrect works, or that all official client windows are supported.
Cross-origin frames running in a separate renderer require CDP target attachment;
closed shadow roots cannot be inspected by this DOM hook. These remain device and
integration coverage limits, not claims of universal support.

## Android kernel experiments

Build the fixed experiments with Android NDK 29, then rebuild/install the debug
APK. They are excluded from release builds. Open FoldGPT before broadcasting so
Android's stopped-package handling cannot skip the receiver.

```powershell
./tools/build-landlock-probe.ps1
gradle -p android :app:assembleDebug
adb -s YOUR_SERIAL install -r android/app/build/outputs/apk/debug/app-debug.apk
adb -s YOUR_SERIAL shell am start -n app.foldgpt/.FoldActivity
adb -s YOUR_SERIAL shell am broadcast -n app.foldgpt/.LandlockProbeReceiver
adb -s YOUR_SERIAL shell am broadcast -a app.foldgpt.PROBE_BROKER -n app.foldgpt/.LandlockProbeReceiver
adb -s YOUR_SERIAL shell am broadcast -a app.foldgpt.PROBE_SHELL -n app.foldgpt/.LandlockProbeReceiver
adb -s YOUR_SERIAL shell am broadcast -a app.foldgpt.PROBE_PROOT -n app.foldgpt/.LandlockProbeReceiver
```

Read each result from `cache/landlock-probe.log`, `cache/broker-probe.log`,
`cache/shell-probe.log` or `cache/proot-probe.log` with `adb shell run-as
app.foldgpt cat ...`. The receiver executes asynchronously; a broadcast result
of zero alone is not a passing test. Require the native process's final independent
verification and the corresponding `FoldGPT-Probe` completion in logcat. See
`NATIVE-AUDIT.md` for the exact scope and deliberate metadata limitation in the
first experiment. These tests do not invoke a model or demonstrate Codex integration.
