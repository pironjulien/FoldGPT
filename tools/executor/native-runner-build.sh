#!/usr/bin/env bash
# Native Linux execution and static Android compile; no device or account.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
work=$(mktemp -d /var/tmp/foldgpt-native-runner-build-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/sources"
cp "$repo"/tools/executor/native-runner* "$work/sources/"
uname -a > "$work/environment.txt"
gcc --version >> "$work/environment.txt"
"$toolchain/aarch64-linux-android35-clang" --version >> "$work/environment.txt"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$repo/tools/executor/native-runner.c" -o "$work/native-runner"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$repo/tools/executor/native-runner-security-test.c" -o "$work/security-test"
"$toolchain/aarch64-linux-android35-clang" -std=c11 -O2 -Wall -Wextra -Werror -static \
    -Wl,-z,max-page-size=16384,-z,common-page-size=16384 "$repo/tools/executor/native-runner.c" -o "$work/native-runner-android-arm64"
readelf -h -l -d "$work/native-runner" > "$work/linux-elf.txt"
"$toolchain/llvm-readelf" -h -l -d "$work/native-runner-android-arm64" > "$work/android-elf.txt"
if [ "$(id -u)" = 0 ]; then
    run=(runuser -u nobody --)
else
    run=()
fi
"${run[@]}" env FOLDGPT_PARENT_PRIVATE=private-test python3 -B "$repo/tools/executor/native-runner-test.py" \
    --binary "$work/native-runner" --security-test "$work/security-test" | tee "$work/native-tests.txt"
"${run[@]}" python3 -B "$repo/tools/executor/native-runner-client-live-test.py" \
    --binary "$work/native-runner" | tee "$work/client-tests.txt"
(cd "$work" && sha256sum sources/* native-runner security-test native-runner-android-arm64 > SHA256SUMS)
destination="$repo/downloads/native-runner/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Native runner evidence: %s\nAndroid compiled only.\n' "$destination"
