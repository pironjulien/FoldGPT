#!/usr/bin/env bash
# Complete Bash features with bundled readline/termcap; two real NDK builds.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
project=$(cd "$here/../../.." && pwd)
prefix=${1:?Usage: build-bash.sh ANDROID_RUNTIME_PREFIX [NEW_PROJECT_DOWNLOAD_DIRECTORY]}
[[ $# -le 2 ]]
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
grep -qx 'Pkg.Revision = 29.0.14206865' "$ndk/source.properties"
mkdir -p "$project/downloads"
if [[ $# = 2 ]]; then
  work=$(realpath -m -- "$2")
  [[ "$work" = "$project/downloads/"* && ! -e "$work" ]]
  mkdir -p "$work"
else
  work=$(mktemp -d "$project/downloads/foldgpt-bionic-bash-XXXXXXXX")
fi
work=$(cd "$work" && pwd)
[[ "$work" = "$project/downloads/"* ]]
mkdir "$work/tmp"
export TMPDIR="$work/tmp" LC_ALL=C TZ=UTC
prepare_args=("$work/source" --prefix "$prefix")
if [[ -n "${FOLDGPT_BASH_INPUTS:-}" ]]; then
  prepare_args+=(--inputs "$FOLDGPT_BASH_INPUTS")
fi
python3 -B "$here/prepare-bash.py" "${prepare_args[@]}" > "$work/prepare.log" 2>&1
SOURCE_DATE_EPOCH=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["sourceDateEpoch"])' "$work/source/source-manifest.json")
export SOURCE_DATE_EPOCH
compiler="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang"
export CC="$compiler" CC_FOR_BUILD=cc
export AR="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-ar"
export RANLIB="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-ranlib"
export LDFLAGS='-pie -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384'
for pass in first second; do
  build="$work/$pass"
  mkdir "$build"
  cd "$build"
  export CFLAGS="-O2 -fPIE -ffile-prefix-map=$build=/foldgpt/bash-build -ffile-prefix-map=$work/source=/foldgpt/bash-source"
  {
    printf 'CC=%q\nCC_FOR_BUILD=%q\nCFLAGS=%q\nLDFLAGS=%q\nSOURCE_DATE_EPOCH=%q\n' "$CC" "$CC_FOR_BUILD" "$CFLAGS" "$LDFLAGS" "$SOURCE_DATE_EPOCH"
    printf '%q ' "$work/source/bash-5.3/configure" --host=aarch64-linux-android --build=x86_64-pc-linux-gnu \
      --prefix="$prefix" --enable-multibyte --without-bash-malloc --enable-progcomp \
      bash_cv_job_control_missing=present bash_cv_sys_siglist=yes \
      bash_cv_func_sigsetjmp=present bash_cv_unusable_rtsigs=no \
      ac_cv_func_mbsnrtowcs=no bash_cv_dev_fd=whacky bash_cv_getcwd_malloc=yes
    printf '\nmake -j %q\n' "${JOBS:-4}"
  } > "$build/command.sh.txt"
  "$work/source/bash-5.3/configure" --host=aarch64-linux-android --build=x86_64-pc-linux-gnu \
    --prefix="$prefix" --enable-multibyte --without-bash-malloc --enable-progcomp \
    bash_cv_job_control_missing=present bash_cv_sys_siglist=yes \
    bash_cv_func_sigsetjmp=present bash_cv_unusable_rtsigs=no \
    ac_cv_func_mbsnrtowcs=no bash_cv_dev_fd=whacky bash_cv_getcwd_malloc=yes \
    > "$build/configure.log" 2>&1
  make -j "${JOBS:-4}" > "$build/make.log" 2>&1
done
cmp "$work/first/bash" "$work/second/bash"
cp "$work/first/bash" "$work/libfoldgpt_bash.so"
cp "$work/first/config.h" "$work/first/config.log" "$work/"
cp "$ndk/source.properties" "$work/ndk-source.properties"
"$compiler" --version > "$work/compiler.txt"
python3 -B "$here/verify-bash-build.py" "$work" --prefix "$prefix" --ndk "$ndk"
printf 'Bionic Bash built twice and byte-verified; not device-tested: %s\n' "$work"
