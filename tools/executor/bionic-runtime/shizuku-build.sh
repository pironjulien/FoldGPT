#!/usr/bin/env bash
set -euo pipefail
umask 077
here=$(cd -- "$(dirname -- "$0")" && pwd)
build=$(mktemp -d /var/tmp/foldgpt-shizuku-probe-XXXXXXXX)
python3 - "$here/shizuku-qualification.py" "$build/shizuku-fixture.h" <<'PY'
import json, pathlib, sys
source = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
compile(source, "shizuku-qualification.py", "exec")
pathlib.Path(sys.argv[2]).write_text(
    "/* Generated from the fixed audited fixture. */\n#define SHIZUKU_FIXTURE \\\n" +
    " \\\n".join(json.dumps(line, ensure_ascii=True) for line in source.splitlines(keepends=True)) +
    "\n", encoding="ascii")
PY
cp -- "$here/shizuku-probe.c" "$build/"
cp -- "$here/shizuku-qualification.py" "$build/"
cp -- "$here/../native-runner-seccomp.h" "$build/"
cp -- "$here/shizuku-build.sh" "$build/"
cp -- "$here/shizuku-check-elf.py" "$build/"
ndk=/opt/foldgpt/android-ndk-r29
compiler="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang"
# NDK r29's Bionic static startup does not relocate a -static-pie image.
# Use the supported Android dynamic PIE startup/loader and retain ASLR.
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie \
  -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384 \
  -I"$build" "$build/shizuku-probe.c" -o "$build/probe"
"$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf" -hlnd "$build/probe" > "$build/probe-elf.txt"
python3 "$build/shizuku-check-elf.py" "$build/probe" > "$build/probe-elf-verified.json"
(cd "$build" && sha256sum probe shizuku-probe.c shizuku-qualification.py shizuku-fixture.h native-runner-seccomp.h > SHA256SUMS)
printf '%s\n' "$build"
