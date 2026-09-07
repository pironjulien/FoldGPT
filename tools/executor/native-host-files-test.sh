#!/usr/bin/env bash
# Snapshot and exercise actual helpers as nonroot; no Android execution.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
runner=${1:?Usage: native-host-files-test.sh ACTUAL_HOST_BIONIC_SUPERVISOR}
test_module=${2:-tools.executor.test_native_host_files}
case "$test_module" in
  tools.executor.test_native_host_files|tools.executor.test_native_host_files_channel) ;;
  *) printf 'Unsupported qualification module: %s\n' "$test_module" >&2; exit 2 ;;
esac
test -x "$runner"
work=$(mktemp -d /var/tmp/foldgpt-host-files-XXXXXXXX)
chmod 755 "$work"
mkdir -p "$work/package/tools/executor/bionic-supervisor" "$work/package/tools/policy" "$work/results"
cp "$repo/tools/executor/"*.py "$work/package/tools/executor/"
cp "$repo/tools/executor/bionic-supervisor/"*.py "$work/package/tools/executor/bionic-supervisor/"
cp "$repo/tools/policy/"*.py "$work/package/tools/policy/"
cp "$repo/tools/executor/"{native-files.c,native-file-handle.c,test_bootstrap_paused_helper.c} "$work/"
cp "$repo/tools/executor/native-host-files-test.sh" "$work/"
cp "$runner" "$work/runner"
printf '%s\n' "$runner" > "$work/RUNNER-SOURCE.txt"
printf '%s\n' "$test_module" > "$work/TEST-MODULE.txt"
for package in tools tools/executor tools/policy; do : > "$work/package/$package/__init__.py"; done
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/native-files.c" -o "$work/native-files"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/native-file-handle.c" -o "$work/native-file-handle"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$work/test_bootstrap_paused_helper.c" -o "$work/paused-helper"
(cd "$work" && find package -type f -print0 | sort -z | xargs -0 sha256sum > SOURCES.sha256)
(cd "$work" && sha256sum *.c native-host-files-test.sh >> SOURCES.sha256)
(cd "$work" && sha256sum native-files native-file-handle paused-helper runner > BINARIES.sha256)
if [ "$(id -u)" = 0 ]; then
    chown nobody:nogroup "$work/results"
    nonroot=(runuser -u nobody --)
else
    nonroot=()
fi
cd "$work/package"
"${nonroot[@]}" env PYTHONPATH="$work/package" FOLDGPT_NATIVE_FILES="$work/native-files" \
  FOLDGPT_NATIVE_HANDLES="$work/native-file-handle" FOLDGPT_NATIVE_RUNNER="$work/runner" \
  FOLDGPT_PAUSED_HELPER="$work/paused-helper" FOLDGPT_HOST_FILE_OBSERVATIONS="$work/results/observations.json" \
  python3 -B -m "$test_module" > "$work/tests.txt" 2>&1 || {
    cat "$work/tests.txt"; printf 'Failed host file authority evidence: %s\n' "$work"; exit 1;
  }
cat "$work/tests.txt"
printf 'Actual nonroot host file authority evidence: %s\n' "$work"
