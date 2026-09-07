#!/usr/bin/env bash
# Complete Bash features with bundled readline/termcap; NDK cross-build only.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
prefix=${1:?Usage: build-bash.sh ANDROID_RUNTIME_PREFIX}
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
grep -qx 'Pkg.Revision = 29.0.14206865' "$ndk/source.properties"
work=$(mktemp -d /var/tmp/foldgpt-bionic-bash-XXXXXXXX)
python3 -B "$here/prepare-bash.py" "$work/source" --prefix "$prefix" > "$work/prepare.log" 2>&1
compiler="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang"
export CC="$compiler" CC_FOR_BUILD=cc
export AR="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-ar"
export RANLIB="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-ranlib"
export CFLAGS='-O2 -fPIE'
export LDFLAGS='-pie -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384'
cd "$work/source/bash-5.3"
./configure --host=aarch64-linux-android --build=x86_64-pc-linux-gnu \
  --prefix="$prefix" --enable-multibyte --without-bash-malloc --enable-progcomp \
  bash_cv_job_control_missing=present bash_cv_sys_siglist=yes \
  bash_cv_func_sigsetjmp=present bash_cv_unusable_rtsigs=no \
  ac_cv_func_mbsnrtowcs=no bash_cv_dev_fd=whacky bash_cv_getcwd_malloc=yes \
  > "$work/configure.log" 2>&1
make -j "${JOBS:-4}" > "$work/make.log" 2>&1
cp bash "$work/libfoldgpt_bash.so"
cp config.h config.log "$work/"
cp "$ndk/source.properties" "$work/ndk-source.properties"
"$compiler" --version > "$work/compiler.txt"
"$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf" \
  -h -l -d "$work/libfoldgpt_bash.so" > "$work/elf.txt"
sha256sum "$work/libfoldgpt_bash.so" > "$work/SHA256SUMS"
printf 'Bionic Bash cross-compiled, not device-tested: %s\n' "$work"
