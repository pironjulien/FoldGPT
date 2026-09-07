# Native command runtime without PRoot — 7 September 2026

Status: **Bash and a CPython CLI cross-compiled and staged on the PC. Not installed
or executed on the phone. No managed Bionic command profile is validated yet.**
The two phone reboots remain unexplained; this work does not run their fixture,
diagnose their cause, or demonstrate that removing PRoot alone resolves them.

## Preferred route and measured work

Use APK-owned ARM64/Bionic Bash and Python for model commands, under the real
Android kernel and the original managed policy enforced by the native broker.
No PRoot, guest path tracer, VM, root, bootloader operation, Knox change or client
modification is required by this design. The launcher is **not** the sandbox.

The prototype sources are in `tools/executor/bionic-runtime/`:

- `build-bash.sh`, `prepare-bash.py`, `bash-inputs.json`: GNU Bash 5.3 plus the
  fifteen official GNU fixes to 5.3.15, each checked against the hash published
  in the current Termux recipe. Reviewed Termux Android path patches are retained
  under `termux-bash/`. The Android prefix is a required build argument.
- `python-cli.c`, `build-python-cli.sh`, `python-package.py`: a small CLI against
  official Android CPython 3.14.7. The pinned official archive supplies all 428
  compiler inputs (headers and libpython); their bytes are checked before build.
- `stage-runtime.py`: preserve the complete official Python library tree, place
  every ELF in `jniLibs/arm64-v8a/lib*.so`, and describe hash-exact aliases for
  Python's original module/library names. This produces a staging tree, not an
  APK, and makes no changes on Android.

Both builds used the existing NDK r29 `29.0.14206865`, target
`aarch64-linux-android35`, under unprivileged host UID 65534. This is a
cross-compilation toolchain on the PC; no VM or emulated CPU is proposed for the
phone runtime.

| Final retained artifact | Location | SHA-256 |
| --- | --- | --- |
| Bash executable | `/var/tmp/foldgpt-bionic-bash-CvPhLZfV/libfoldgpt_bash.so` | `42a96bb6614030d518d50b783b29700e2d4453a59b4cefbb3a94dcc93c2ae0b7` |
| Python CLI executable, after host CLI review | `/var/tmp/foldgpt-bionic-python-xTKxsi7N/libfoldgpt_python_cli.so` | `9ad7a3faeb4b9027126f64af8967b40c54c36c7791a5693df1122ca0715bac30` |
| Final staging manifest, including data hashes | `/var/tmp/foldgpt-bionic-stage-cli-fix-20260907/manifest.json` | `bae40a46899c72687e45b287363f2fcd62c990885e51ceed1e84185350c85837` |

Paths in this table belong to the existing `Ubuntu-24.04` build environment on
the PC. Earlier `foldgpt-bionic-python-*` and staging directories are intermediate
artifacts and are not the final candidate.

Observed from the final binaries and full staging inventory:

- Both CLI ELF files are AArch64 dynamic executables with
  `PT_INTERP=/system/bin/linker64`, 16 KiB-aligned LOAD segments, no writable and
  executable LOAD segment, and non-executable stacks. The build enables RELRO
  and immediate relocation.
- Bash is 1,439,432 bytes and needs only system `libc.so` and `libdl.so`.
  `config.h` retains job control, readline/history, process substitution,
  arrays, programmable completion and multibyte support. Bundled readline and
  termcap are compiled. The Termux username-completion patch reflects Android's
  lack of a conventional enumerable Unix account database; it is not a sandbox
  mechanism. Build warnings remain in upstream Bash; compilation is not a
  runtime feature test.
- Python uses the existing, independently authenticated official CPython binary.
  The new CLI implements the ordinary `-c`, `-m`, script and stdin entry path
  through `PyConfig` and `Py_RunMain`; `sys.executable` is the real APK executable.
  This preserves ordinary nested `subprocess([sys.executable, ...])` construction.
  A required build-time base home provides a deployment default even for `-I`,
  `-E` or a replaced environment. Ordinary `PYTHONHOME` remains effective when
  Python's parsed flags permit it. The current explicit deployment input is
  `/data/user/0/app.foldgpt/files/bionic/python`; other Android user/profile
  installations need their actual path supplied at build/deployment time.
- The CLI directly needs all four primary Python libraries and uses
  `DT_RUNPATH=$ORIGIN`. Eagerly loading them by their real SONAME is intended to
  keep extension dependencies available without injecting `LD_LIBRARY_PATH`
  into the model's environment. This is statically verified linkage; Android
  dlopen/alias behavior remains to be validated separately.
- The full staged runtime contains **79 unique ELF files, 21,501,672 bytes**,
  **81 original ELF-path aliases**, including **67 extension-module aliases**,
  and **2,447 data files, 48,737,595 bytes**. Data includes the official standard
  library and its tests. The only non-runtime native dependencies are Android
  `libc`, `libdl`, `liblog`, `libm` and `libz`.

### Independent portable CLI review

`verify-python-cli-host.py` compiles the actual launcher source against the PC's
CPython 3.12.3 and executes it under UID 65534. The first run caught a real bug:
`PyConfig_Read` does not finish path initialization, so assigning the fallback
home there also replaced an allowed `PYTHONHOME`. The source now honors that
variable only when the parsed `use_environment` setting permits it, otherwise
using the explicit deployment default. The failed evidence remains in
`/var/tmp/foldgpt-bionic-cli-host-mvuzktfd`.

After this correction all 16 real host checks pass, including Unicode argv,
binary stdin/stdout, separate stderr and exit status, stdin/script/module modes,
`-I/-E/-S/-B/-u`, alternate `PYTHONHOME`, nested execution with `env={}`, fork/wait,
three real Python unit tests, compileall, building a zipapp and executing it to
produce 42. Evidence is in `/var/tmp/foldgpt-bionic-cli-host-76q1im8q`.
Source SHA-256 is `8f796442e5ec0afe9777de234a5107a772429d549693b880e96d973605277544`.
The corrected source was then rebuilt for Android and restaged with a SHA-256
for each of the 2,447 data files as well as every ELF.

These checks validate portable launcher behavior on host CPython, not Android's
loader, Android's `_android_support` implementation, the managed policy, or a
model-created project. The ordinary phone acceptance test remains outstanding.

This is a concrete minimal *tool selection* for the existing Python acceptance
project: Bash plus Python with its complete official library. It is not a claim
that all 79 ELF files load during each command, or that this is the byte-minimum
Python distribution. A smaller import closure would not support arbitrary
future model scripts, so no artificial tiny runtime is presented as complete.

## Android's documented execution boundary

The primary Android 10 documentation states that untrusted apps targeting API
29 or later cannot directly `execve` files in their writable app home; binary
code should be packaged in the APK. This app currently targets API 37. Its
existing `useLegacyPackaging true` extracts `lib*.so` into the package-managed
native library directory. A PIE executable can use that filename and be started
there; its contents need not be a JNI library.

The new staging manifest describes aliases from ordinary names such as
`lib/python3.14/lib-dynload/_posixsubprocess...so` to authenticated files under
the current `nativeLibraryDir`. A future installer must establish these aliases
outside the command workspace, verify the target hashes and update them when
an APK update changes its install path. There is no second mutable copy of ELF
code in this proposed runtime. The filesystem broker must protect both the
native code and the extracted standard-library data from command mutations.

Termux's official execution documentation confirms that its normal execution is
native Android/Bionic, compiled with the NDK, using the existing kernel. It also
explicitly warns that its published packages are compiled for
`/data/data/com.termux/files`; copying them into `app.foldgpt` is not a correct
port. The current build therefore produces our Bash from source with an explicit
application prefix instead of copying an unrelated Termux installation.

CPython's primary Android documentation says subprocesses are possible but are
not officially supported by Android as a general desktop process environment.
The official package includes `_posixsubprocess`; its configured `HAVE_FORK` and
`HAVE_VFORK` are enabled. `multiprocessing`/System V IPC and the usual Unix account
database are not fully available in the official Android Python build. Those are
real compatibility boundaries, not resolved by repackaging.

## Required policy and path integration

Removing PRoot removes its path rewriting. The new environment must present
truthful physical Android paths to the model and the exact same project files
to the GUI. The broker must not rewrite the original permission context, cwd or
arbitrary argv strings merely to make `/workspace` appear successful. Any
existing guest view needs an explicit, verified mapping to this physical tree.

The current static native profile admits static programs and a fixed cwd. The
GNU derivative expects PRoot's path handling for several mutation cases. Neither
becomes a complete Bionic shell backend by swapping its executable filename.
The next implementation must explicitly cover:

1. Authenticated dynamic ELF/runtime admission and exact read/execute grants;
   the complete original managed file and network policy remains authoritative.
2. Native relative paths after `chdir`, and directory-relative operations. The
   broker must pin the caller's effective cwd/dirfd and resolve policy against
   the actual target. Reading a path string and then blindly continuing a
   mutable syscall would not be an acceptable replacement.
3. Existing inode validation and `SECCOMP_ADDFD_FLAG_SEND` for allowed opens;
   brokered mkdir/unlink/rename and protected metadata/subtree semantics.
   Preserve explicit DENY handling and fail truthfully where unsupported.
4. The normal process-tree ownership, cancellation, reaping, output limits and
   memory/resource contract. An address-space limit is not an aggregate RSS
   limit. This route must not reuse the GNU profile's permissions for a PRoot
   tracer: model commands need no `ptrace` or `process_vm_*` permission.
5. Startup observation without continuous tracing of model commands. The current
   native runner briefly uses ptrace to attest exec startup; eliminating that
   bootstrap too would require another truthful startup protocol and separate
   validation, not merely suppressing the reported tracer field.

These are outstanding engineering/validation requirements. No current artifact
claims that the managed Bionic backend is already integrated or safe on the
Samsung kernel that rebooted.

## Comparison with a direct GNU/glibc loader

A glibc dynamic loader is native machine code, and its documented direct mode
can launch a GNU ELF with `--library-path` without PRoot. It is therefore a
technical candidate, not a VM. It also does not supply a Linux filesystem tree.

For the existing unmodified GNU rootfs, a single direct loader invocation is
insufficient: subsequent `execve` calls use each program's `PT_INTERP`, typically
`/lib/ld-linux-aarch64.so.1`, which is not installed in Android's global root.
Scripts may require `/bin/bash`, and glibc programs expect Unix `/etc`, locale,
NSS, resolver, certificate and data paths. Bionic cannot simply satisfy glibc's
ABI dependencies.

A separately maintained glibc port could rebuild/relocate every tool with an
explicit application interpreter path, immutable APK-owned loader, appropriate
runtime paths and validated syscall compatibility. An app-private alias to that
immutable loader is a design to investigate; it has not been tested on this
device and is not a supported guarantee. Direct loader invocation also changes
observable process identity (`/proc/self/exe`, auxv and related fields), so it
must not be silently advertised as ordinary direct exec semantics.

This larger glibc relocation and compatibility surface makes the NDK/Bionic route
the preferred first implementation for model commands. The existing GUI's GNU
runtime is a distinct component and is not modified by these prototypes.

## Git, Node and native build tools

Current Termux primary recipes retained under `bionic-runtime/research/` show:

| Tool | Native port evidence | Remaining work here |
| --- | --- | --- |
| Git 2.55.0 | Maintained Bionic recipe with curl, expat, iconv, OpenSSL, PCRE2 and zlib; shell/helpers have explicit prefix paths | Cross-build and APK-package the dependency/helper closure, configure CA/DNS/path behavior and validate real repositories under the original file policy |
| Node LTS 24.18.0 | Maintained Android/ARM64 cross-build; OpenSSL, c-ares, ICU, SQLite, zlib and libc++; bundled libuv to address Android loader semantics | Port dependencies and patches, retain ICU/JS data, validate child_process and module loading; native addons introduce their own executable-code deployment |
| Compilers/build tools | Native Android tools can themselves be APK-owned executables | Building an ELF file in a workspace and directly running it is still subject to Android's app-home exec restriction; shipping the compiler alone does not resolve this |

Python source, shell scripts and JavaScript can be interpreted by admitted
APK-owned interpreters. A universal developer environment that runs newly built
native code still needs an explicit durable deployment/execution design. Do not
claim this boundary is fixed by renaming files, reducing targetSdk, disabling
SELinux, faking a sandbox, or switching off the original policy.

No calendar estimate for the full port is justified by this limited experiment.
The measured work already accomplished is two real cross-builds and a complete
hash-checked Python staging tree. Git/Node/toolchain integration and the dynamic
managed backend have not been built here. The retained Node recipe itself notes
roughly two hours per architecture for its build; this is an upstream maintainer
observation, not a promise about this workstation or total integration time.

## Primary sources consulted

- [Android app-home execute restrictions](https://developer.android.com/about/versions/10/behavior-changes-10#execute-permission), read in the integrated browser.
- [NDK: other build systems and Autoconf cross-compilation](https://developer.android.com/ndk/guides/other_build_systems), read in the integrated browser.
- [Termux execution environment](https://github.com/termux/termux-packages/wiki/Termux-execution-environment), read in the integrated browser, including native Bionic, fixed-prefix and app-home execution sections.
- [Termux Bash recipe](https://github.com/termux/termux-packages/blob/master/packages/bash/build.sh), blob `f00e7e5e1db03495b8b064bdcdbfbfbdc60a2183`, plus the retained adjacent path patches.
- [Termux Python recipe](https://github.com/termux/termux-packages/blob/master/packages/python/build.sh), blob `5c3b8d2f8b52bc84c21fcb463735301bcd759c40`.
- [Termux Git recipe](https://github.com/termux/termux-packages/blob/master/packages/git/build.sh), blob `f3be7d87939e5b8ea9f6c5273c72495cfae280c6`.
- [Termux Node LTS recipe](https://github.com/termux/termux-packages/blob/master/packages/nodejs-lts/build.sh), blob `2ac240058fa3b09169e368714e00a014dd90a62e`.
- [CPython Android deployment](https://github.com/python/cpython/blob/v3.14.7/Doc/using/android.rst), [platform availability](https://github.com/python/cpython/blob/v3.14.7/Doc/library/intro.rst), [actual stream initialization](https://github.com/python/cpython/blob/v3.14.7/Lib/_android_support.py) and [PyConfig](https://github.com/python/cpython/blob/v3.14.7/Doc/c-api/init_config.rst); official retained sources/package inspected locally.
- [glibc dynamic loader manual](https://man7.org/linux/man-pages/man8/ld.so.8.html), direct invocation, dependency search and `$ORIGIN`, read in the integrated browser.

No phone commands, security-setting changes, client modifications or incident
reproducer were performed for this research/build work.
