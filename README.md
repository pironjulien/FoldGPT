# FoldGPT

**Live showcase:** https://foldgpt.julienpironfr.chatgpt.site

FoldGPT is an experimental Android host for the official ChatGPT Linux ARM64 desktop client on a Galaxy Z Fold. It keeps the Android app in its own UID and launches the Linux desktop surface locally through the Android runtime.

## Current status

The repaired development APK has been exercised on a Galaxy Z Fold with the native executor selected. A real Codex request ran `python -c "print(2+2)"` and returned `4`; the runtime status was ready, direct native execution was selected, and no `EACCES` appeared in the new runtime log. The phone reported verified boot `green`, a locked bootloader, and a zero Knox warranty bit during this check.

This is a development prototype. Fresh install, update behaviour, Remote, long background sessions, several simultaneous active discussions, and broad tool isolation still need qualification. Android process pressure is a known limit: Android reports a 32 phantom-process budget and one session can approach it. This project does not bypass Android process accounting or weaken device security.

The source deliberately excludes client credentials, browser profiles, Linux images, APKs, recovery archives, and private device evidence. The official client remains a separate dependency; this repository contains the host, runtime integration, build checks, and reproducible patches.

## Build

Requirements are JDK 21, Android SDK 37, Gradle 9.7.1, Python 3, ADB, and ARM64 native executor inputs. A candidate build must name a reviewed executor package; the build refuses an implicit or incomplete package and verifies the resulting APK before copying it.

```powershell
python tools/runtime/build-production-candidate.py --candidate r45 --package C:\path\to\executor-package
```

The package must contain `assets/` and `jniLibs/`. See [`config/android/executor-package.json`](config/android/executor-package.json) and [`tools/runtime/executor_package.py`](tools/runtime/executor_package.py). The pinned Termux:X11 and PRoot sources are declared in `.gitmodules`; the current X11 changes are recorded in [`recovery/submodules/termux-x11.patch`](recovery/submodules/termux-x11.patch).

## Contributing

Issues and pull requests are welcome. Maintainers review every change and retain merge control. Please read [`CONTRIBUTING.md`](CONTRIBUTING.md), avoid private logs or account data, and include a focused test or device evidence when changing runtime behaviour.

## Licence and boundary

The host wrapper is GPL-3.0-or-later; dependencies retain their own licences. FoldGPT is not an OpenAI, Samsung, or ChatGPT product. See [`LEGAL.md`](LEGAL.md) for the dependency and distribution boundary.
