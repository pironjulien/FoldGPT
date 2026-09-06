# Source publication — 6 September 2026

Repository: https://github.com/pironjulien/FoldGPT

This publication contains reviewed source for an experimental Android host. It is not an APK release, a one-click installer or a validated beta. The public snapshot excludes historical screenshots, marketing mockups, generated binaries, account profiles and Linux images. The earlier development history is retained locally.

## Verified on the test Fold

| Area | Observation |
| --- | --- |
| Integrated runtime | `app.foldgpt` runs the official ChatGPT Linux ARM64 client and Codex interface under Android UID 10412, using its own storage and service. This UID is an observation from the test device, not a required installation ID. |
| Native execution | PRoot and matching loaders were compiled from `vendor/proot` commit `7266fb3e8516535682f5a9c8f3a7e70f6506eddb`. Execution uses the phone's ARM64 CPU. |
| Display | Shared-memory mapping and an `xfwm4` window manager enable the fullscreen client at 2448 × 1848. Observed XRandR modes range from 59.95 to 119.98 Hz; rendered FPS and latency have not been measured. |
| GPU | Mesa 26.2.2 foldgpt5 is installed with corrected Xlorie. Two renderpass lifetime fixes preserve Adreno acceleration and pass all 24 independent GLES pixel cases, Vulkan/GLX probes, 20 settings sections and repeated actual Plugins/Browser taps after normal restart. The reproduced black-menu corruption is resolved; broader reliability and rendered FPS remain unmeasured. See [GPU evidence](docs/verification-gpu-renderpasses-2026-09-06.md). |
| Integrated browser | Two real Codex turns created/read Example Domain, clicked through to IANA and navigated back, with actual CUA results and independent final-page inspection. Those operations pass; remaining browser features are not certified. See [browser evidence](tools/browser/README.md). |
| External links | The guest's separate Android link bridge opened Example Domain in Android's selected browser. Background requests and invalid numeric hosts were refused. This does not establish external-browser automation. |
| Samsung keyboard | Actual touch in an editable field produced Android IME shown=true; touch outside produced shown=false. The user confirmed this interaction works. |
| IME lifecycle | A process-owned socket and serialized shutdown eliminate the reproduced bind conflict after Activity replacement. Repeated software display transitions retained the Linux process. |
| Kernel protection experiments | The untouched official Codex 0.153.4 completed an offline command/exec fixture under native Landlock/seccomp in the actual app context. The parent independently verified created files, denied writes and cleanup. This fixed, credential-free diagnostic is not the production managed executor. |
| Native filesystem RPC | The real stdio endpoint passed 34 responses and 12 grouped checks in a debug Zygote service using authenticated official Android/Bionic CPython. Independent collection verified physical files, inode, refusals and executable/APK hashes. The supervisor runs outside PRoot with inherited seccomp and no isolation shim; live Desktop routing and a complete process executor remain unfinished. See [Android RPC evidence](tools/executor/native-files-android-rpc.md). |
| Private guest bridge | A GNU ARM64 bridge under PRoot reached the native Android/Bionic broker through an app-private Unix socket. The latest fixture passed 53 responses across two sessions, including readDirectory/walk/copy/remove, protected mutation refusals and streamed block reads of a 38,797,325-byte binary file. Independent collection checked actual peers, final files, exact offsets/EOF, eight source snapshots, 28 native libraries and the tested APK before/after. UID checks do not distinguish programs sharing the app UID; no normal model task is claimed. See [private bridge evidence](tools/executor/private-exec-android.md). |
| Inactive installation v2 | The Android coordinator prepared authenticated Debian, its guest account, the intact official client, vault and GNOME collection twice, with independent verification of retained identities. The root remains `PREPARED`; no activation, client launch or model task was attempted. See [combined preparation](docs/install/combined-preparation-probe.md). |
| Inactive installation v3 | Two real Android calls prepared/revalidated integration, client and vault after recovery of a permission conflict. Independent native collection matched all 345 entries: 29 integration and 316 XKB entries, plus retained root/package/report identities and hashes. The stage remains `PREPARED`, without activation. See [v3 evidence](docs/install/inactive-native-integration.md). |
| Keyring startup | Two cold launches unlocked the existing encrypted keyring without a Linux prompt. A nonexportable Android Keystore key encrypts its password; the private plaintext import was removed. Android must be unlocked when starting the runtime. |
| Folding | One real fold/reopen produced the expected display-area callbacks, launched official ChatGPT Android and retained the same Linux runtime PID. Reopening FoldGPT restored the desktop interface. |
| Android state | The inspected bootloader was locked, verified boot green, SELinux enforcing and Knox warranty bit zero. No Android root or bootloader unlock was used. |

The runtime belongs to FoldGPT. The existing installation was prepared with
development tooling and Termux. Independently built PRoot, matching loaders,
talloc and shared memory have since been adopted in the development APK, with
installed hashes and actual Android storage/execution checks. The separate
authenticated Debian preparation above does not replace that live root.

The newer [v3 inactive integration route](docs/install/inactive-native-integration.md)
adds the GPU and guest integration payload. After correcting a shared state
directory permission conflict, its actual Android combined probe passes two
complete calls with the same root, integration report, client and vault.
The execution and original independent collection used APK `f6f5...`; the later
collection under APK `b47b...` inspected the same retained report and stage.
It did not rerun the coordinator or produce that earlier execution report.
The linked evidence records both full hashes. This recovered installation
remains inactive and has not started a display/client.
The assembled fresh installer and general Codex executor remain unfinished.

## Known limits

- V5 was verified on-device: touch opens, outside touch closes, programmatic editor refocus leaves the keyboard closed, and another deliberate touch reopens it. Samsung key taps entered `aet`; the test text was removed without submission. Composition, dictation and every modal have not been exhaustively tested.
- Complete protected local Codex model execution has not passed. The existing path's Debian `bwrap` failure is a recorded blocker; the private file bridge and fixed offline command fixture do not provide production Desktop routing, arbitrary managed processes, full filesystem compatibility, TTY or networking.
- Settings → Configuration → Diagnostics still has an unresolved official workspace-runtime dependency failure. The recorded 6 September configuration provides no Linux ARM64 runtime entry; manifest retrieval reports `Failed to download primary runtime manifest (404 ).` The Bionic interpreter used by the debug native supervisor does not replace or repair this upstream runtime.
- Integrated-browser creation, reading, clicking and history navigation are qualified only for the recorded pages. Uploads, downloads, authentication, local development sites and PiP remain unverified.
- The compatibility shim simulates isolation calls. It does not provide equivalent Linux namespace protection; see [NATIVE-AUDIT.md](NATIVE-AUDIT.md).
- Adreno rendering and the reproduced menu defect pass the foldgpt5 checks. Broader reliability, thermal and battery testing remains; see the [current GPU report](docs/verification-gpu-renderpasses-2026-09-06.md), including the separate unresolved diagnostic-color investigation.
- Remote, active-task continuity during folding/locking, long background runs, inner split-screen, updates and a fresh installation have not passed their functional tests. One physical fold/reopen of an idle desktop session passed; it is not a complete reliability test.
- The installed APK is debuggable. Its local debugging endpoint is part of the experimental keyboard bridge. Native RPC probe services and CPython diagnostic assets are debug-only; successful release-content checks concern an unsigned, uninstalled check artifact, not a released APK.

Claims about 120 FPS, full Codex functionality, automatic Remote pairing, one-click installation, production security or guaranteed payment/warranty compatibility are outside the verified scope.

## Distribution

The source includes pinned upstream references and the FoldGPT integration code. A future binary release needs a reproducible dependency inventory, corresponding source and license notices, as described in [LEGAL.md](LEGAL.md), a retained APK signing identity and an authenticated update channel. First-install activation, normal protected model work, active-task lifecycle and updates preserving account/workspace data must pass the [acceptance gates](docs/install/end-to-end-architecture.md#acceptance-and-publication-evidence). OpenAI's proprietary client and all account data remain outside the distribution.
