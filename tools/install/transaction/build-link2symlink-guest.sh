#!/usr/bin/env bash
set -euo pipefail
# Build a debug-only ARM64 Linux fixture, never part of the production runtime.
test "$#" -eq 1 || { echo 'usage: build-link2symlink-guest.sh OUTPUT_DIRECTORY' >&2; exit 2; }
source_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
mkdir -p -- "$1"
aarch64-linux-gnu-gcc -std=c11 -O2 -Wall -Wextra -Werror -static \
  -Wl,-z,max-page-size=16384 -Wl,-z,noexecstack \
  "$source_dir/link2symlink-guest.c" -o "$1/libfoldgpt-l2s-fixture.so"
sha256sum "$1/libfoldgpt-l2s-fixture.so"
