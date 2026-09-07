#!/usr/bin/env bash
# PC-only compile and real nonroot tests. No ADB or Android build/deployment.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
runner=${1:?Usage: native-bootstrap-files-test.sh ACTUAL_HOST_BIONIC_SUPERVISOR}
test -x "$runner"
work=$(mktemp -d /var/tmp/foldgpt-bootstrap-files-XXXXXXXX)
chmod 755 "$work"
mkdir -p "$work/package/tools/executor/bionic-supervisor" "$work/package/tools/policy"
cp "$repo/tools/executor/"*.py "$work/package/tools/executor/"
cp "$repo/tools/executor/bionic-supervisor/"*.py "$work/package/tools/executor/bionic-supervisor/"
cp "$repo/tools/policy/"*.py "$work/package/tools/policy/"
cp "$repo/tools/executor/"{native-files.c,native-file-handle.c,test_bootstrap_paused_helper.c} "$work/"
for package in tools tools/executor tools/policy; do : > "$work/package/$package/__init__.py"; done
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/native-files.c" -o "$work/native-files"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/native-file-handle.c" -o "$work/native-file-handle"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/test_bootstrap_paused_helper.c" -o "$work/paused-helper"
if [ "$(id -u)" = 0 ]; then nonroot=(runuser -u nobody --); else nonroot=(); fi
cd "$work/package"
"${nonroot[@]}" env PYTHONPATH="$work/package" FOLDGPT_NATIVE_FILES="$work/native-files" \
  FOLDGPT_NATIVE_HANDLES="$work/native-file-handle" FOLDGPT_NATIVE_RUNNER="$runner" \
  FOLDGPT_NATIVE_FILE_HANDLE="$work/native-file-handle" \
  FOLDGPT_PAUSED_HELPER="$work/paused-helper" python3 -B -m unittest \
  tools.executor.test_native_bootstrap_files tools.executor.test_native_bootstrap_channel tools.executor.test_native_files_live \
  tools.executor.test_native_file_streams tools.executor.test_exec_server -v > "$work/tests.txt" 2>&1 || { cat "$work/tests.txt"; exit 1; }
(cd "$work" && find package -type f -print0 | sort -z | xargs -0 sha256sum > SOURCES.sha256)
(cd "$work" && sha256sum native-files native-file-handle paused-helper > BINARIES.sha256)
cat "$work/tests.txt"
printf 'Actual nonroot PC evidence: %s\n' "$work"
