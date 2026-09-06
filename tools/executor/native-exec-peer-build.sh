#!/usr/bin/env bash
# Linux execution plus Android cross compilation only; no phone or APK.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
export LC_ALL=C TZ=UTC
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]
for command in gcc python3 readelf sha256sum; do command -v "$command" >/dev/null; done
grep -qx 'Pkg.Revision = 29.0.14206865' "$ndk/source.properties"
work=$(mktemp -d /var/tmp/foldgpt-exec-peer-build-XXXXXXXX)
# The disposable non-root test user needs to traverse this build directory.
# It contains public source/binaries; private fixture data is elsewhere, 0700.
chmod 755 "$work"
mkdir "$work/sources"
cp "$repo/tools/executor/native-exec-peer-probe.c" "$repo/tools/executor/native-abc-probe.c" \
   "$repo/tools/executor/native-exec-peer-build.sh" "$repo/tools/executor/native-exec-peer-proof.md" "$work/sources/"
uname -a > "$work/environment.txt"
gcc --version >> "$work/environment.txt"
"$toolchain/aarch64-linux-android35-clang" --version >> "$work/environment.txt"
cat /proc/sys/kernel/yama/ptrace_scope > "$work/yama-before.txt"
gcc -std=c11 -O2 -static -Wall -Wextra -Werror "$work/sources/native-exec-peer-probe.c" -o "$work/native-exec-peer-linux"
"$toolchain/aarch64-linux-android35-clang" -std=c11 -O2 -static -Wall -Wextra -Werror \
  -Wl,-z,max-page-size=16384,-z,common-page-size=16384 \
  "$work/sources/native-exec-peer-probe.c" -o "$work/native-exec-peer-android-arm64"
readelf -h -l -d "$work/native-exec-peer-linux" > "$work/linux-elf.txt"
"$toolchain/llvm-readelf" -h -l -d "$work/native-exec-peer-android-arm64" > "$work/android-elf.txt"
python3 - "$work" <<'PY'
import json, struct, sys
from pathlib import Path
root = Path(sys.argv[1])
results = []
for name, machine, minimum in [("native-exec-peer-linux", 62, 4096), ("native-exec-peer-android-arm64", 183, 16384)]:
    data = (root / name).read_bytes()
    if data[:6] != b"\x7fELF\x02\x01": raise SystemExit("Expected ELF64 little-endian: " + name)
    h = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    if h[0] != 2 or h[1] != machine: raise SystemExit("Unexpected ELF type/machine: " + name)
    loads, stacks = [], []
    for index in range(h[9]):
        typ, flags, offset, address, _, filesz, memsz, align = struct.unpack_from("<IIQQQQQQ", data, h[4] + index*h[8])
        if typ in (2, 3): raise SystemExit("Static probe unexpectedly has dynamic table/interpreter: " + name)
        if typ == 1:
            if align < minimum or offset % minimum != address % minimum or flags & 3 == 3:
                raise SystemExit("Invalid LOAD alignment or writable executable LOAD: " + name)
            loads.append({"offset":offset,"address":address,"flags":flags,"alignment":align})
        if typ == 0x6474e551: stacks.append(flags)
    if not loads or not stacks or any(flags & 1 for flags in stacks): raise SystemExit("Missing LOAD or non-executable stack: " + name)
    results.append({"name":name,"machine":machine,"static":True,"loads":loads,"execution":"Linux only" if machine == 62 else "not executed"})
(root / "elf-verification.json").write_text(json.dumps(results,indent=2)+"\n")
PY
if [ "$(id -u)" = 0 ]; then
  command -v runuser >/dev/null
  runuser -u nobody -- "$work/native-exec-peer-linux" /var/tmp 2>&1 | tee "$work/host-result.txt"
else
  "$work/native-exec-peer-linux" /var/tmp 2>&1 | tee "$work/host-result.txt"
fi
cat /proc/sys/kernel/yama/ptrace_scope > "$work/yama-after.txt"
cmp "$work/yama-before.txt" "$work/yama-after.txt"
(cd "$work" && sha256sum sources/* native-exec-peer-linux native-exec-peer-android-arm64 > SHA256SUMS)
destination="$repo/downloads/native-exec-peer/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$work" "$destination"
printf 'Linux exec/peer evidence: %s\nAndroid compiled only; no phone/APK/Termux used.\n' "$destination"
