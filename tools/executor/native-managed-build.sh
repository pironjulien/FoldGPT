#!/usr/bin/env bash
# Private native kernel tests and Android cross-build; no ADB or runtime change.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
work=$(mktemp -d /var/tmp/foldgpt-native-managed-build-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/sources" "$work/linux" "$work/android" "$work/evidence"
chmod 777 "$work/evidence"
cp "$repo"/tools/executor/native-managed-* "$work/sources/"
cp "$repo"/tools/executor/native-runner.c "$repo"/tools/executor/native-runner-seccomp.h \
   "$repo"/tools/executor/native-runner-memory-contract.h "$repo"/tools/executor/native_process_policy.py \
   "$repo"/tools/executor/native_files.py "$repo"/tools/executor/exec_server.py \
   "$repo"/tools/executor/policy_intent.py \
   "$repo"/tools/policy/managed_policy.py "$work/sources/"
# Execute the frozen Python closure, not potentially changing checkout files.
mkdir -p "$work/python/tools/executor" "$work/python/tools/policy"
cp "$work"/sources/{native-managed-test.py,native_process_policy.py,native_files.py,exec_server.py,policy_intent.py} \
   "$work/python/tools/executor/"
cp "$work/sources/managed_policy.py" "$work/python/tools/policy/"
uname -a > "$work/environment.txt"
gcc --version >> "$work/environment.txt"
"$toolchain/aarch64-linux-android35-clang" --version >> "$work/environment.txt"
for target in runner fixture; do
    gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/sources/native-managed-$target.c" -o "$work/linux/$target"
    "$toolchain/aarch64-linux-android35-clang" -std=c11 -O2 -Wall -Wextra -Werror -static \
        -Wl,-z,max-page-size=16384,-z,common-page-size=16384 "$work/sources/native-managed-$target.c" \
        -o "$work/android/libfoldgpt-native-managed-$target.so"
    readelf -h -l -d "$work/linux/$target" > "$work/linux/$target-elf.txt"
    "$toolchain/llvm-readelf" -h -l -d "$work/android/libfoldgpt-native-managed-$target.so" > "$work/android/$target-elf.txt"
done
python3 -B "$repo/tools/executor/native-runner-scudo-check.py" \
    --elf "$work/android/libfoldgpt-native-managed-fixture.so" --toolchain "$toolchain" \
    --output "$work/android/scudo"
if [ "$(id -u)" = 0 ]; then run=(runuser -u nobody --); else run=(); fi
"${run[@]}" python3 -B "$work/python/tools/executor/native-managed-test.py" --runner "$work/linux/runner" \
    --fixture "$work/linux/fixture" --evidence "$work/evidence/kernel.json" 2>&1 | tee "$work/tests.txt"
(cd "$work" && sha256sum sources/* linux/runner linux/fixture android/*.so > SHA256SUMS)
destination="$repo/downloads/native-managed/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Native managed evidence: %s\nAndroid compiled only.\n' "$destination"
