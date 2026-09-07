#!/usr/bin/env bash
# Cross-compilation only. Never installs, starts ADB or executes phone code.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
prefix=${1:?Usage: build-python-cli.sh OFFICIAL_STAGED_PREFIX ANDROID_PYTHON_HOME [ARCHIVE]}
runtime_home=${2:?The actual Android Python deployment prefix is required}
case "$runtime_home" in /*) ;; *) printf 'Runtime home must be absolute\n' >&2; exit 2;; esac
if [[ "$runtime_home" == *'"'* || "$runtime_home" == *$'\n'* || "$runtime_home" == *$'\r'* || "$runtime_home" == *'\'* || "$runtime_home" == *':'* || "$runtime_home" == *'$'* ]]; then
  printf 'Invalid runtime home\n' >&2; exit 2
fi
archive=${3:-$repo/downloads/native-python/inputs/python-3.14.7-aarch64-linux-android.tar.gz}
test -d "$prefix/include/python3.14"
test -f "$prefix/lib/libpython3.14.so"
python3 -B "$here/python-package.py" "$archive" "$prefix"
grep -qx 'Pkg.Revision = 29.0.14206865' "$ndk/source.properties"
work=$(mktemp -d /var/tmp/foldgpt-bionic-python-XXXXXXXX)
compiler="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang"
cp "$here/python-cli.c" "$work/"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie \
  -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384 \
  -Xlinker -rpath -Xlinker "$runtime_home/lib:\$ORIGIN" -Wl,--no-undefined \
  "-DFOLDGPT_PYTHON_HOME=\"$runtime_home\"" \
  -I"$prefix/include/python3.14" "$work/python-cli.c" \
  -L"$prefix/lib" -Wl,--no-as-needed -lpython3.14 -lcrypto_python -lssl_python -lsqlite3_python \
  -Wl,--as-needed -o "$work/libfoldgpt_python_cli.so"
"$compiler" --version > "$work/compiler.txt"
cp "$ndk/source.properties" "$work/ndk-source.properties"
printf '%s\n' "$runtime_home" > "$work/deployment-prefix.txt"
"$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-readelf" \
  -h -l -d "$work/libfoldgpt_python_cli.so" > "$work/elf.txt"
python3 -B - "$work/elf.txt" "$runtime_home/lib:\$ORIGIN" <<'PY'
from pathlib import Path
import re
import sys
dynamic = Path(sys.argv[1]).read_text()
paths = re.findall(r'\(RUNPATH\)\s+Library runpath: \[(.*?)\]', dynamic)
if paths != [sys.argv[2]]:
    raise ValueError('Compiled Python runtime search path differs from its deployment')
required = set(re.findall(r'\(NEEDED\)\s+Shared library: \[(.*?)\]', dynamic))
if not {'libpython3.14.so', 'libcrypto_python.so', 'libssl_python.so', 'libsqlite3_python.so'} <= required:
    raise ValueError('Compiled Python CLI does not directly load its runtime dependencies')
PY
sha256sum "$work/python-cli.c" "$work/libfoldgpt_python_cli.so" \
  "$prefix/lib/libpython3.14.so" > "$work/SHA256SUMS"
printf 'Bionic Python CLI cross-compiled, not device-tested: %s\n' "$work"
