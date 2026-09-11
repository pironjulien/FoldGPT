# Optional X11 diagnostic helper

`quiet_xext.c` exports `XMissingExtension` for the GNU/Linux ARM64 guest. It suppresses the repeated libXext missing-extension diagnostic; it does not implement an X11 extension or establish graphics compatibility. The session script loads it only if it is already installed under `/usr/local/lib/foldgpt`.

The source release does not ship the generated `libquiet_xext.so`. To reproduce it, supply LLVM Clang with an AArch64 linker (the Android NDK r29 toolchain was used during development):

```powershell
python tools/quiet_xext/build_quiet_xext.py --clang "$env:ANDROID_NDK_CLANG"
```

Set `ANDROID_NDK_CLANG` to the installed compiler executable, or pass that path directly to `--clang`. The C source has no headers or libc dependencies, so this build does not require a preconfigured Debian sysroot. Output defaults to the ignored `work/quiet-xext/libquiet_xext.so`; use `--output` for a different new path. The command builds the file and does not install it or modify a phone.
