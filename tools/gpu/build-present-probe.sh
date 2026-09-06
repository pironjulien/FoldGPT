#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work="$repo/downloads/gpu"
prefix=/opt/foldgpt-gpu/mesa-26.2.2-foldgpt4
for probe in glx-present-probe glx-tfp-probe; do
aarch64-linux-gnu-gcc --sysroot="$work/sysroot" -O2 -Wall -Wextra -Werror \
    -I"$work/stage$prefix/include" -L"$work/stage$prefix/lib" -L"$work/sysroot/usr/lib/aarch64-linux-gnu" \
    -Wl,-rpath-link,"$work/stage$prefix/lib" -Wl,-rpath-link,"$work/sysroot/usr/lib/aarch64-linux-gnu" \
    "$repo/tools/gpu/$probe.c" -lGL -lX11 -lXrandr -lxcb -lxcb-present -o "$work/$probe"
done
