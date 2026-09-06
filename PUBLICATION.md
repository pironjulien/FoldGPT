# Source publication — 6 September 2026

Repository: https://github.com/pironjulien/FoldGPT

This publication contains reviewed source for an experimental Android host. It is not an APK release, a one-click installer or a validated beta. The public snapshot excludes historical screenshots, marketing mockups, generated binaries, account profiles and Linux images. The earlier development history is retained locally.

## Verified on the test Fold

| Area | Observation |
| --- | --- |
| Integrated runtime | `app.foldgpt` runs the official ChatGPT Linux ARM64 client and Codex interface under Android UID 10412, using its own storage and service. This UID is an observation from the test device, not a required installation ID. |
| Native execution | PRoot and matching loaders were compiled from `vendor/proot` commit `7266fb3e8516535682f5a9c8f3a7e70f6506eddb`. Execution uses the phone's ARM64 CPU. |
| Display | Shared-memory mapping and an `xfwm4` window manager enable the fullscreen client at 2448 × 1848. Observed XRandR modes range from 59.95 to 119.98 Hz; rendered FPS and latency have not been measured. |
| GPU | Vulkan, GLX, X11 Present and compositor texture pixel tests pass on Adreno 840. Mesa revision 4 and corrected Xlorie are installed; the actual File menu renders correctly and the targeted timestamp/refresh errors are absent. Broader display reliability and rendered FPS remain unmeasured. |
| Samsung keyboard | Actual touch in an editable field produced Android IME shown=true; touch outside produced shown=false. The user confirmed this interaction works. |
| IME lifecycle | A process-owned socket and serialized shutdown eliminate the reproduced bind conflict after Activity replacement. Repeated software display transitions retained the Linux process. |
| Kernel protection experiments | The untouched official Codex 0.153.4 completed an offline command/exec fixture under native Landlock/seccomp in the actual app context. The parent independently verified created files, denied writes and cleanup. This fixed, credential-free diagnostic is not the production managed executor. |
| Keyring startup | Two cold launches unlocked the existing encrypted keyring without a Linux prompt. A nonexportable Android Keystore key encrypts its password; the private plaintext import was removed. Android must be unlocked when starting the runtime. |
| Folding | One real fold/reopen produced the expected display-area callbacks, launched official ChatGPT Android and retained the same Linux runtime PID. Reopening FoldGPT restored the desktop interface. |
| Android state | The inspected bootloader was locked, verified boot green, SELinux enforcing and Knox warranty bit zero. No Android root or bootloader unlock was used. |

The runtime now belongs to FoldGPT. The existing installation was prepared with
development tooling and Termux. Independent native-library builds and a pristine
Debian base are now available as reviewed local candidates; neither replaces
the installed runtime automatically. See [installation preparation](docs/install/README.md).

The new host checks cover authenticated Debian inputs, encrypted-keyring
creation/recovery, file-policy differences and selected concurrent process
accesses. They are explicitly separated from the observations on the phone
above. The assembled fresh installer and general Codex executor remain unfinished.

## Known limits

- V5 was verified on-device: touch opens, outside touch closes, programmatic editor refocus leaves the keyboard closed, and another deliberate touch reopens it. Samsung key taps entered `aet`; the test text was removed without submission. Composition, dictation and every modal have not been exhaustively tested.
- Local Codex command execution fails. One reproduced blocker is Debian `bwrap` 0.12.0: `bwrap --help` exits 1 when access to `/proc/sys/kernel/overflowuid` is denied. Installing the package alone does not resolve execution.
- The compatibility shim simulates isolation calls. It does not provide equivalent Linux namespace protection; see [NATIVE-AUDIT.md](NATIVE-AUDIT.md).
- Adreno rendering and the targeted GPU corrections now pass in the development session. The broader reliability, thermal and battery checks remain; see the [current device checkpoint](docs/verification-2026-09-06.md).
- Remote, active-task continuity during folding/locking, long background runs, inner split-screen, updates and a fresh installation have not passed their functional tests. One physical fold/reopen of an idle desktop session passed; it is not a complete reliability test.
- The development APK is debuggable. Its local debugging endpoint is part of the experimental keyboard bridge.

Claims about 120 FPS, full Codex functionality, automatic Remote pairing, one-click installation, production security or guaranteed payment/warranty compatibility are outside the verified scope.

## Distribution

The source includes pinned upstream references and the FoldGPT integration code. A future binary release needs a reproducible dependency inventory, corresponding source and license notices, as described in [LEGAL.md](LEGAL.md). OpenAI's proprietary client and all account data remain outside the distribution.
