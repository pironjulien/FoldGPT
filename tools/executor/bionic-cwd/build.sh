#!/usr/bin/env bash
# Host execution only; Android compilation/ELF inspection, never adb.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-bionic-cwd-XXXXXXXX)
chmod 755 "$work"
mkdir "$work/source" "$work/test-workspace"
cp "$repo/tools/executor/bionic-cwd/"{cwd.c,exports.map,test.c,test-supervisor.py,check-elf.py,build.sh,README.md,CHANGELOG.md} "$work/source/"
compiler=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang
common=(-std=c11 -O2 -Wall -Wextra -Werror -fPIC -fvisibility=hidden -fstack-protector-strong -D_FORTIFY_SOURCE=2
    -shared -Wl,--as-needed,--no-undefined,-z,relro,-z,now,-z,noexecstack
    -Wl,--version-script="$work/source/exports.map" -Wl,-soname,libfoldgpt_bionic_cwd.so)
gcc "${common[@]}" "$work/source/cwd.c" -o "$work/libfoldgpt_bionic_cwd.host.so"
"$compiler" "${common[@]}" -Wl,-z,max-page-size=16384,-z,common-page-size=16384 \
    "$work/source/cwd.c" -o "$work/libfoldgpt_bionic_cwd.so"
gcc -std=c11 -O2 -Wall -Wextra -Werror "$work/source/test.c" -o "$work/test-host"
python3 -B "$work/source/check-elf.py" "$work/libfoldgpt_bionic_cwd.so" > "$work/android-elf.json"
readelf -h -l -d -Ws "$work/libfoldgpt_bionic_cwd.host.so" > "$work/host-elf.txt"
"${compiler%/*}/llvm-readelf" -h -l -d -Ws "$work/libfoldgpt_bionic_cwd.so" > "$work/android-elf.txt"
"${compiler%/*}/llvm-nm" -D --defined-only "$work/libfoldgpt_bionic_cwd.so" > "$work/android-exports.txt"
python3 - "$work/android-exports.txt" <<'PY'
from pathlib import Path
import sys
symbols = [line.split()[-1] for line in Path(sys.argv[1]).read_text().splitlines() if line.strip()]
assert symbols == ['chdir'], symbols
PY
gcc --version > "$work/compilers.txt"
"$compiler" --version >> "$work/compilers.txt"
if [ "$(id -u)" = 0 ]; then
    chown nobody:nogroup "$work/test-workspace"
    run=(runuser -u nobody --)
else
    run=()
fi
"${run[@]}" id > "$work/test-identity.txt"
"${run[@]}" env -u LD_PRELOAD "$work/test-host" baseline "$work/test-workspace" 2>&1 | tee "$work/host-baseline.txt"
"${run[@]}" env LD_PRELOAD="$work/libfoldgpt_bionic_cwd.host.so" \
    "$work/test-host" shim "$work/test-workspace" 2>&1 | tee "$work/host-shim.txt"
(cd "$work" && sha256sum source/* > SOURCES.sha256)
(cd "$work" && sha256sum *.so test-host > BINARIES.sha256)
destination="$repo/downloads/bionic-cwd/$(basename "$work")"
python3 - "$work" "$destination" <<'PY'
from pathlib import Path
import hashlib
import shutil
import sys
source, target = map(Path, sys.argv[1:])
target.mkdir(parents=True, exist_ok=False)
for path in sorted(source.rglob('*')):
    if path.is_relative_to(source / 'test-workspace'):
        continue
    if path.is_symlink():
        raise ValueError('Unexpected source alias')
    output = target / path.relative_to(source)
    if path.is_dir():
        output.mkdir()
    else:
        shutil.copyfile(path, output)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(output.read_bytes()).digest():
            raise OSError('Transferred artifact hash mismatch')
print(f'Frozen PC-only build: {target}')
PY
printf 'Host native library: %s\nAndroid library compiled, not device-tested: %s\n' \
    "$work/libfoldgpt_bionic_cwd.host.so" "$work/libfoldgpt_bionic_cwd.so"
