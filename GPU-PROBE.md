# Isolated Adreno GPU validation

These developer tools test an alternative graphics driver without replacing
Debian system Mesa or modifying the official desktop client. The probes do not
restart the desktop. Selecting a new session driver requires a coordinated
restart. Driver installation is not yet part of the Android runtime installer.

## Current checkpoint

The installed session now selects `mesa-26.2.2-foldgpt4` and Xlorie SHA-256
`94b09f06b8f9508be587266f5400d5a360fc787c69788310a2fa2b411783369b`.
Vulkan/timestamps, GLX/Present/pixmap tests and a visible File-menu check passed
on 6 September. The targeted calibrated-timestamp and GLX refresh errors are
absent in the new session log. The memfd helper uses positive tmpfs/ashmem
identification; ENOTTY is no longer treated as proof of ordinary memory.
See [the device evidence and limits](docs/verification-2026-09-06.md).

## Earlier checkpoints and diagnosis

The installed session selects `mesa-26.2.2-foldgpt3`. On 6 September 2026 at
02:05 UTC, the official client's local GPU report identified:

```text
ANGLE (Mesa, zink Vulkan 1.4(Adreno (TM) 840 (MESA_TURNIP)), OpenGL 4.6 ... Mesa 26.2.2)
gpu_compositing=enabled rasterization=enabled webgl=enabled
```

Vulkan, GLX, X11 Present and texture-from-pixmap pixel tests pass. The full
desktop is visible with `xfwm4` running. A clean initial frame does not establish
presentation reliability: opening the search menu produced intermittent
corruption on the Android surface while the client's own screenshot was clean.
Touching the actual search input opened Samsung IME; leaving it closed IME.

The captured startup log had no GPU-process crash, but did have 208 calibrated
timestamp errors and 524 GLX refresh-query errors. These counts describe that
particular startup capture, not a sustained rate or a current health report.

`foldgpt4` is a **compiled, not device-validated candidate** with the timestamp
and RandR corrections below. USB disconnected before deployment. The build,
package and test scripts default to that candidate. `foldgpt-session.sh` still
selects the installed revision 3. Do not switch it before the new probes pass.
To repeat the older offscreen/texture tests, pass
`--prefix /opt/foldgpt-gpu/mesa-26.2.2-foldgpt3` to their Python launchers.

## Verified baseline, 2026-09-06

- The app UID can open `/dev/kgsl-3d0` for reading and writing without root.
- KGSL reports chip ID `0x44050a31`, 18 MiB GMEM, highest bank bit `0x10`,
  and UBWC mode `0x6`. Sysfs reports `Adreno840v2`.
- The running desktop previously reported Mesa 25.0.7 llvmpipe through ANGLE;
  that is CPU rendering, independent of the Android viewer's EGL rendering.
- Mesa 26.0.6 compiled with the KGSL backend loads but fails physical-device
  enumeration. Its KGSL code handles UBWC versions 1–4 only. The failure is
  reproducible; no device-ID override or success simulation is used.
- Mesa 26.2.2 contains upstream support for UBWC5/6 in
  `src/freedreno/vulkan/tu_knl_kgsl.cc`, and its device database includes this
  Adreno 840 chip. Its Vulkan probe passes on the real GPU.

## Successful runtime results

The following output was obtained under the FoldGPT Android application UID,
with the isolated `mesa-26.2.2-foldgpt2` prefix, without root or a desktop restart:

```text
GPU=Adreno (TM) 840 type=1 vendor=0x5143 device=0x44050a31 api=1.4.354
PASS: Adreno Vulkan queue submitted and completed; 64x64 offscreen pixels verified
OpenGL renderer=zink Vulkan 1.4(Adreno (TM) 840 (MESA_TURNIP)) version=4.6 (Compatibility Profile) Mesa 26.2.2 direct=1
PASS: offscreen Zink/Adreno clear and rasterized triangle pixels verified
```

The first unpatched GLX test failed with `DRI3 not available`, although the
X server advertises DRI3. Mesa's KGSL-only configuration selects `pseudo-drm`;
`glxext.c` queried DRI3 capabilities only inside `GLX_USE_DRM`, leaving the
capability field false on this path. `mesa-pseudodrm-dri3.patch` moves **only the
real server query** under `HAVE_X11_DRM`, which includes pseudo-DRM. The existing
capability check remains in effect. The kernel DRM device-opening path remains
unchanged. No device-ID override, `LIBGL_KOPPER_DRI2`, software fallback, or
Chromium GPU blocklist override was used to obtain these results.

An additional windowed test exposed a separate failure in the first build:
`SIGBUS`, PC `0x1`, with the caller at `wsi_create_buffer_blit_context`. X11 chose
DMA-BUF image parameters, while KGSL's pseudo-DRM build omitted libdrm and the
corresponding WSI DRM implementation. Release-build undefined behavior then
interpreted these parameters as CPU image parameters and called a bogus SHM
callback. `mesa-pseudodrm-wsi.patch` makes libdrm a real dependency for
X11/pseudo-DRM, compiling the actual WSI DMA-BUF functions. Kernel DRM support
is not falsely declared and no callback is disabled.

The corrected `foldgpt2` build also passed this real presentation test:

```text
stage=window-mapped
renderer=zink Vulkan 1.4(Adreno (TM) 840 (MESA_TURNIP))
stage=GPU-draw-completed
stage=swap-returned
stage=X-server-synchronized
stage=Present-completion-received
PASS: GPU buffer presented through X11; all window pixels verified
```

The test observes the actual X11 Present completion event on a separate
connection before reading every pixel from its own temporary 64 × 64 window.
A swap call alone is asynchronous and is insufficient evidence. These results
do not change the renderer of an already running desktop process.

## Source and build provenance

- Official archive: <https://archive.mesa3d.org/mesa-26.2.2.tar.xz>
- SHA-256: `eeb29ca7e56cfaa8e8a79538dcf834e3b18e501c31bef5145e959ea437cc4216`.
- Digest checked against Mesa's `docs/relnotes/26.2.2.rst` at official upstream
  main commit `86158b8c7467cadcd24f8a8cf02aa3bc748f7e3f`.
- Official release tag: `mesa-26.2.2`, commit
  `3281a69a8bfd9f997e91c15ed0e6290cae12dd32`.
- Two tracked Mesa corrections, for GLX capability queries and WSI build
  dependencies, described above. The
  official ChatGPT files and the installed Debian Mesa remain unchanged.
  Cross compiler: Ubuntu 24.04 ARM64 GCC/G++ 13.
  Meson: 1.12.0, in a project-local WSL venv.
- Target libraries are downloaded from signed Ubuntu arm64 package repositories
  and extracted into an isolated sysroot. They are not installed on Android.
  Dependency versions follow the configured Ubuntu repositories; this is a
  reproducible procedure, not a claim of byte-for-byte deterministic builds.
- Configuration: Turnip KGSL only, Zink Gallium, X11 GLX/EGL, release build,
  no LLVM, Rusticl, video codecs or other GPU drivers.

## Build and deploy

From `C:\Dev\ChatgptFold`, with Ubuntu-24.04 WSL and authorized ADB available:

```powershell
wsl --distribution Ubuntu-24.04 --user root --exec bash /mnt/c/Dev/ChatgptFold/tools/gpu/build-mesa.sh
python tools/gpu/deploy-test-prefix.py --serial <adb-serial>
python tools/gpu/inspect-kgsl.py --serial <adb-serial>
python tools/gpu/run-probes.py --serial <adb-serial>
```

`build-mesa.sh` invokes `prepare-build.sh`, which installs host build
dependencies, verifies the source archive, extracts it, and creates the pinned
Meson venv. WSL root is used for **host** package installation only. The phone
continues to use its ordinary application UID.

Outputs remain in ignored `downloads/gpu/`. The deployment script accepts only
archive members within `/opt/foldgpt-gpu/mesa-26.2.2-foldgpt4`, checks symlinks and archive
SHA-256 after ADB transfer, and refuses an existing destination. It validates and
hashes the exact byte snapshot subsequently transferred, so replacement by a
concurrent build cannot substitute another archive. Extraction uses a private
staging directory; the completed payload is renamed without replacing an
existing revision. Failure cleans only the validated staging directory. Mesa
source extraction likewise promotes a completed temporary directory. Host
regression tests cover archive replacement and transfer tampering. A real Linux
shell test also confirms that truncated extraction leaves no final revision,
retry succeeds and an existing revision remains intact. The revised Android
extraction transaction still awaits an on-device run.

Deployed test archive SHA-256:
`6eb8495f03fc262b543aaea02985a377812b1e49bb8d4bf3045a4cd01077449c`
(9,834,453 bytes). Subsequent builds may have different archive timestamps.

The verified process environment is:

```sh
VK_DRIVER_FILES=/opt/foldgpt-gpu/mesa-26.2.2-foldgpt2/share/vulkan/icd.d/freedreno_icd.aarch64.json
LD_LIBRARY_PATH=/opt/foldgpt-gpu/mesa-26.2.2-foldgpt2/lib
MESA_LOADER_DRIVER_OVERRIDE=zink
GALLIUM_DRIVER=zink
```

This selects libraries for a new diagnostic process only. A desktop-client
integration must preserve any existing required library paths, validate the
client's actual renderer through CDP, and test presentation separately.

## What a pass proves

`vulkan-clear-probe` requires an integrated Adreno/Turnip device, submits an
offscreen image clear and transfer, waits for a GPU fence, and compares all
64 × 64 RGBA pixels with the expected result. It rejects a software renderer.

`glx-clear-probe` creates an offscreen pbuffer on the existing X display, requires
a Zink/Adreno renderer, and verifies both an OpenGL clear and two rasterized
triangles covering the pbuffer. The triangle stage exercises real shader
compilation and drawing through Mesa's compatibility pipeline. No window is
shown and no prompt or user document is touched.

The Vulkan fence is bounded at five seconds; each process is bounded at
30 seconds. Neither probe demonstrates shader-heavy application performance,
display presentation, 120 FPS, battery cost, or hardware acceleration in the
separately running official client. Those require subsequent coordinated tests.

For the explicit, short-lived windowed presentation test:

```powershell
wsl --distribution Ubuntu-24.04 --exec bash /mnt/c/Dev/ChatgptFold/tools/gpu/build-present-probe.sh
python tools/gpu/run-presentation-probe.py --serial <adb-serial>
```

The window does not receive keyboard focus. Its X11 connection and temporary
executable are removed afterwards. The process is bounded at 30 seconds and
the Present-completion wait at five seconds. This is a functional test, not a
framerate benchmark.

## Integration and distribution limits

The EGL library is built, but the probes above validate Vulkan and GLX, not
Electron's particular EGL/ANGLE configuration. EGL's X11 code already queries
DRI3 under `HAVE_X11_DRM`; it does not have the first GLX-only guard defect.
The WSI dependency correction applies to both. The client backend has now been
inspected, as recorded above; reliable presentation across UI transitions still
requires further validation.

This test archive currently relies on the existing Debian runtime. It requires
at least GLIBC 2.38 and GLIBCXX 3.4.29; Debian 13 provides these, Debian 12 does
not. Zink dynamically loads `libvulkan.so.1`, even where ELF dependency listings
do not show it. The corrected build also requires Debian's `libdrm2`.

The archive is not yet a complete redistribution package: runtime dependency
checks and the full source/notice/provenance companion must be added before
shipping it as a standalone driver distribution. The upstream sources contain
component-specific notices; do not label the whole bundle with only a generic
MIT notice or copy the Ubuntu sysroot libraries into the Android package.

`tools/gpu/package-review-bundle.py` now collects a local review companion from
the exact candidate archive, verified pristine Mesa source archive, ordered
patches, FoldGPT build/probe sources and license notices. Run it in WSL/Linux
after `package-build.sh`. Its manifest inventories ten AArch64 ELF objects,
their dependencies and symbol versions; Zink's dynamic Vulkan-loader dependency
is also recorded. The highest required versions are GLIBC 2.38, GLIBCXX 3.4.29
and CXXABI 1.3.9. All twenty-one payload hashes were independently checked, and two
collection runs produced identical bytes. This is reproducible collection, not
a second compilation or a runtime dependency test. The bundle remains local
and explicitly marked as a candidate awaiting device validation.
The collector pins the independently inspected binary archive's SHA-256 as well
as the upstream source hash. A new build needs an explicit review and digest
update; passing the safe-extraction prefix check alone does not authorize
publication. Regressions reject an archive containing `auth.json` under an
otherwise allowed prefix and reject private bytes appended to the real candidate.
The imported archive validator is now included among the companion sources.

## Compositor texture import diagnosis

`glx-tfp-probe.c` creates a private X pixmap and GLX pbuffer, fills the pixmap
through X11, binds it through `GLX_EXT_texture_from_pixmap`, and reads the GL
texture. It does not create a visible window or touch the desktop client.

```powershell
wsl --distribution Ubuntu-24.04 --exec bash /mnt/c/Dev/ChatgptFold/tools/gpu/build-present-probe.sh
python tools/gpu/run-presentation-probe.py --serial <adb-serial> --probe tfp
```

With `foldgpt2`, the initial green pixmap produced `(0, 0, 0, 255)` instead of
`(0, 255, 0, 255)`. This reproduces the compositor's black texture independently
of Electron. Termux:X11's `dri3_screen_info_rec.fds_from_pixmap` is `FalseNoop`,
so exporting an X pixmap for GPU import fails. Mesa's `kopper_allocate_textures`
then allocates a fallback texture, but `kopper_update_tex_buffer` skips its
contents update whenever the GPU has DMA-BUF capability, regardless of whether
that particular pixmap was successfully imported. The server's pixmap-export
capability and the GPU's DMA-BUF capability are distinct.

`mesa-kopper-pixmap-import.patch` checks `drawable->image`, which identifies a
successful import, instead of the GPU-wide `screen->has_dmabuf` capability.
The existing X11 pixel-copy path now fills locally allocated textures. Revision
3 passed both initial green pixels and an update to red, then displayed the
official client with the compositor retained.

## Candidate corrections awaiting device validation

Upstream KGSL's `kgsl_device_get_gpu_timestamp` contains `UNREACHABLE`, although
calibrated timestamps are advertised. A direct `IOCTL_KGSL_PERFCOUNTER_READ`
of ALWAYSON returned `EPERM` under the app UID. The dedicated
`IOCTL_KGSL_READ_CALIBRATED_TIMESTAMPS` (request 0x60) **succeeded under that UID**:
DEVICE, MONOTONIC and MONOTONIC_RAW domains returned real values, with a
growing GPU counter and kernel-reported deviation of 52–625 ns in those samples.
`mesa-kgsl-calibrated-timestamps.patch` implements the existing Mesa callback
through this supported ioctl. Neither a timestamp nor a permission is simulated.

`vulkan-timestamp-probe.c` additionally requires a real command-buffer timestamp
query between two calibrations and compares GPU progression against
`CLOCK_MONOTONIC_RAW`, including reported uncertainty. This final Vulkan path
has compiled but has not run on the disconnected Fold. It is included in the
candidate archive:

```powershell
python tools/gpu/run-probes.py --serial YOUR_ADB_SERIAL --api timestamp
```

GLX's refresh query only used XF86VidMode, which this X server does not provide.
`mesa-glx-randr-rate.patch` reads active RandR CRTC modes instead when the legacy
query fails, preserving the exact rational rate. It returns failure for absent,
invalid or differing active rates; no fixed 60/120 value is invented. The
presentation probe now compares the GLX result against independent Xlib RandR
queries. The older revision 3 is expected to fail this new rate assertion.
The candidate and extended probe compile; their device result is pending.

The prepared `termux-x11-dmabuf-sync.patch` adds real `DMA_BUF_IOCTL_SYNC`
START/END calls around CPU access to imported buffer memory, including texture
upload. It distinguishes ordinary shared memory through ENOTTY and preserves
other errors. This addresses a missing coherency operation identified in the
presentation path; its effect on the observed artefacts is not yet proven.
The patch includes a new header and is kept separately from the pinned vendor
commit. The complete Xlorie build now passes using the official Linux NDK r29,
with an ext4 source tree to preserve case-sensitive header lookup. Its 1,986
exports match the earlier library and its LOAD segments have 16 KiB alignment.
The candidate APK compiles and its packaged library hash matches the built
library. On-device cache, rendering and JNI/lifecycle tests are still required.
See [the native build notes](tools/gpu/X11-BUILD.md).

```powershell
& tools/gpu/build-dmabuf-sync-probe.ps1
python tools/gpu/run-dmabuf-sync-probe.py --serial YOUR_ADB_SERIAL
```

The Android-native probe uses real shared memory and DMA-heap buffers; it does
not fabricate ioctl responses. Its NDK compilation passed. Sources compile
without root access to Android, and no OpenAI executable is modified.
