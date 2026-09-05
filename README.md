# FoldGPT

Experimental Android host for the official ChatGPT Linux ARM64 desktop client on a Galaxy Z Fold.

**Status: working desktop interface in a development prototype; not a public beta.** The integrated `app.foldgpt` APK now runs the client and Codex interface in its own Android app storage and UID. Local Codex commands are blocked, and Remote, fold routing, updates and background reliability remain unverified. See [PUBLICATION.md](PUBLICATION.md) for the tested scope.

## What works

- Termux:X11 is embedded in the FoldGPT display Activity. A separate foreground service owns the native ARM64 Linux runtime; Termux is no longer the running application's host.
- PRoot is built from pinned source in `vendor/proot`. Matching loaders fix the previous Termux-specific loader paths. Shared-memory mapping and `xfwm4` provide the working X11 session.
- The client fills the tested inner display at 2448 × 1848. XRandR reports a 119.98 Hz display mode; application frame rate has not been measured.
- Actual touch opens the Samsung keyboard in an editable field and touching outside closes it. The V5 bridge opens only on deliberate pointer input: automatic refocus leaves the dismissed keyboard closed. This was reproduced on-device without a model request; a new touch reopened it. Tapping Samsung keys entered `aet` in the official editor.

`foldgpt_ime.py` and `keyboard-focus.js` observe editable-field focus through a local Chromium debugging connection. They send visibility requests, without field contents, to an Android Unix socket that checks the peer UID. The bridge installs runtime DOM listeners; packaged OpenAI files are not patched.

## Security and compatibility boundary

The current experiment uses `fake_userns.c`, which suppresses namespace requests and simulates successful isolation calls. It is a sandbox compatibility bypass, **not a Linux namespace implementation or a security boundary**. Android app isolation and SELinux remain separate mechanisms. The reproduced confinement failure is documented in [NATIVE-AUDIT.md](NATIVE-AUDIT.md).

On the inspected phone, the bootloader was locked, verified boot was green, SELinux was enforcing and the Knox warranty bit was zero. These observations do not guarantee future compatibility with firmware, banking apps or contractual warranty coverage.

The development APK is debuggable. Keep its Chromium debugging endpoint on loopback; do not expose it over Wi-Fi. Credentials, browser profiles, keyrings and Linux images are excluded from the source publication.

## Development build

Requirements: JDK 21, Android SDK 37, Gradle 9.7.1, Python, ADB and an authorized ARM64 Termux development environment with the runtime libraries and compiler tools. These scripts currently use a device-specific SSH connection through localhost port 18022. Review their device/user settings before use.

Clone with submodules and configure the SDK path in ignored `android/local.properties`:

```powershell
git clone --recurse-submodules https://github.com/pironjulien/FoldGPT.git
cd FoldGPT
python tools/prepare-device-runtime.py
python tools/build-proot-on-device.py
gradle -p android :app:assembleDebug
```

Run the preparation scripts in that order: the second builds PRoot and matching loaders from the pinned source. The Windows build currently collects X11, talloc and Android shared-memory libraries from the installed official packages. Hashes are recorded under ignored `android/native/`. The optional `-PbuildX11FromSource` path has not yet been verified for FoldGPT.

An APK build does not install Linux. `tools/migrate-device-runtime.py` copies an existing on-device development installation into an empty FoldGPT destination and refuses existing data. It is not a fresh installer. `install.sh` exits explicitly because its historical workflow is unvalidated.

For an already initialized debug installation, these tools update FoldGPT's guest scripts or run a diagnostic command:

```powershell
python tools/deploy-session.py --serial YOUR_ADB_SERIAL
python tools/device-shell.py --serial YOUR_ADB_SERIAL /usr/bin/uname -m
```

The guest session requires Debian's `python3-websockets`, `dbus-x11`, `xfwm4` and `wmctrl`, in addition to the client dependencies. Obtain OpenAI's client from its official source; no OpenAI binaries are supplied here.

## Next validation gates

- Resolve local Codex execution. One reproduced blocker is Debian `bwrap` 0.12.0 failing even `--help` because access to `/proc/sys/kernel/overflowuid` is denied.
- Broaden keyboard verification to field switching, Unicode, Samsung composition and dictation.
- Test native Remote, folding, background operation and clean shutdown.
- Provide a fresh installer and verify signed APK/client updates preserve state.
- Establish the production isolation model, dependency provenance and measured performance.

This independent project is not affiliated with or endorsed by OpenAI or Samsung. See [LEGAL.md](LEGAL.md), [PRODUCT.md](PRODUCT.md) and [CHANGELOG.md](CHANGELOG.md).
