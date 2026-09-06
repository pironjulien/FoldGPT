# FoldGPT

Experimental Android host for the official ChatGPT Linux ARM64 desktop client on a Galaxy Z Fold.

**Status: working desktop interface in a development prototype; not a public beta.** The integrated `app.foldgpt` APK runs the unmodified client and Codex interface in its own Android app storage and UID, with native ARM64 execution and Adreno acceleration. The reproduced settings-menu corruption is fixed, selected integrated-browser operations pass, and the private guest-to-Android file bridge is verified. Inactive v3 installation and independent native inspection also pass. Complete protected local task execution, an autonomous installer, Remote, updates and sustained background reliability remain unfinished or unverified. See [PUBLICATION.md](PUBLICATION.md) for the tested scope.

## What works

- Termux:X11 is embedded in the FoldGPT display Activity. A separate foreground service owns the native ARM64 Linux runtime; Termux is no longer the running application's host. The old Termux applications were removed from the test device with their data retained, and FoldGPT still starts independently. Its display notification and help use FoldGPT's own interface.
- PRoot is built from pinned source in `vendor/proot`. Matching loaders fix the previous Termux-specific loader paths. Shared-memory mapping and `xfwm4` provide the working X11 session.
- The client fills the tested inner display at 2448 × 1848. XRandR mode reports have ranged from 59.95 to 119.98 Hz; application frame rate has not been measured.
- The official client reports ANGLE on Zink/Turnip and Adreno 840, with GPU composition and rasterization enabled. The installed Mesa 26.2.2 foldgpt5 corrects two renderpass lifetime bugs without disabling GPU features. All 24 independent GLES pixel cases pass on the Fold, alongside Vulkan/GLX probes, all 20 settings sections and repeated real Plugins/Browser taps after a normal restart. These checks cover the reproduced corruption; broader display reliability and application FPS remain unmeasured. See [the GPU verification](docs/verification-gpu-renderpasses-2026-09-06.md).
- Two real Codex turns on the Fold opened and read Example Domain in the official integrated browser, clicked its link to IANA and navigated back. Independent page inspection confirms the result. External links use a separate guest-to-Android bridge that opens Android's selected browser. Uploads, downloads, authentication, local development pages and PiP remain unverified. See [the browser evidence](tools/browser/README.md).
- A debug service runs the real filesystem RPC endpoint with official Android/Bionic CPython outside PRoot. The initial fixture passes 34 responses and 12 grouped checks. A later GNU guest bridge under PRoot reaches the native Android broker through a private Unix socket: its latest 53 responses across two sessions verify reads/writes, directory listing/walking, copy/remove, policy refusals, block reads of a 37 MiB binary file and descriptor/lease cleanup. Independent collection binds the complete transcript and physical files to the eight packaged sources, 28 native libraries and exact tested APK. These are recorded diagnostic fixtures; no normal model task or production Desktop route is connected. See [the original RPC evidence](tools/executor/native-files-android-rpc.md) and [the private bridge](tools/executor/private-exec-android.md).
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

This device-assisted development recipe runs the preparation scripts in that order: the second builds PRoot and matching loaders from the pinned source. Its preparation step collects native inputs from the development device and records hashes under ignored `android/native/`. It does not reproduce the independently built library set now adopted in the test APK; use the dedicated build notes below for those sources and checks. The optional `-PbuildX11FromSource` Gradle path has not itself been verified for FoldGPT.

The separate [native X11 build](tools/gpu/X11-BUILD.md) supplies the corrected
library adopted in the development APK. Its subsequent device rendering checks
are recorded in [the display checkpoint](docs/verification-2026-09-06.md), with
the later Mesa correction recorded above. The build records source and patch
hashes and preserves Linux filename case in its ext4 build directory.

An [independent Android runtime build](tools/install/native/README.md) now also
cross-compiles PRoot, its matched loaders, talloc and shared memory from pinned
sources without a phone or Termux. All five installed library hashes were
verified after adoption in the development APK. Actual Zygote storage, pristine
Debian execution and shared-memory checks pass, followed by an on-device guest
process cancellation regression. These results do not establish a fresh install
or a complete protected executor.

An APK build does not install Linux. `tools/migrate-device-runtime.py` copies an existing on-device development installation into an empty FoldGPT destination and refuses existing data. It is not a fresh installer. `install.sh` exits explicitly because its historical workflow is unvalidated.

The [combined inactive preparation](docs/install/combined-preparation-probe.md)
now passes twice on the Fold: authenticated Debian, guest account, intact official
client, Android vault and GNOME collection are prepared and revalidated with the
same root and package inodes. That v2 stage remains `PREPARED`; it has not been
activated or used to launch the client. The newer
[v3 integration route](docs/install/inactive-native-integration.md), which adds
the GPU and guest integration payload, has passed two complete Android calls
after recovery of a shared-state permission conflict. Independent native
collection verifies all 345 manifest entries, retained identities and hashes,
and absence of activation. The original run/collection used APK `f6f5...`; a
later inspection under `b47b...` reread the same stage without rerunning the
coordinator. Exact APK identities and evidence are in the v3 report. The
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

The guest session requires Debian's `python3-websockets`, `python3-secretstorage`, `dbus-x11`, `xfwm4` and `wmctrl`, in addition to the client dependencies. The current development migration also requires provisioning the existing keyring password once with `tools/provision-keyring.py --serial YOUR_ADB_SERIAL --secret-file PRIVATE_SECRET_PATH`. It refuses to overwrite existing credentials and does not print the secret. Fresh vault/collection preparation has passed within the inactive Android v2 and v3 coordinators above; activation and the complete installer remain unfinished. Obtain OpenAI's client from its official source; no OpenAI binaries are supplied here.

## Next validation gates

- Connect and verify the complete protected executor with a normal Codex model task. The private file bridge and earlier fixed offline command fixture do not supply production Desktop routing, arbitrary managed processes, full filesystem compatibility, TTY or networking. The original Debian `bwrap` failure remains a recorded blocker in the existing local execution path.
- Resolve the official workspace-runtime diagnostic failure. The 6 September runtime configuration has no Linux ARM64 entry and manifest retrieval returns HTTP 404. The Android/Bionic fixture interpreter is a separate supervisor component and does not repair that upstream dependency supply.
- Verify the remaining browser operations, including file transfer, authentication and local development sites.
- Broaden keyboard verification to field switching, Unicode, Samsung composition and dictation.
- Test native Remote, active-task continuity, locking, sustained background operation, inner split-screen and clean shutdown. One physical fold/reopen of the idle desktop session has passed.
- Complete runtime validation and activation after the verified inactive v3 preparation, then prove a fresh installation and signed APK/client updates preserving account and workspace state.
- Establish the production isolation model, dependency provenance and measured performance.

Native experiments prove Landlock enforcement, a fixed offline official Codex
command fixture and the Android filesystem RPC checks described above. The
latter uses Bionic after the native observer identified GNU Python's blocked
`set_robust_list` syscall under Android's inherited seccomp filter. No signal or
Android protection is suppressed by that correction. The tested supervisor has
no PRoot or isolation-shim mappings; the existing desktop compatibility boundary
still applies. See [NATIVE-AUDIT.md](NATIVE-AUDIT.md) and the
[RPC scope](tools/executor/native-files-android-rpc.md).

This independent project is not affiliated with or endorsed by OpenAI or Samsung. See [LEGAL.md](LEGAL.md), [PRODUCT.md](PRODUCT.md) and [CHANGELOG.md](CHANGELOG.md).
