#!/usr/bin/env bash
# Snapshot, build and verify actual nonroot native FD streaming; cross-build Bionic.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-file-streams-XXXXXXXX)
chmod 755 "$work"
compiler=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang
mkdir -p "$work/package/tools/executor" "$work/package/tools/policy"
for name in native-file-handle.c native_file_streams.py test_native_file_streams.py \
    native-files.c native_files.py test_native_files_live.py exec_server.py policy_intent.py test_policy_intent.py; do
    cp "$repo/tools/executor/$name" "$work/package/tools/executor/"
done
cp "$repo/tools/policy/managed_policy.py" "$work/package/tools/policy/"
cp "$repo/tools/executor/native-file-streams-build.sh" "$work/"
for helper in native-file-handle native-files; do
    gcc -std=c11 -O2 -Wall -Wextra -Werror -static \
        "$work/package/tools/executor/$helper.c" -o "$work/$helper"
done
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -static \
    -Wl,-z,max-page-size=16384,-z,common-page-size=16384 \
    "$work/package/tools/executor/native-file-handle.c" -o "$work/libfoldgpt_file_handle.so"
readelf -h -l -d "$work/libfoldgpt_file_handle.so" > "$work/android-elf.txt"
gcc --version > "$work/compilers.txt"
"$compiler" --version >> "$work/compilers.txt"
if [ "$(id -u)" = 0 ]; then
    run=(runuser -u nobody --)
else
    run=()
fi
cd "$work/package"
"${run[@]}" id > "$work/test-identity.txt"
"${run[@]}" env FOLDGPT_NATIVE_FILES="$work/native-files" FOLDGPT_NATIVE_FILE_HANDLE="$work/native-file-handle" \
    python3 -B -m unittest tools.executor.test_native_file_streams tools.executor.test_native_files_live \
    tools.executor.test_policy_intent -v 2>&1 | tee "$work/tests.txt"
cd "$work"
find package -type f -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
sha256sum native-file-handle native-files libfoldgpt_file_handle.so >> SHA256SUMS
destination="$repo/downloads/native-file-streams/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
cp -a "$work" "$destination"
printf 'Native file streaming evidence: %s\n' "$destination"
