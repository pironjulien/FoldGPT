# Native X11 build for FoldGPT

Run `bash tools/gpu/build-x11.sh` from WSL Ubuntu 24.04. It builds the current
`vendor/termux-x11` C sources, including local correction headers, with the
official Linux NDK **29.0.14206865 / r29** for **Android ARM64, API 24**. API 24
matches the upstream library minimum; the FoldGPT app itself requires API 30.

The script writes source staging, source archives and artifacts under
`C:\Dev\ChatgptFold\downloads\gpu\x11`. Native compilation uses a separate
`/var/tmp/foldgpt-x11-*` directory on WSL's Linux filesystem. It never installs an
APK or overwrites `android/native/x11`. Upstream CMake applies its dependency
patches only to the native snapshot. Their presence is checked explicitly because
upstream's patch helper does not propagate patch failures.

The versioned `termux-x11-dmabuf-sync.patch` is applied or verified in the source
copy with `-p5`. A clean public clone therefore does not depend on dirty vendor
files. UTF-8 text line endings are normalized in the copy, with original hashes
preserved. NTFS snapshot I/O uses Windows Python when available under WSL, then a
tar transfer moves the prepared sources to ext4 for compilation.

## Host setup

Install the Linux build dependencies in WSL:

```sh
apt-get update
apt-get install --no-install-recommends cmake ninja-build bison flex python3 gcc g++ patch pkg-config unzip curl
```

The official archive is
`https://dl.google.com/android/repository/android-ndk-r29-linux.zip`.
The Android SDK repository metadata identifies its size as **783549481 bytes**
and SHA-1 as `87e2bb7e9be5d6a1c6cdf5ec40dd4e0c6d07c30b`. The verified archive's
SHA-256 is `4abbbcdc842f3d4879206e9695d52709603e52dd68d3c1fff04b3b5e7a308ecf`.

Keep the archive at
`C:\Dev\AndroidSdk-Linux\downloads\android-ndk-r29-linux.zip`, verify its hash,
and extract it with Linux `unzip` into `/opt/foldgpt`. `ANDROID_NDK_HOME` and
`FOLDGPT_NDK_ARCHIVE` can override those locations. The NDK needs a case-sensitive
filesystem: its headers include both `xt_RATEEST.h` and `xt_rateest.h`. Ordinary
case-insensitive NTFS extraction is invalid. WSL's Linux filesystem preserves
both filenames and executable permissions. Source compilation itself also needs
case sensitivity: otherwise Bionic's `<xlocale.h>` can incorrectly select
libX11's `Xlocale.h` from an earlier include directory.

## Evidence and limits

Each artifact directory contains the stripped and unstripped libraries, ELF and
export reports, exact compiler commands, source hashes, upstream and dependency
commits, local tracked-source diff, the FoldGPT patch and its hash, NDK provenance
and build logs. `source-prepared.tar` and `source-built.tar.gz` preserve the
prepared and compiled sources, including correction headers and upstream patches.

The script rejects sources changed during the build. It verifies an AArch64
shared object, its `JNI_OnLoad` entry point and Android 16 KiB load alignment, and
rejects obvious GNU/Linux runtime dependencies. Upstream registers native methods
dynamically rather than exporting Java-named functions. `SOURCE_DATE_EPOCH` and
mapped build paths reduce accidental timestamp/path differences. Repeated-build
bit-for-bit equality is a separate check; do not claim it solely because the
script completes.

A successful build is **not a device test**. Before shipping, confirm the final
patch/source hashes, library dependencies, Android page alignment, JNI exports
and which library the APK actually packages, then test rendering on the Fold.

The separate Windows `build-dmabuf-sync-probe.ps1` extracts its helper header
directly from the complete new-file hunk in the same tracked patch. It validates
the hunk and records header/patch hashes; it does not require a patched vendor
checkout. Its output was also compiled from a minimal tree without `vendor`.

## Verified candidate, 2026-09-06

The candidate built from upstream commit
`9df8b767645aa0d0a2f2576767449df55b41962f` and FoldGPT patch SHA-256
`44cd67caa7d797496b2daa35e8665c6b0ed7e7895a9c49118f095bc29cee2866` is:

```text
downloads/gpu/x11/build-tVmp8dpU/artifact/libXlorie.so
SHA256 49032f62df55b5d17262ec70aa2746e1b475d3df8650cba7c5276e47648632fb
```

All 535 native build steps, including the final shared-library link, completed.
ELF verification confirmed AArch64, Android API 24 and 16 KiB load alignment.
Comparison with the previous upstream library found the same 1,986 exported
symbols and the same eight Android dependencies. Disassembly of `LorieBuffer_lock`
and `LorieBuffer_unlock` confirmed calls to `ioctl` with `DMA_BUF_IOCTL_SYNC`
(`0x40086200`), including retry and error handling. Evidence is retained beside
the candidate in `build-manifest.json`, `export-comparison.json`,
`dmabuf-disassembly.txt`, `elf-report.txt` and the build logs.

The build invocation initially stopped after linking because its verification
expected Java-named exports. The corrected verification block, which checks
`JNI_OnLoad`, was then executed against the completed artifact and passed. This
records the actual evidence without claiming an additional complete build run.
Clean upstream sources plus the versioned patch also reproduced the four
reviewed correction files exactly after text line-ending normalization.

These checks qualify a native build candidate. Device rendering, DMA-BUF runtime
behavior and performance still require validation on the Fold.
