#!/bin/bash
# Cross-compile only this diagnostic; no Android deployment or Mesa rebuild.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work="$repo/downloads/gpu"
output="$work/vulkan-timestamp-probe"
[ -d "$work/sysroot/usr/include/vulkan" ] || {
    printf '%s\n' 'Prepare the GPU ARM64 sysroot with build-mesa.sh first.' >&2
    exit 1
}
aarch64-linux-gnu-gcc --sysroot="$work/sysroot" -std=c11 -O2 \
    -Wall -Wextra -Werror \
    -I"$work/sysroot/usr/include" -L"$work/sysroot/usr/lib/aarch64-linux-gnu" \
    "$repo/tools/gpu/vulkan-timestamp-probe.c" -lvulkan -lm -o "$output"
aarch64-linux-gnu-readelf -h "$output" | sed -n '/Class:/p;/Machine:/p'
sha256sum "$output"
