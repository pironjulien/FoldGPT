#!/usr/bin/env bash
# Build the native helper and run the same complete RPC fixture without root.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-files-rpc-build-XXXXXXXX)
chmod 755 "$work"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static "$repo/tools/executor/native-files.c" -o "$work/native-files"
mkdir -m 700 "$work/evidence"
if [ "$(id -u)" = 0 ]; then
  chown nobody:nogroup "$work/evidence"
  run=(runuser -u nobody --)
else
  run=()
fi
"${run[@]}" python3 -I -S -B "$repo/tools/executor/native_files_rpc_fixture.py" \
  --helper "$work/native-files" --evidence "$work/evidence" | tee "$work/fixture-output.txt"
cd "$repo"
"${run[@]}" python3 -B -m unittest tools.executor.test_native_files_fixture_lifecycle -v 2>&1 | tee "$work/lifecycle-tests.txt"
(cd "$repo" && sha256sum tools/executor/native-files.c tools/executor/native_files*.py \
  tools/executor/exec_server.py tools/executor/policy_intent.py tools/policy/managed_policy.py) > "$work/SHA256SUMS"
destination="$repo/downloads/native-files-rpc/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
cp -a "$work" "$destination"
printf 'Native RPC evidence: %s\n' "$destination"
