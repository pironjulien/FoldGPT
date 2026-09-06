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

Four local source fixes are applied only to extracted snapshots:

- `proot-string-header.patch` includes `<string.h>` for existing `strcmp` and
  `memset` calls. No compiler diagnostics are disabled.
- `proot-shmat-errno.patch` propagates the real `libandroid_shmat_fd` errno
  through the helper protocol. Previously its libc `-1` return became guest
  `EPERM` regardless of the error. The Fold's stale-segment regression failed
  with `EPERM` before the patch and passes with the actual `EINVAL` afterwards.
- `proot-kill-on-exit-sigterm.patch` lets a launcher cancel a PRoot session
  started with `--kill-on-exit` using SIGTERM. It uses the existing SIGQUIT
  tracee-termination path and lets the event loop reap the tracees before the
  tracer exits. SIGTERM is blocked across the initial tracee fork until its PID
  and the handler exist; the guest receives the launcher's original signal mask.
  Children whose automatic ptrace attachment was still queued during cancellation
  are also killed before resuming guest work. Sessions without `--kill-on-exit`
  keep upstream's SIGTERM-ignore behavior. This permits Android's public
  `Process.destroy()` followed by actual process completion, without reflecting
  a PID or forcibly killing the tracer. Guest processes receive SIGKILL, as in
  upstream's existing `--kill-on-exit` cleanup: cancellation is not a filesystem
  rollback or graceful completion of a package installation.
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

Before adopting a new build, execute the Android startup, loader, shared-memory
and guest command checks on the supported device and repeat the existing
runtime acceptance tests. Static ELF verification cannot prove compatibility
with Samsung's kernel, the guest filesystem, Landlock, GPU or Codex execution.

## Android adoption on 6 September 2026

The independent build with the original header, shmat-errno and tmpdir fixes is packaged in the
development APK. Under the actual Android Zygote application UID, five checks
pass: two pristine Debian hardlink groups, execution of pristine Debian Perl,
SysV shared memory across fork and a second attach, guest-created hardlinks,
and Java-provisioned PRoot hardlinks. The shared-memory check also verifies
detach, removal and refusal of a stale identifier. It does not claim complete
SysV IPC compatibility or an IPC security boundary. ARM32's loader is packaged
and statically checked; the device execution checks use ARM64.

The installed APK SHA-256 is
`d8b7b9b8d453cdf1db28e504c496a217f04c618a8485a891eb907c852c286dcc`.
Its real installed five-library hashes match the build manifest. The existing
client restarts and its CDP GPU report still selects Adreno 840 through
ANGLE/Zink/Turnip, with composition and rasterization enabled. This is not a
fresh install, a repeat of all GPU tests, or a complete protected executor.
Local evidence is retained in the ignored directory
`downloads/install/native/android-adoption-6928768071979500215`; sources,
notices and recipe accompany `foldgpt-native-P5tRdGlG` in the same native
artifact directory. Debug/release compilation and release vital lint pass;
independent APK-content checks find 17 debug libraries and exactly 7 release
libraries. No binary release has been published.

## SIGTERM cancellation regression on 6 September 2026

Run `test-proot-sigterm.sh` as an actual nonroot Linux x86_64 user with the
host C toolchain, talloc development headers/library, Python 3, Git and Make.
It archives the same pinned PRoot commit into two isolated directories, applies
the two existing PRoot fixes to both and the SIGTERM fix only to the second,
then builds and runs the actual native binaries. Source, recipe snapshots,
compiler output, both executables, fixture output and hashes remain in the new
`/var/tmp/foldgpt-proot-sigterm-XXXXXXXX` directory. No Android files change.

All 22 cases passed under WSL UID 65534 in
`downloads/install/native/foldgpt-proot-sigterm-14h51rar`. They verify the
baseline refusal to terminate on SIGTERM, preservation of that behavior without
the option, SIGQUIT compatibility, SIGTERM with both default seccomp and
`PROOT_NO_SECCOMP`, and the normal command exit code. Real guest trees contain
background children, a session-detached grandchild and a great-grandchild that
ignore SIGTERM. Eight cases cancel while the native guest is forking further
children. Independent host `/proc` observations, subreaper waits and unchanged
heartbeat files establish that the observed descendants stop and are reaped.

Eight additional cases use a test-only preload to queue SIGTERM after the first
tracee fork, before the call returns its PID to PRoot. The injection targets the
blocked launch interval, not PRoot's earlier F2FS capability-probe fork. The
tests require the real cancellation-handler diagnostic and verify that guest
work never starts. This preload is only a host test fixture and is not packaged.

The tested patched host executable SHA-256 is
`a2cd97a9e1f6e6be2dc70c1357401335cfc89367aada635ac3d7788e48c9ce6c`;
the patch SHA-256 is
`a3e0726af6924d5fe4b5b4b54141afcfe224a670ca23481f6304e74e73a530f1`.
The subsequent canonical Android build is `foldgpt-native-5WtDOy0s`.
`ProotStorageProbeService` ran its original five storage/execution/shared-memory
checks plus public `Process.destroy()` against a real Debian shell, a detached
shell and its sleep child. All passed under Zygote UID 10412, `untrusted_app`,
inherited seccomp 2. Independent `/proc` start-identity checks found none of the
three descendants after tracer completion; the actual SIGTERM handler ran.
The new PRoot SHA-256 is
`7507fc16a7a1fa06e4c1baf0d54c8b17b3225ba128eae8eca4d316e5645f381c`.
The tested APK SHA-256 is
`7d5d376d90cf8ea56bcd1d69400410b5df20ae8e010613f125f71e100c8ef145`;
private evidence is in `downloads/install/native/android-sigterm-20260906`.
The client package's separate interrupted same-root recovery passed on the
host, as documented in `docs/install/inactive-client-install.md`. Android
installation recovery still needs its own integrated test. None of these
checks establishes a sandbox or covers unrelated untraced runtime helpers.
