# Device checkpoint: 6 September 2026

This is development evidence, not a public APK release qualification.
Tests used the connected Samsung SM-F971B, Android API 37, app UID 10412,
without Android root or bootloader changes.

## Independent application

The separate `com.termux` and `com.termux.x11` packages were first disabled.
FoldGPT then restarted its own display, PRoot, Debian and official client.
All runtime processes belonged to `app.foldgpt`; its rootfs is private under
`files/debian` and the display library comes from the APK.

Both legacy packages were subsequently uninstalled for Android user 0 with
`-k`, retaining their private data. Their original base/split APKs were copied
to a local ignored backup and SHA-256 checked against the phone before removal.
Android reports `installed=false` for both. A subsequent FoldGPT APK update
and client restart succeeded. This does not claim the old private data was
deleted, or that the developer bootstrap is already a consumer installer.

A final package inventory found a third obsolete package:
`com.openai.chatgpt.launcher`, version 1.0, displayed as **FoldGPT**. Its
manifest and DEX match the old `launcher_apk` prototype, whose sole activity
opens `com.termux.x11.MainActivity`. It is not the official Android client.
The installed APK was backed up and compared against the device SHA-256
`e599075e5024a05303af1360d0f245d03c6b1bed99b9a53f4fdde9e6fd112bae`,
then removed for user 0 with `-k`. Android confirms `installed=false`.
Only `app.foldgpt` and the official `com.openai.chatgpt` remain installed for
this setup. FoldGPT reopened successfully; retained legacy data is not claimed
as reclaimed disk space.

The integrated display notification uses `foldgpt.display.v1`, importance 2,
no sound and the FoldGPT icon. Its actual Android notification flags include
`SILENT` and `ONLY_ALERT_ONCE`. The runtime notification remains available to
stop Linux. Disconnection and permission errors remain visible.

## Official command and independently verified files

The debug-only offline service launched the untouched official Codex CLI
0.153.4, SHA-256
`4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6`.
The actual Zygote app context reports Landlock ABI 6 and inherited seccomp 2.
The test masks the compatibility preload in its guest process.

Initialization and `command/exec` both succeeded using an empty temporary
profile, no credentials and no model request. Four mediated opens created or
appended ordinary files. Attempts to change protected metadata and outside
files were refused. The native parent independently checked file bytes,
protected modes, absent forbidden files and descendant cleanup after completion.
Repeat runs also completed successfully.

Two startup requirements were identified directly: bounded `fchmod` on the
test's own scratch objects, and Rust's unnamed Unix `SOCK_SEQPACKET` process
startup channel plus ARM64 `sendto`. Internet socket creation remains refused.
No mutable syscall request is resumed with seccomp `CONTINUE`.

This fixture has read visibility over the guest and a fixed write policy;
it does not implement full Codex managed policies, arbitrary workspaces,
deny-read exceptions, general metadata operations or the production executor.
One run failed in PRoot temporary-directory setup; that intermittent failure
is retained as unresolved evidence, not converted into a success by retries.
The main graphical session still has the older compatibility shim and must
not be described as fully sandboxed.

## GPU and visible menus

Mesa 26.2.2 `foldgpt4` passed Vulkan submission/readback, calibrated timestamps,
GLX triangle pixels, X11 Present completion/window pixels and updated
texture-from-pixmap sampling on the device. The reported display refresh rate
matches the active RandR mode; this is not measured application FPS.

The Xlorie DMA-BUF helper now positively distinguishes regular tmpfs/memfd and
legacy ashmem. Android can refuse the DMA-BUF ioctl on a memfd with `EACCES`;
that refusal no longer causes an ordinary memory buffer to fail. Actual DMA-BUF
exporter errors are still propagated. The standalone probe verified 16 cycles
each for ASharedMemory, memfd and the system DMA heap, plus error propagation.
That probe runs in `runas_app`, which is distinct from a Zygote service.

The complete Xlorie candidate SHA-256 is
`94b09f06b8f9508be587266f5400d5a360fc787c69788310a2fa2b411783369b`.
After installing it and selecting Mesa `foldgpt4`, the official client's
diagnostic interface confirms Adreno 840 composition/rasterization through
ANGLE, Zink and Turnip. The actual File menu was visually checked on the Fold:
labels, background and shadow render correctly. GLX/Present/pixmap tests pass
again with the integrated library. The former calibrated-timestamp and
`glXGetMscRateOML` errors are absent in that session log. Other nonfatal
messages remain, including missing optional XFree86-VidMode support; this is
not a claim of error-free logs, battery qualification or sustained 120 FPS.

## Remaining delivery gates

- Full native process/file executor integration and protected command tests
  through ordinary Desktop operations.
- Fresh Android installation, provisioning, keyring and recovery checks.
- Update/recovery path preserving the official client and user data.
- Automatic reopen after unfolding, actual Remote test and longer lifecycle,
  battery and thermal measurements.
- Complete corresponding-source obligations before binary distribution.
