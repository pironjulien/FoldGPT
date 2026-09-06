#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
grep -qx 'Pkg.Revision = 29.0.14206865' "$ndk/source.properties"
compiler="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang"
for command in python3 curl sha256sum; do command -v "$command" >/dev/null; done
test -x "$compiler"
destination="$repo/downloads/native-python"
mkdir -p "$destination"
python3 -B "$repo/tools/executor/stage-android-python.py" fetch --inputs "$destination/inputs"
work=$(mktemp -d "$destination/build-XXXXXXXX")
python3 -B "$repo/tools/executor/stage-android-python.py" stage \
    --inputs "$destination/inputs" --output "$work"
cp "$repo/tools/executor/android-python-launcher.c" "$work/"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie \
    -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384 \
    '-Wl,-rpath,$ORIGIN' -Wl,--no-undefined \
    -I"$work/prefix/include/python3.14" "$work/android-python-launcher.c" \
    -L"$work/prefix/lib" -lpython3.14 \
    -o "$work/stage/jniLibs/arm64-v8a/libfoldgpt_python.so"
"$compiler" --version > "$work/compiler.txt"
cp "$ndk/source.properties" "$work/ndk-source.properties"
python3 -B "$repo/tools/executor/stage-android-python.py" inventory --output "$work"
printf 'Android Python build: %s\n' "$work"
