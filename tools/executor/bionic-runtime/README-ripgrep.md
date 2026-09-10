# Native ripgrep and PCRE2 for FoldGPT

The pinned inputs are upstream ripgrep 15.2.0 and PCRE2 10.47, with Rust 1.97.0,
Android ARM64 API35 and NDK r29 (29.0.14206865). Preparation downloads and checks
the two archive hashes, preserves the upstream Cargo.lock and verifies every
vendored crate file against Cargo's registry checksums. Sources, licences,
archives, temporary files and caches remain under the project.

The upstream `HomebrewFormula -> pkg/brew` source alias is materialized as a
directory copy on Windows. Its exact name/target is authenticated by the pinned
archive and recorded in `source-manifest.json`; no source code patch is applied.

## Build

```powershell
python -B tools/executor/bionic-runtime/prepare-ripgrep.py `
  --output work/native-ripgrep-20260908/prepared-v2
python -B tools/executor/bionic-runtime/build-ripgrep-windows.py `
  --prepared work/native-ripgrep-20260908/prepared-v2 `
  --output work/native-ripgrep-20260908/build-v4 `
  --ndk C:/Users/julie/AppData/Local/Android/Sdk/ndk/29.0.14206865 `
  --ninja C:/Users/julie/AppData/Local/Android/Sdk/cmake/3.22.1/bin/ninja.exe `
  --msvc 'C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC/14.44.35207'
python -B tools/executor/bionic-runtime/verify-ripgrep-build.py `
  work/native-ripgrep-20260908/build-v4
python -B tools/executor/bionic-runtime/test-ripgrep-admission.py `
  --build work/native-ripgrep-20260908/build-v4 `
  --output work/native-ripgrep-20260908/admission-tests-v1
```

Output directories must be new. `prepare-ripgrep.py --inputs DIR` can reuse
previously acquired archives; all archive hashes are checked again. Once the
locked source closure has been prepared, Cargo compilation is offline.

The installed Windows compiler generates every Android binary. WSL's genuine
`pkg-config` 1.8.1 in `Ubuntu-24.04` is used only to resolve the generated PCRE2
metadata. The canonical Windows dispatcher passes simple unquoted distribution
and project paths because this machine's WSL invocation from `cmd` preserves
literal quotes around the distribution name. Paths with command metacharacters
or spaces are rejected before building. This host metadata helper neither runs
the Android binaries nor changes the phone's execution architecture.

## PCRE2/JIT linkage

The locked `pcre2-sys` 0.2.10 vendored build disables JIT on
`aarch64-linux-android`. The recipe therefore compiles upstream PCRE2 with CMake,
8/16/32-bit support, Unicode and JIT, then uses pcre2-sys's existing pkg-config
entry point. `PCRE2_SYS_STATIC=0` permits that entry point;
`PKG_CONFIG_ALL_STATIC=1` selects the independently compiled static PCRE2 library.
Actual Cargo build metadata must contain `cargo:rustc-link-lib=static=pcre2-8`.
No ripgrep feature is removed, and `--features pcre2` enables `rg -P`.

PCRE2's generated ARM instructions require instruction-cache synchronization.
Rust invokes the linker with `-nodefaultlibs`, which omits Clang's implementation
of `__clear_cache`. The recipe resolves the matching compiler-rt archive using
NDK Clang's `--print-libgcc-file-name` and explicitly supplies that real archive
to the Rust link. No substitute cache routine or interpreter-only fallback is
introduced. The toolchain record includes the archive's SHA256.

The upstream `release-lto` profile is used. Separate PCRE2, Cargo caches and
output directories produce two complete builds; both resulting executable
hashes must match byte for byte. `GIT_CEILING_DIRECTORIES` prevents the source
archive from accidentally embedding FoldGPT's enclosing Git commit.

## Admission and limits

`build.json` uses schema `foldgpt.bionic-ripgrep-build.v1`. It records source and
lock hashes, the current recipe, compiler identities, build evidence, actual
ELF properties and both output hashes. `verify-ripgrep-build.py` rechecks the
complete prepared source closure, current recipe, PCRE2 configuration and
Cargo linkage before checking both ELF copies and the staged bytes. Admission
also validates API35, target and NDK/Rust versions.

`runas-runtime/ripgrep-admission.py:production_ripgrep(build)` returns the exact
two executable byte strings plus production provenance. The output names are
`libfoldgpt_rg.so` and `libfoldgpt_pcre2_jit_probe.so`; they are AArch64 PIE
executables named for Android native-library packaging. Both require the
Android system loader, 16KiB LOAD alignment, immediate binding, RELRO, an NX
stack and system-only dynamic dependencies. They have no RUNPATH.

`ripgrep-notices.txt` collects the upstream and vendored dependency licence
notices for inclusion with the APK. Its bytes are part of build evidence.

The separate Rust standard-library and NDK notices are admitted by
`runas-runtime/ripgrep-notices.py` against the reviewed
`runas-runtime/ripgrep-toolchain-notices.json` pins. Native staging requires
`--ripgrep-toolchain-notices work/native-ripgrep-20260908/toolchain-notices`
whenever `--ripgrep-build` is selected. The original 15-file capture manifest
has SHA256 `48228a450f06e98d36efed235e4c4a79b3befb644d3f331fba5e22fafa321294`.

The stage and package include these 15 notices under
`assets/notices/ripgrep-toolchain/`, plus a normalized asset manifest without
host installation paths. The qualification records the capture hash, canonical
pin hash, asset-manifest hash, toolchain versions, file count and total length.
Package assembly rechecks the captured source bytes. APK verification checks
the complete notice asset closure against canonical pins, including rejection
of missing/extra files and self-rehashed modified notices. Candidates without
native rg continue to verify without these optional assets.

This documentation addition does not alter the frozen rg build recipe or any
runtime/executable inventory. The r24b stage/package use the exact r24 admission
binary because `runtime-inventory.h` remains byte-identical (SHA256
`7ca9ba3333c5ed9244bfca999a610d6b67d36522377456937a8b7d4955405d1a`).
The new outputs are
`downloads/native-ordinary-uid-20260908/production-stage-r24b` and
`downloads/native-ordinary-uid-20260908/production-package-r24b`; r24 is retained.

Host qualification does not execute Android code. The standalone JIT probe
must subsequently run on the phone and successfully compile and directly
execute JIT code for Unicode letters, lookbehind and a backreference. Zero JIT
code size, interpreter fallback or a wrong match produces a nonzero exit code.
Actual `rg -P`, ordinary search, ignore rules, JSON, stdin and error/exit codes
must also pass production/device qualification before the integration is
described as working on Android.

Failed preparation/build directories are preserved as diagnostic evidence.
They do not constitute admitted artifacts and cannot replace a successful
`build.json` with matching source, recipe and double-build evidence.
