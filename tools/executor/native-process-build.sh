#!/usr/bin/env bash
# Isolated native lifecycle kernel tests and ARM64 cross-build. No ADB/Gradle.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
work=$(mktemp -d /var/tmp/foldgpt-native-process-build-XXXXXXXX)
chmod 755 "$work"
mkdir -p "$work/sources" "$work/linux" "$work/android" "$work/evidence" \
    "$work/python/tools/executor" "$work/python/tools/policy" "$work/abi"
chmod 777 "$work/evidence"
for name in native-managed-runner.c native-managed-filter.h native-managed-fixture.c \
    native-runner.c native-runner-seccomp.h native-runner-memory-contract.h \
    native-process-fixture.c native_processes.py native_process_policy.py \
    native_environment.py native_environment_unicode.py \
    native_files.py native-files.c exec_server.py policy_intent.py native-managed-test.py \
    test_native_processes_live.py native-process-build.sh native-process-lifecycle.md native-process-fd-abi.c; do
    cp "$repo/tools/executor/$name" "$work/sources/"
done
cp "$repo/tools/policy/managed_policy.py" "$work/sources/"
cp "$work"/sources/{native_processes.py,native_process_policy.py,native_environment.py,native_environment_unicode.py,native_files.py,exec_server.py,policy_intent.py,native-managed-test.py,test_native_processes_live.py} "$work/python/tools/executor/"
cp "$work/sources/managed_policy.py" "$work/python/tools/policy/"
uname -a > "$work/environment.txt"
gcc --version >> "$work/environment.txt"
"$toolchain/aarch64-linux-android35-clang" --version >> "$work/environment.txt"
for pair in runner:native-managed-runner fixture:native-process-fixture acquisition-fixture:native-managed-fixture files-helper:native-files fd-abi:native-process-fd-abi; do
    name=${pair%%:*}; source=${pair#*:}
    gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/sources/$source.c" -o "$work/linux/$name"
    "$toolchain/aarch64-linux-android35-clang" -std=c11 -O2 -Wall -Wextra -Werror -static \
        -Wl,-z,max-page-size=16384,-z,common-page-size=16384 "$work/sources/$source.c" \
        -o "$work/android/libfoldgpt-native-process-$name.so"
    readelf -h -l -d "$work/linux/$name" > "$work/linux/$name-elf.txt"
    "$toolchain/llvm-readelf" -h -l -d "$work/android/libfoldgpt-native-process-$name.so" > "$work/android/$name-elf.txt"
done
sysroot="$ndk/toolchains/llvm/prebuilt/linux-x86_64/sysroot/usr/include"
cp "$sysroot/linux/memfd.h" "$work/abi/ndk-linux-memfd.h"
cp "$sysroot/linux/fcntl.h" "$work/abi/ndk-linux-fcntl.h"
cp "$sysroot/asm-generic/fcntl.h" "$work/abi/ndk-asm-generic-fcntl.h"
cp "$sysroot/sys/mman.h" "$work/abi/ndk-sys-mman.h"
cp "$sysroot/sys/pidfd.h" "$work/abi/ndk-sys-pidfd.h"
"$work/linux/fd-abi" > "$work/abi/host-observed.json"
python3 -B - "$work/python" "$work/abi/host-observed.json" <<'PY'
import json, sys
sys.path.insert(0, sys.argv[1])
from tools.executor.native_processes import NATIVE_FD_ABI
with open(sys.argv[2]) as source:
    assert json.load(source) == dict(NATIVE_FD_ABI), "Compiled UAPI and Python libc binding ABI differ"
PY
python3 -B "$repo/tools/executor/native-runner-scudo-check.py" \
    --elf "$work/android/libfoldgpt-native-process-fixture.so" --toolchain "$toolchain" --output "$work/android/scudo"
if [ "$(id -u)" = 0 ]; then run=(runuser -u nobody --); else run=(); fi
"${run[@]}" python3 -B "$work/python/tools/executor/native-managed-test.py" --runner "$work/linux/runner" \
    --fixture "$work/linux/acquisition-fixture" --evidence "$work/evidence/acquisition.json" 2>&1 | tee "$work/acquisition-tests.txt"
"${run[@]}" python3 -B "$work/python/tools/executor/test_native_processes_live.py" --runner "$work/linux/runner" \
    --fixture "$work/linux/fixture" --files-helper "$work/linux/files-helper" \
    --evidence "$work/evidence/lifecycle.json" 2>&1 | tee "$work/lifecycle-tests.txt"
(cd "$work" && sha256sum sources/* abi/* linux/runner linux/fixture linux/acquisition-fixture linux/files-helper linux/fd-abi android/*.so > SHA256SUMS)
destination="$repo/downloads/native-process/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Native lifecycle evidence: %s\nAndroid compiled only.\n' "$destination"
