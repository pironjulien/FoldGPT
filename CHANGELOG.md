# Changelog

## Unreleased — 2026-09-06

- Built and installed `app.foldgpt` with embedded Termux:X11, a separate foreground runtime service and private Linux storage. The integrated host now runs the official ChatGPT client and Codex interface independently of the Termux runtime host.
- Compiled PRoot and matching loaders from pinned commit `7266fb3e8516535682f5a9c8f3a7e70f6506eddb`, resolving the Termux-specific loader paths.
- Added shared-memory mapping and an `xfwm4` session. Verified fullscreen at 2448 × 1848; XRandR reports 119.98 Hz, with application FPS still unmeasured.
- Verified Samsung keyboard opening and closing through actual touch. Fixed unwanted reopening: only deliberate pointer input opens the keyboard. On-device tests confirmed automatic refocus stays closed, the next touch reopens, and Samsung key taps enter text.
- Added explicit keyboard visibility requests over a Unix socket with peer UID checks. The CDP bridge follows page targets and reloads without transmitting field contents.
- Added development build, migration, guest-script deployment and diagnostic tools. Migration refuses existing data and cleans private temporary archives on failure; the unvalidated legacy installer now exits explicitly.
- Reproduced a local Codex execution blocker: Debian `bwrap` 0.12.0 fails `--help` when `/proc/sys/kernel/overflowuid` is inaccessible. Local tools remain blocked.
- Prepared reviewed source for publication at `pironjulien/FoldGPT`, excluding historical media, binaries and account data. Recorded verified behavior and remaining gates in `PUBLICATION.md`.

## 2026-09-05

- Installed Debian ARM64 and Termux:X11 on the Fold without unlocking or rooting Android.
- Official ChatGPT failed its namespace checks under ordinary PRoot. A full Debian QEMU experiment reached authentication, but a custom task did not complete during the recorded test.
- Added a native PRoot startup shim, display settings, launcher APK and initial keyboard daemon. The client displayed its interface and later answered a conversation.
- Audited the shim: `chroot` returned success while an outside marker remained accessible. Recorded the isolation limits in `NATIVE-AUDIT.md`.
- The initial keyboard daemon toggled visibility and was not validated for reliable everyday touch use. The original launcher depended on the separate Termux:X11 application.
