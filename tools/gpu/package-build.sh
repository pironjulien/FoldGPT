#!/bin/bash
# Stage the completed build and probes. May be rerun after editing only a probe.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work="$repo/downloads/gpu"
version=26.2.2
prefix="/opt/foldgpt-gpu/mesa-$version-foldgpt4"
DESTDIR="$work/stage" "$work/build-venv/bin/meson" install -C "$work/build-$version"
mkdir -p "$work/stage$prefix/bin"
aarch64-linux-gnu-gcc --sysroot="$work/sysroot" -O2 -Wall -Wextra -Werror \
    -I"$work/sysroot/usr/include" -L"$work/sysroot/usr/lib/aarch64-linux-gnu" \
    "$repo/tools/gpu/vulkan-clear-probe.c" -lvulkan -o "$work/stage$prefix/bin/vulkan-clear-probe"
aarch64-linux-gnu-gcc --sysroot="$work/sysroot" -O2 -Wall -Wextra -Werror \
    -I"$work/stage$prefix/include" -L"$work/stage$prefix/lib" -L"$work/sysroot/usr/lib/aarch64-linux-gnu" \
    -Wl,-rpath-link,"$work/stage$prefix/lib" -Wl,-rpath-link,"$work/sysroot/usr/lib/aarch64-linux-gnu" \
    "$repo/tools/gpu/glx-clear-probe.c" -lGL -lX11 -o "$work/stage$prefix/bin/glx-clear-probe"
bash "$repo/tools/gpu/build-timestamp-probe.sh"
install -m 755 "$work/vulkan-timestamp-probe" "$work/stage$prefix/bin/vulkan-timestamp-probe"
tar -C "$work/stage" -czf "$work/foldgpt-mesa-$version-arm64.tar.gz" "${prefix#/}"
sha256sum "$work/foldgpt-mesa-$version-arm64.tar.gz"
