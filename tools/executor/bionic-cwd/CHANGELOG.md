# Changelog

## 2026-09-07

- Add an actual libc `chdir` shim using mediated readable directory acquisition
  followed by `fchdir`, without a raw `chdir` syscall or cancellation points.
- Add nonroot host kernel checks and an Android/Bionic ARM64 shared-library build.
  Android execution and official application integration are not claimed.
- Pass four actual native supervisor composition tests covering Bash/Python cwd,
  denied directory access, reserved preload, removed preload and bad attestation.
- Package the shim in our Shizuku transport and verify its fixed installed APK
  path/digest before launch and backend construction, without a caller-selected
  absolute package path or a shell-writable preload deployment.
