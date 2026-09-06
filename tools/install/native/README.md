# Android runtime cross-build

This recipe builds PRoot, both matching loaders, talloc and android-shmem with
the Linux Android NDK. It needs no phone, ADB, SSH, Termux installation or emulator.
It does not change `vendor/proot`, `android/native` or the APK. Outputs remain
review candidates until a separate Android runtime validation and packaging step.

## Run

Prerequisites: Linux x86_64 (WSL Ubuntu 24.04 is supported), Git, Make, Python 3,
curl, tar, patch, sha256sum and the GPL-3 text in `/usr/share/common-licenses`.
The checked-out `vendor/proot` must have the pinned HEAD below. Local vendor
changes are not built: the source snapshot comes from `git archive` of that commit.

Install and verify the official Linux NDK r29 before running. The recipe checks
the installation revision, verifies the downloaded NDK archive SHA-256 again,
and records the actual compiler version and digest. The installed compiler is
trusted to come from that archive; the recipe does not reinstall the toolchain.

```powershell
wsl --distribution Ubuntu-24.04 --exec bash /mnt/c/Dev/ChatgptFold/tools/install/native/build-native.sh
```

Defaults are `/opt/foldgpt/android-ndk-r29` for `ANDROID_NDK_HOME` and
`/mnt/c/Dev/AndroidSdk-Linux/downloads/android-ndk-r29-linux.zip` for
`FOLDGPT_NDK_ARCHIVE`. Override those environment variables for another machine.
Target compilation is Android API 30, ARM64; PRoot's `-m32` target produces its
ARM32 loader using the same NDK toolchain.

All source extraction and compilation happen in a new
`/var/tmp/foldgpt-native-XXXXXXXX` directory on Linux ext4. The complete artifact
is copied to a new ignored `downloads/install/native/foldgpt-native-XXXXXXXX`.
Build directories are retained, including failures, for inspection. The recipe
never recursively removes existing files or overwrites a previous artifact.

## Sources and notices

| Component | Source | License |
| --- | --- | --- |
| PRoot | `termux/proot@7266fb3e8516535682f5a9c8f3a7e70f6506eddb` | GPL-2.0-or-later |
| talloc | Samba talloc 2.4.3 | LGPL-3.0-or-later for the built library and libreplace headers |
| android-shmem | `termux/libandroid-shmem@7f0bd7e25dbdd146265aff7c6a890029e374622d`, tag v0.7 | BSD-3-Clause |

Archives are retained under `sources/`, patches and the complete recipe under
`build/recipe/`, and the relevant license texts under `notices/`. The talloc and
android-shmem archive hashes also match the official Termux package recipes at
`termux/termux-packages@90081438daf30a6b46f6745daff6966dc71cb7bc`.

| Archive | SHA-256 |
| --- | --- |
| `https://dl.google.com/android/repository/android-ndk-r29-linux.zip` | `4abbbcdc842f3d4879206e9695d52709603e52dd68d3c1fff04b3b5e7a308ecf` |
| `https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz` | `dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd` |
| `https://codeload.github.com/termux/libandroid-shmem/tar.gz/refs/tags/v0.7` | `1e5ff8459bc0a8c229dd8a94b27d119987e09ef3414331c2b5ebfff20b98e867` |

No OpenAI client, user data or credential is included. This build record does not
replace review of the complete APK's distribution obligations. In particular,
retain corresponding sources, modifications and build materials with any binary
distribution and preserve the applicable LGPL replacement/relinking rights.

Two local source fixes are applied only to extracted snapshots:

- `proot-string-header.patch` includes `<string.h>` for existing `strcmp` and
  `memset` calls. No compiler diagnostics are disabled.
- `android-shmem-tmpdir.patch` replaces Termux's unavailable `_PATH_TMP` macro
  with the process's absolute private `TMPDIR`. It checks path length and returns
  filesystem errors rather than looping on errors other than `EEXIST`. The
  current Android runtime already sets this variable before launching PRoot.
  `IPC_PRIVATE` remains unchanged. A caller that needs keyed segments must
  provide the same private directory to the cooperating processes.

## Configuration and verification

`configure-talloc.py` runs real Android compile/link checks for headers,
declarations, functions, types and compiler attributes. It retains the generated
C programs, output ELF files, compiler diagnostics, command lines and JSON
results. It never executes Android code and does not supply fabricated runtime
test answers to Waf. Bionic's C99 `snprintf`/`vsnprintf` semantics are the one
explicit platform contract recorded separately as `runtime_tested: false`.
Required checks preserve talloc's random header initialization using `getauxval`
and a constructor; the configuration does not turn that feature off.

The upstream PRoot Makefile retains its feature probes and builds both loaders.
`PROOT_UNBUNDLE_LOADER=/foldgpt/runtime` and
`PROOT_WITH_LIBANDROID_SHMEM=1` preserve the existing runtime's functional options.
Compiler output records the exact PRoot source commit. The NDK links every
runtime ELF with 16 KiB page alignment, stack protection, fortification and
non-executable stacks; dynamically linked outputs also use RELRO/NOW.

The five packaged files are named:

```text
runtime/arm64-v8a/libproot.so
runtime/arm64-v8a/libproot-loader.so
runtime/arm64-v8a/libproot-loader32.so
runtime/arm64-v8a/libtalloc.so
runtime/arm64-v8a/libandroid-shmem.so
```

The `.so` suffix is Android packaging convention; PRoot is an executable and its
loaders are static executables. `libtalloc.so` retains SONAME `libtalloc.so.2`;
the runtime must expose the alias **`libtalloc.so.2 -> libtalloc.so`**, as the
current service already does. Loaders must remain matched to their PRoot build.

`verify-elf.py` rejects an unexpected artifact set, wrong machine/type,
misaligned LOAD segments, writable executable LOADs, executable or absent GNU
stacks, invalid executable entry points, an unexpected interpreter, embedded
RPATH/RUNPATH, undeclared dependencies or wrong SONAMEs. Checks remain active
under Python optimization. PRoot must depend on the packaged talloc and shmem;
all other dependencies must be explicitly allowed Android system libraries.

`manifest.json` records sizes, SHA-256 values, ELF segments, dependencies,
source pins, required alias, NDK provenance and recipe/license digests. Unstripped
ELFs are kept in `debug/`; build logs and generated feature configuration remain
under `build/`. This manifest inventories a local build; it is not a signed
release descriptor and does not establish runtime behavior or bit-for-bit
reproducibility.

Before adopting these files, execute the Android startup, loader, shared-memory
and guest command checks on the supported device and repeat the existing
runtime acceptance tests. Static ELF verification cannot prove compatibility
with Samsung's kernel, the guest filesystem, Landlock, GPU or Codex execution.
