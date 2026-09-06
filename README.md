# FoldGPT

Experimental Android host for the official ChatGPT Linux ARM64 desktop client on a Galaxy Z Fold.

**Status: working desktop interface in a development prototype; not a public beta.** The integrated `app.foldgpt` APK now runs the client and Codex interface in its own Android app storage and UID. Secure prompt-free keyring startup and one real fold/reopen cycle are verified. Local Codex commands remain blocked; Remote, updates and sustained background reliability remain unverified. See [PUBLICATION.md](PUBLICATION.md) for the tested scope.

## What works

- Termux:X11 is embedded in the FoldGPT display Activity. A separate foreground service owns the native ARM64 Linux runtime; Termux is no longer the running application's host.
- PRoot is built from pinned source in `vendor/proot`. Matching loaders fix the previous Termux-specific loader paths. Shared-memory mapping and `xfwm4` provide the working X11 session.
- The client fills the tested inner display at 2448 × 1848. XRandR mode reports have ranged from 59.95 to 119.98 Hz; application frame rate has not been measured.
- The official client now reports ANGLE on Zink/Turnip and the actual Adreno 840, with GPU composition and rasterization enabled. Mesa corrections also restore compositor textures. Menu transitions still expose intermittent presentation corruption, so GPU integration is not yet reliable. See [GPU-PROBE.md](GPU-PROBE.md) for the pixel tests, remaining defects and the distinction between installed and candidate builds.
- Actual touch opens the Samsung keyboard in an editable field and touching outside closes it. The V5 bridge opens only on deliberate pointer input: automatic refocus leaves the dismissed keyboard closed. This was reproduced on-device without a model request; a new touch reopened it. Tapping Samsung keys entered `aet` in the official editor.
- A process-owned IME endpoint survives display Activity replacement. Serialized shutdown fixes the reproduced socket conflict after reopening the display; requests still require the app's UID and a resumed inner-display Activity.
- Android Keystore protects the Linux keyring password with a device-bound AES-GCM key. The service sends it through a private stdin pipe; the helper unlocks the existing GNOME collection over an encrypted Secret Service session. Two cold launches succeeded without a Linux prompt. Android must already be unlocked at startup; this does not change Android's screen lock.
- Display-area folding features gate the Linux surface and keyboard. A real fold/reopen launched official ChatGPT Android and kept the same Linux runtime process; opening FoldGPT again restored its interface. The monitor uses public Jetpack WindowManager APIs independently of Activity window size.

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

The separate [native X11 build](tools/gpu/X11-BUILD.md) now compiles a corrected
library and the candidate APK packages it successfully. This is build evidence;
that candidate still awaits on-device validation. The build records source and
patch hashes and preserves Linux filename case in its ext4 build directory.

An [independent Android runtime build](tools/install/native/README.md) now also
cross-compiles PRoot, its matched loaders, talloc and shared memory from pinned
sources without a phone or Termux. Five ELF outputs pass static checks. These
libraries remain separate candidates until their Android tests pass; the recipe
does not replace the APK's existing libraries automatically.

An APK build does not install Linux. `tools/migrate-device-runtime.py` copies an existing on-device development installation into an empty FoldGPT destination and refuses existing data. It is not a fresh installer. `install.sh` exits explicitly because its historical workflow is unvalidated.

The [fresh-install preparation notes](docs/install/README.md) document a verified
guest-script bundle, a [pristine Debian ARM64 build](docs/install/ROOTFS.md), and
the remaining Android bootstrap requirements. The
[executor integration audit](tools/executor/README.md) records the official
policy handoff and its native enforcement gap. The
[fold lifecycle notes](docs/fold-lifecycle.md) explain current background-launch
limits. These preparatory components do not constitute a functional public release.

For an already initialized debug installation, these tools update FoldGPT's guest scripts or run a diagnostic command:

```powershell
python tools/deploy-session.py --serial YOUR_ADB_SERIAL
python tools/device-shell.py --serial YOUR_ADB_SERIAL /usr/bin/uname -m
python tools/inspect-gpu.py --serial YOUR_ADB_SERIAL
python tools/audit-device-logs.py --serial YOUR_ADB_SERIAL
```

The guest session requires Debian's `python3-websockets`, `python3-secretstorage`, `dbus-x11`, `xfwm4` and `wmctrl`, in addition to the client dependencies. The current development migration also requires provisioning the existing keyring password once with `tools/provision-keyring.py --serial YOUR_ADB_SERIAL --secret-file PRIVATE_SECRET_PATH`. It refuses to overwrite existing credentials and does not print the secret. [Fresh keyring preparation](docs/install/keyring.md) now has Linux checks and an Android generation API, but remains separate from a complete installer. Obtain OpenAI's client from its official source; no OpenAI binaries are supplied here.

## Next validation gates

- Resolve local Codex execution. One reproduced blocker is Debian `bwrap` 0.12.0 failing even `--help` because access to `/proc/sys/kernel/overflowuid` is denied.
- Broaden keyboard verification to field switching, Unicode, Samsung composition and dictation.
- Test native Remote, active-task continuity, locking, sustained background operation, inner split-screen and clean shutdown. One physical fold/reopen of the idle desktop session has passed.
- Provide a fresh installer and verify signed APK/client updates preserve state.
- Establish the production isolation model, dependency provenance and measured performance.

Native experiments now prove that the phone enforces Landlock, that a fixed
broker can preserve project metadata while granting individual write handles,
and that a Debian shell can run with filesystem restrictions installed outside
PRoot. These are bounded tests, not the missing Codex executor. Reproduction and
limits are recorded in [NATIVE-AUDIT.md](NATIVE-AUDIT.md).

This independent project is not affiliated with or endorsed by OpenAI or Samsung. See [LEGAL.md](LEGAL.md), [PRODUCT.md](PRODUCT.md) and [CHANGELOG.md](CHANGELOG.md).
