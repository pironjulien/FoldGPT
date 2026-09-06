#!/usr/bin/env bash
# Compile debug-only native Android fixtures and execute the same fixed checks
# without privileges on Linux. Never package/install an APK or access ADB.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
compiler="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang"
work=$(mktemp -d /var/tmp/foldgpt-runner-android-check-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/sources" "$work/linux" "$work/android"
cp "$repo"/tools/executor/native-runner* "$work/sources/"
cp "$repo/android/app/src/debug/java/app/foldgpt/NativeRunnerProbeService.java" "$work/sources/"
for target in native-runner native-runner-android-fixture native-runner-android-probe; do
    case "$target" in
        native-runner) output=libfoldgpt-native-runner.so ;;
        native-runner-android-fixture) output=libfoldgpt-native-runner-fixture.so ;;
        native-runner-android-probe) output=libfoldgpt-native-runner-probe.so ;;
    esac
    gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/sources/$target.c" -o "$work/linux/$output"
    "$compiler" -std=c11 -O2 -Wall -Wextra -Werror -static \
        -Wl,-z,max-page-size=16384,-z,common-page-size=16384 "$work/sources/$target.c" -o "$work/android/$output"
    "$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf" -h -l "$work/android/$output" > "$work/android/$output.elf.txt"
done
python3 -B "$work/sources/native-runner-scudo-check.py" \
    --elf "$work/android/libfoldgpt-native-runner-fixture.so" \
    --toolchain "$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin" --output "$work/scudo-evidence"
uname -a > "$work/environment.txt"
gcc --version >> "$work/environment.txt"
"$compiler" --version >> "$work/environment.txt"
run=()
if [ "$(id -u)" = 0 ]; then run=(/usr/sbin/runuser -u nobody --); fi
"${run[@]}" "$work/linux/libfoldgpt-native-runner-probe.so" /var/tmp "$work/linux" | tee "$work/native-fixture-tests.txt"
(cd "$work" && sha256sum sources/* linux/* android/* scudo-evidence/* > SHA256SUMS)
destination="$repo/downloads/native-runner/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Evidence: %s\nAndroid compiled only; no APK build, package mutation, or device test.\n' "$destination"
