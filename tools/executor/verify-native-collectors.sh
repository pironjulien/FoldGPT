#!/usr/bin/env bash
# Read retained actual host/Android evidence; no device or runtime execution.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-native-collectors-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/sources" "$work/evidence"
chmod 777 "$work/evidence"
for name in collect-native-executor.py collect-native-processes.py \
    test_collect_native_executor.py test_collect_native_processes.py verify-native-collectors.sh; do
    cp "$repo/tools/executor/$name" "$work/sources/"
done
if [ "$(id -u)" = 0 ]; then run=(runuser -u nobody --); else run=(); fi
"${run[@]}" python3 -B "$work/sources/test_collect_native_processes.py" \
    --current "$repo/downloads/native-process/foldgpt-native-process-build-XyjPqBoX" \
    --legacy-pass "$repo/downloads/native-process/android-1a54dd8c/collected-pass-reviewed-20260906-r2" \
    --legacy-failure "$repo/downloads/native-process/android-f3079b8e/collected-failure-20260906" \
    --v2-failure "$repo/downloads/native-process/android-dec1eece/collected-failure-v2-children" \
    --evidence "$work/evidence/lifecycle-integrity.json" 2>&1 | tee "$work/lifecycle-tests.txt"
"${run[@]}" python3 -B "$work/sources/test_collect_native_executor.py" \
    --current "$repo/downloads/native-executor/foldgpt-native-executor-t5do5Qb3" \
    --children-failure "$repo/downloads/native-executor/android-dec1eece/failure-children" \
    --shield-failure "$repo/downloads/native-executor/android-23c8555b/failure-shield" \
    --evidence "$work/evidence/composite-integrity.json" 2>&1 | tee "$work/composite-tests.txt"
(cd "$work" && sha256sum sources/* evidence/* > SHA256SUMS)
destination="$repo/downloads/native-executor/$(basename "$work")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Native collector integrity evidence: %s\n' "$destination"
