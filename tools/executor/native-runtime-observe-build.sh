#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-runtime-observe-XXXXXXXX)
chmod 755 "$work"
compiler=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang
cp "$repo/tools/executor/native-runtime-observe.c" "$work/"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/native-runtime-observe.c" -o "$work/native-runtime-observe"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -static \
    -Wl,-z,max-page-size=16384,-z,common-page-size=16384 \
    "$work/native-runtime-observe.c" -o "$work/libfoldgpt-runtime-observe.so"
(cd "$work" && sha256sum native-runtime-observe.c native-runtime-observe libfoldgpt-runtime-observe.so > SHA256SUMS)
destination="$repo/downloads/native-files/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Observer build: %s\n' "$destination"
