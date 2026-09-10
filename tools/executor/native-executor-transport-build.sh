#!/usr/bin/env bash
# Frozen Linux nonroot composite + old file-transport regressions. No ADB/Gradle.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-native-executor-XXXXXXXX)
chmod 755 "$work"
mkdir -p "$work/sources" "$work/linux" "$work/python/tools/executor" "$work/python/tools/policy" "$work/evidence"
chmod 777 "$work/evidence"
for name in native-managed-runner.c native-managed-filter.h native-managed-fixture.c \
    native-runner.c native-runner-seccomp.h native-runner-memory-contract.h native-process-fixture.c \
    native_processes.py native_process_policy.py native_files.py native-files.c \
    native_environment.py native_environment_unicode.py \
    native_file_streams.py native-file-handle.c native_executor_backend.py \
    exec_server.py policy_intent.py private_exec_broker.py private-exec-bridge.c \
    test_native_processes_live.py test_private_exec_broker.py test_native_executor_transport.py \
    native_files_rpc_fixture.py native_executor_android_fixture.py native-executor-transport-build.sh; do
    cp "$repo/tools/executor/$name" "$work/sources/"
done
cp "$repo/tools/policy/managed_policy.py" "$work/sources/"
cp "$work"/sources/*.py "$work/python/tools/executor/"
mv "$work/python/tools/executor/managed_policy.py" "$work/python/tools/policy/"
uname -a > "$work/environment.txt"
gcc --version >> "$work/environment.txt"
python3 --version >> "$work/environment.txt"
for pair in runner:native-managed-runner fixture:native-process-fixture files-helper:native-files handle-helper:native-file-handle; do
    name=${pair%%:*}; source=${pair#*:}
    gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/sources/$source.c" -o "$work/linux/$name"
done
gcc -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie -Wl,-z,relro,-z,now,-z,noexecstack \
    "$work/sources/private-exec-bridge.c" -o "$work/linux/bridge"
if [ "$(id -u)" = 0 ]; then run=(runuser -u nobody --); else run=(); fi
set +e
"${run[@]}" python3 -I -S -B "$work/python/tools/executor/test_native_executor_transport.py" \
    --runner "$work/linux/runner" --fixture "$work/linux/fixture" --files-helper "$work/linux/files-helper" \
    --handle-helper "$work/linux/handle-helper" --bridge "$work/linux/bridge" --parent "$work/evidence" \
    --evidence "$work/evidence/composite.json" 2>&1 | tee "$work/composite-tests.txt"
composite=${PIPESTATUS[0]}
cd "$work/python"
"${run[@]}" env FOLDGPT_PRIVATE_TEST_PARENT="$work/evidence" FOLDGPT_PRIVATE_BRIDGE="$work/linux/bridge" \
    FOLDGPT_NATIVE_FILES="$work/linux/files-helper" python3 -B -m unittest tools.executor.test_private_exec_broker -v \
    2>&1 | tee "$work/file-regressions.txt"
files=${PIPESTATUS[0]}
set -e
printf 'composite=%s\nfile_regressions=%s\n' "$composite" "$files" > "$work/status.txt"
(cd "$work" && sha256sum sources/* linux/* evidence/composite.json > SHA256SUMS)
destination="$repo/downloads/native-executor/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Native composite transport evidence: %s\n' "$destination"
[ "$composite" = 0 ] && [ "$files" = 0 ]
