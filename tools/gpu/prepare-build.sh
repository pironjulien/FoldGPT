#!/bin/bash
# Run in WSL Ubuntu 24.04. Host build dependencies only; never runs on Android.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
work="$repo/downloads/gpu"
version=26.2.2
# Official Mesa release notes, docs/relnotes/26.2.2.rst at main commit
# 86158b8c7467cadcd24f8a8cf02aa3bc748f7e3f, checked against the downloaded archive.
source_sha256=eeb29ca7e56cfaa8e8a79538dcf834e3b18e501c31bef5145e959ea437cc4216
if [ "$EUID" -ne 0 ]; then
    printf '%s\n' 'Run this host dependency preparation as WSL root (not Android root).' >&2
    exit 1
fi
apt-get update -qq
apt-get install --no-install-recommends -y ca-certificates curl xz-utils \
    gcc-aarch64-linux-gnu g++-aarch64-linux-gnu pkg-config ninja-build bison flex \
    python3-venv python3-mako python3-yaml python3-pycparser python3-packaging glslang-tools patch
mkdir -p "$work/src"
archive="$work/mesa-$version.tar.xz"
if [ ! -f "$archive" ]; then
    curl --fail --location --proto '=https' --tlsv1.2 \
        "https://archive.mesa3d.org/mesa-$version.tar.xz" -o "$archive.partial"
    printf '%s  %s\n' "$source_sha256" "$archive.partial" | sha256sum --check
    mv -T "$archive.partial" "$archive"
fi
printf '%s  %s\n' "$source_sha256" "$archive" | sha256sum --check
if [ ! -d "$work/src/mesa-$version" ]; then
    [ ! -e "$work/src/mesa-$version" ] && [ ! -L "$work/src/mesa-$version" ]
    extract_stage=$(mktemp -d "$work/src/.extract-XXXXXXXX")
    cleanup_extract() {
        case "$extract_stage" in "$work/src/".extract-*) ;; *) return 1 ;; esac
        [ ! -L "$extract_stage" ] && [ "$(realpath "$extract_stage")" = "$extract_stage" ] || return 1
        rm -rf -- "$extract_stage"
    }
    trap cleanup_extract EXIT
    tar -xJf "$archive" -C "$extract_stage" --no-same-owner
    [ -d "$extract_stage/mesa-$version" ] && [ ! -L "$extract_stage/mesa-$version" ]
    mv -nT "$extract_stage/mesa-$version" "$work/src/mesa-$version"
    [ ! -e "$extract_stage/mesa-$version" ]
    cleanup_extract
    trap - EXIT
fi
# Query the server's real DRI3 capabilities on KGSL's pseudo-DRM GLX path too.
# Upstream guards that query by kernel DRM, which leaves the value false on KGSL.
for mesa_patch in "$repo/tools/gpu/mesa-pseudodrm-dri3.patch" "$repo/tools/gpu/mesa-pseudodrm-wsi.patch" "$repo/tools/gpu/mesa-kopper-pixmap-import.patch" "$repo/tools/gpu/mesa-glx-randr-rate.patch" "$repo/tools/gpu/mesa-kgsl-calibrated-timestamps.patch" "$repo/tools/gpu/mesa-tc-renderpass-transition.patch" "$repo/tools/gpu/mesa-zink-render-area.patch"; do
if patch --fuzz=0 --directory="$work/src/mesa-$version" -p1 --dry-run --forward < "$mesa_patch" >/dev/null 2>&1; then
    patch --fuzz=0 --directory="$work/src/mesa-$version" -p1 --forward < "$mesa_patch"
else
    # Already-applied is the only accepted alternative, not an unknown conflict.
    patch --fuzz=0 --directory="$work/src/mesa-$version" -p1 --dry-run --reverse < "$mesa_patch" >/dev/null
fi
done
if [ ! -x "$work/build-venv/bin/python" ]; then
    python3 -m venv --system-site-packages "$work/build-venv"
fi
# Exact Meson version used for the recorded build; distro 1.3.2 is too old.
"$work/build-venv/bin/python" -m pip install --disable-pip-version-check 'meson==1.12.0'
