#!/usr/bin/env bash
# Isolated host regression; never changes vendor, Android libraries or a device.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
commit=7266fb3e8516535682f5a9c8f3a7e70f6506eddb
export LC_ALL=C TZ=UTC
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]
[ "$(id -u)" != 0 ] || { printf 'Run this regression as a nonroot user.\n' >&2; exit 1; }
work=$(mktemp -d /var/tmp/foldgpt-proot-sigterm-XXXXXXXX)
printf 'Regression directory: %s\n' "$work"
# The public vendor tree has no upstream Git metadata and may contain patches.
# Build both variants from the same exact upstream object in a fresh directory.
git init -q "$work/upstream"
git -C "$work/upstream" remote add origin https://github.com/termux/proot.git
git -C "$work/upstream" fetch --depth 1 origin "$commit"
[ "$(git -C "$work/upstream" rev-parse FETCH_HEAD)" = "$commit" ]
git -C "$work/upstream" archive FETCH_HEAD > "$work/source.tar"
printf '%s\n' "$commit" > "$work/upstream-commit.txt"
cp -a "$repo/tools/install/native" "$work/recipe"
for variant in baseline patched; do
  mkdir "$work/$variant"
  tar -xf "$work/source.tar" -C "$work/$variant"
  for name in proot-string-header proot-shmat-errno; do
    patch -p1 --fuzz=0 -d "$work/$variant" < "$work/recipe/$name.patch"
  done
  if [ "$variant" = patched ]; then
    patch -p1 --fuzz=0 -d "$work/$variant" < "$work/recipe/proot-kill-on-exit-sigterm.patch"
  fi
  make -C "$work/$variant/src" -j"$(nproc)" GIT=false V=1 > "$work/$variant-build.log" 2>&1
done
cc -O2 -Wall -Wextra -Werror "$work/recipe/test-proot-sigterm-guest.c" -o "$work/guest"
cc -shared -fPIC -O2 -Wall -Wextra -Werror "$work/recipe/test-proot-sigterm-fork.c" -ldl -o "$work/fork-signal.so"
python3 "$work/recipe/test-proot-sigterm.py" "$work" | tee "$work/tests.log"
sha256sum "$work/source.tar" "$work/baseline/src/proot" "$work/patched/src/proot" \
  "$work/recipe/proot-kill-on-exit-sigterm.patch" "$work/guest" "$work/fork-signal.so" > "$work/SHA256SUMS"
printf 'Nonroot host regression completed: %s\n' "$work"
