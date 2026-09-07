#!/usr/bin/env bash
# Genuine nonroot host tests; retain all sources/results without touching a phone.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
commit=7266fb3e8516535682f5a9c8f3a7e70f6506eddb
export LC_ALL=C TZ=UTC
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]
[ "$(id -u)" != 0 ] || { printf 'Run this regression as a nonroot user.\n' >&2; exit 1; }
[ "$(git -c safe.directory="$repo/vendor/proot" -C "$repo/vendor/proot" rev-parse HEAD)" = "$commit" ]
work=$(mktemp -d /var/tmp/foldgpt-proot-strict-XXXXXXXX)
printf 'Regression directory: %s\n' "$work"
git -c safe.directory="$repo/vendor/proot" -C "$repo/vendor/proot" archive "$commit" > "$work/source.tar"
cp -a "$repo/tools/install/native" "$work/recipe"
for variant in baseline patched; do
  mkdir "$work/$variant"
  tar -xf "$work/source.tar" -C "$work/$variant"
  for name in proot-string-header proot-shmat-errno proot-kill-on-exit-sigterm; do
    patch -p1 --fuzz=0 -d "$work/$variant" < "$work/recipe/$name.patch"
  done
  if [ "$variant" = patched ]; then
    patch -p1 --fuzz=0 -d "$work/$variant" < "$work/recipe/proot-strict-sandbox.patch"
  fi
  make -C "$work/$variant/src" -j"$(nproc)" GIT=false V=1 > "$work/$variant-build.log" 2>&1
done
cc -O2 -Wall -Wextra -Werror "$work/recipe/test-proot-strict-guest.c" -o "$work/guest"
cc -O2 -Wall -Wextra -Werror "$work/recipe/test-proot-sigterm-guest.c" -o "$work/sigterm-guest"
cc -O2 -Wall -Wextra -Werror "$work/recipe/test-landlock-scope.c" -o "$work/scope-admission"
cc -O2 -Wall -Wextra -Werror "$work/recipe/test-proot-tracer-guest.c" -o "$work/tracer-guest"
cc -O2 -Wall -Wextra -Werror -shared -fPIC "$work/recipe/test-proot-tracer-preload.c" -o "$work/tracer-preload.so"
cc --version > "$work/compiler-version.txt"
id > "$work/identity.txt"
uname -a > "$work/kernel.txt"
python3 "$work/recipe/test-proot-strict.py" "$work" | tee "$work/tests.log"
python3 "$work/recipe/test-proot-tracer.py" "$work" | tee "$work/tracer-tests.log"
sha256sum "$work/source.tar" "$work/baseline/src/proot" "$work/patched/src/proot" \
  "$work/recipe/proot-strict-sandbox.patch" "$work/guest" "$work/sigterm-guest" > "$work/SHA256SUMS"
sha256sum "$work/scope-admission" "$work/tracer-guest" "$work/tracer-preload.so" \
  "$work/tracer-verification.json" >> "$work/SHA256SUMS"
printf 'Nonroot host regression completed: %s\n' "$work"
