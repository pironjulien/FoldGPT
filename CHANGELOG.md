# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to Semantic Versioning.

## [Unreleased]

### Added
- **`fake_userns.c` & `fake_userns.so`**: User-space dynamic linker (`LD_PRELOAD`) shim intercepting Chromium sandbox assertions (`clone(CLONE_NEWUSER)`, `/proc/self/ns/user`), enabling 100% native bare-metal execution of unmodified OpenAI ChatGPT Linux ARM64 binary on Galaxy Z Fold without root or VM.
- **Hardware Display Calibration**: Target window geometry pinned to `2448 × 1768` with scale factor `2.40` on the inner foldable AMOLED display (120Hz Snapdragon Adreno rendering).
- **Universal IME & Focus Architecture**: Architectural specification bridging Chromium text input focus (`input_method_auralinux` via IBus / CDP) directly to Android's `InputMethodManager.showSoftInput()` in LorieView.
- **`LEGAL.md`**: Complete legal compliance framework under EU Directive 2009/24/EC (Articles 5 & 6), US DMCA § 1201(f), GPL-3.0 wrapper licensing, and zero-binary-modification guarantees (Knox 0x0 preserved).
- **Public Release Assets**: Package of 4 viral media assets in `x_post_assets/` including live hardware screenshots and photorealistic device mockups.
- **Unified Standalone APK Architecture**: Roadmap and project specification for the standalone `FoldGPT` Android app unifying `LorieView`, PRoot orchestration, and single-click One UI launcher.

### Changed
- Updated `README.md` to reflect production verification on Samsung Galaxy Z Fold.
- Transitioned from QEMU virtualization to bare-metal PRoot native execution, eliminating emulation CPU overhead and restoring full GPU acceleration.
