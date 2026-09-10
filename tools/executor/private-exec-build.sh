#!/usr/bin/env bash
# Native non-root IPC proof and GNU ARM64 guest bridge cross-compilation.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-private-exec-XXXXXXXX)
chmod 755 "$work"
cp "$repo/tools/executor/private-exec-bridge.c" "$work/"
gcc -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie \
    -Wl,-z,relro,-z,now,-z,noexecstack "$work/private-exec-bridge.c" -o "$work/foldgpt-exec-bridge-host"
aarch64-linux-gnu-gcc -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie \
    -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384 \
    "$work/private-exec-bridge.c" -o "$work/foldgpt-exec-bridge-gnu-arm64"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static \
    "$repo/tools/executor/native-files.c" -o "$work/native-files"
gcc -std=c11 -O2 -Wall -Wextra -Werror -static \
    "$repo/tools/executor/native-file-handle.c" -o "$work/native-file-handle"
mkdir -m 700 "$work/evidence"
if [ "$(id -u)" = 0 ]; then
    chown nobody:nogroup "$work/evidence"
    run=(runuser -u nobody --)
else
    run=()
fi
cd "$repo"
"${run[@]}" env FOLDGPT_PRIVATE_TEST_PARENT="$work/evidence" \
    FOLDGPT_PRIVATE_BRIDGE="$work/foldgpt-exec-bridge-host" FOLDGPT_NATIVE_FILES="$work/native-files" \
    python3 -B -m unittest tools.executor.test_private_exec_broker -v 2>&1 | tee "$work/ipc-tests.txt"
mkdir -m 700 "$work/evidence/fixture"
python3 - "$work" <<'PY'
import json
from pathlib import Path
import sys
work = Path(sys.argv[1])
(work / "evidence/bridge-command.json").write_text(json.dumps([str(work / "foldgpt-exec-bridge-host")]) + "\n")
PY
if [ "$(id -u)" = 0 ]; then
    chown nobody:nogroup "$work/evidence/fixture"
fi
"${run[@]}" python3 -I -S -B "$repo/tools/executor/private_exec_fixture.py" \
    --helper "$work/native-files" --handle-helper "$work/native-file-handle" --evidence "$work/evidence/fixture" \
    --bridge-command-file "$work/evidence/bridge-command.json" | tee "$work/fixture-output.json"
readelf -h -l -d -V "$work/foldgpt-exec-bridge-gnu-arm64" > "$work/guest-bridge-elf.txt"
gcc --version > "$work/compilers.txt"
aarch64-linux-gnu-gcc --version >> "$work/compilers.txt"
sha256sum "$work"/foldgpt-exec-bridge-* "$work/native-files" > "$work/SHA256SUMS"
destination="$repo/downloads/private-exec/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
cp -a "$work" "$destination"
printf 'Private executor transport proof: %s\n' "$destination"
