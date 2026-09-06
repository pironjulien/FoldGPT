# Changelog

## Unreleased — 2026-09-06

- Serialized debug Codex probe completion with Android service starts and bound listener receipt, execution and cleanup to monotonic deadlines. These lifecycle changes still need their Android runtime test.
- Built the complete corrected Xlorie library with official Linux NDK r29, preserving case-sensitive header lookup on ext4. Its 1,986 exports match the baseline and LOAD alignment is 16 KiB. The candidate APK builds and contains the verified library hash; Android runtime validation is pending reconnection.
- Implemented a pure, strict resolver for a documented subset of Codex 0.153.4 managed filesystem policies. All 23 tests pass, including independent A/B/C policies on the same path, metadata exceptions and URI boundaries. This validates lexical decisions only; native enforcement remains a separate implementation step.
- Fixed GPU archive validation/transfer races by transferring the same validated byte snapshot and comparing its precomputed digest. Six host regressions pass, including concurrent replacement, remote tampering and real Linux extraction/retry after truncation. Existing revisions remain intact. The revised Android deployment run is pending.
- Added an offline official-Codex fixture probe in a permission-protected, debug-only Android service. The binary starts under native restrictions; the final initialize/command-exec/file verification remains pending after USB disconnected. No model request or account profile is used.
- Verified actual Adreno 840 rendering in the official client through Mesa 26.2.2 Zink/Turnip: GPU composition/rasterization enabled, Vulkan and GLX pixel tests passed, X11 Present completed. Corrected Mesa's failed-pixmap-import handling; the compositor texture test now passes and the desktop is visible with `xfwm4` retained. Menu transitions still exhibit intermittent corruption; neither reliable GPU presentation nor 120 FPS is claimed.
- Prepared additional Mesa fixes for the real KGSL calibrated-timestamp ioctl and RandR refresh reporting when XF86VidMode is absent. These compiled candidate changes await device validation after USB disconnected; the installed session still selects `foldgpt3`.
- Combined the native broker and PRoot experiments: a real Debian shell created and appended permitted files while eight protected/outside redirections and two mode changes were refused. The parent independently verified contents, absent files and modes. Scratch chmod is mediated explicitly; this fixed-script proof does not implement arbitrary Codex policy or read confidentiality.
- Fixed IME endpoint lifetime across display Activity recreation: one process-owned endpoint, serialized shutdown and rebinding, and the currently resumed Activity receives requests. Repeated transitions no longer produced `Address already in use`; peer UID and inner-display checks remain enforced.
- Added private, read-only log and GPU diagnostics. The initial CDP report identified ANGLE on llvmpipe with GPU composition disabled; Android's EGL presentation alone did not establish client acceleration. Subsequent Adreno results are recorded above.
- Added debug-only native Landlock experiments under the actual application UID and inherited Zygote seccomp filter. Real writes outside the granted directory and symlink escapes are refused. A broker experiment preserves protected project metadata with four granted opens and nine expected denials, independently verified from the parent.
- Verified a fixed Debian shell under a Landlock policy installed before PRoot starts: the shell executes and an attempted workspace write is refused. The experiments are not a production sandbox or an integrated Codex executor.
- Updated the visible-Activity handoff to ChatGPT Android to use the current explicit PendingIntent launch delegation on API 36+. Automatic reopening on unfold is still not implemented.
- Added Android Keystore AES-GCM protection and private stdin delivery for the existing encrypted GNOME keyring. Two cold launches unlocked it without a Linux prompt; the one-time plaintext import was removed. Cold startup requires Android to be unlocked.
- Added inner-display gating using Jetpack WindowManager's display-area folding features. During a real user fold/reopen, the Linux display closed, the official Android client was launched, and the runtime PID remained unchanged. Reopening FoldGPT restored the existing Linux interface. This does not yet validate an active Codex task or Remote.
- Added native Android isolation probes outside PRoot. On the test device, Landlock ABI 6 and seccomp notification are available; user namespace creation returns EINVAL and mount namespace creation EPERM. The official Codex 0.153.4 legacy Landlock route rejects the tested workspace policies; local commands remain blocked.
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
