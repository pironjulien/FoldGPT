#!/bin/bash
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
output="$repo/downloads/gpu/x11/host-tests"
mkdir -p "$output"
c++ -std=c++17 -pthread -Wall -Wextra -Werror -g -O1 \
    -fsanitize=address,undefined -fno-omit-frame-pointer \
    -I "$repo/vendor/termux-x11/lorie/src/main/cpp/lorie" \
    "$repo/tools/gpu/test-x11-event-reader.cpp" -o "$output/test-x11-event-reader"
ASAN_OPTIONS=detect_leaks=1 "$output/test-x11-event-reader"
