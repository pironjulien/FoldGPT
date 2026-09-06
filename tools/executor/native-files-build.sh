#!/usr/bin/env bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-native-files-build-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/sources"
cp "$repo/tools/executor/"native-files*.c "$repo/tools/executor/"native_files.py "$work/sources/"
compiler=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$repo/tools/executor/native-files.c" -o "$work/native-files"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -static -Wl,-z,max-page-size=16384,-z,common-page-size=16384 \
    "$repo/tools/executor/native-files.c" -o "$work/libfoldgpt-native-files.so"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -static -Wl,-z,max-page-size=16384,-z,common-page-size=16384 \
    "$repo/tools/executor/native-files-android-test.c" -o "$work/libfoldgpt-native-files-test.so"
cd "$repo"
if [ "$(id -u)" = 0 ]; then run=(runuser -u nobody --); else run=(); fi
"${run[@]}" env FOLDGPT_NATIVE_FILES="$work/native-files" python3 -B -m unittest \
    tools.executor.test_exec_server tools.executor.test_native_files_live -v 2>&1 | tee "$work/tests.txt"
(cd "$work" && sha256sum sources/* native-files *.so > SHA256SUMS)
destination="$repo/downloads/native-files/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Build and host test evidence: %s\nAndroid execution still requires the debug service.\n' "$destination"
