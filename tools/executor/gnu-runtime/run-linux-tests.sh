#!/usr/bin/env bash
# Fixed nonroot GNU project, actual kernel policy, sources and bytes retained.
set -euo pipefail
recipe=$(cd "$(dirname "$0")" && pwd)
proot=${1:?Usage: run-linux-tests.sh STRICT_PROOT [ROOTFS]}
rootfs=${2:-/}
[ "$(id -u)" != 0 ] || { printf 'Ordinary nonroot UID required.\n' >&2; exit 1; }
proot=$(realpath "$proot")
rootfs=$(realpath "$rootfs")
work=$(mktemp -d /var/tmp/foldgpt-gnu-project-XXXXXXXX)
printf 'GNU project evidence: %s\n' "$work"
mkdir "$work/sources"
cp "$recipe"/*.py "$recipe"/*.c "$recipe"/*.h "$recipe"/*.json "$recipe"/*.sh "$work/sources/"
cc -O2 -Wall -Wextra -Werror "$work/sources/gnu-project.c" -o "$work/gnu-project"
cc --version > "$work/compiler.txt"
id > "$work/identity.txt"
uname -a > "$work/kernel.txt"
printf '%s\n' "$proot" "$rootfs" > "$work/inputs.txt"
sha256sum "$proot" "$(dirname "$proot")/loader/loader" \
    "$(dirname "$proot")/loader/loader-m32" > "$work/runtime-inputs.sha256"
set +e
"$work/gnu-project" "$work" "$proot" "$rootfs" > "$work/runtime.log" 2>&1
code=$?
set -e
cat "$work/runtime.log"
printf '%s\n' "$code" > "$work/exit-code.txt"
if [ "$code" = 0 ]; then
  python3 "$work/sources/verify-host.py" "$work"
fi
(cd "$work" && find sources -type f -print0 | sort -z | xargs -0 sha256sum > sources.sha256)
sha256sum "$work/gnu-project" "$work/runtime.log" >> "$work/sources.sha256"
exit "$code"
