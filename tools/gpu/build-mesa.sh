#!/bin/bash
# Build Mesa for an isolated FoldGPT test prefix. Nothing is installed on Android.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
bash "$repo/tools/gpu/prepare-build.sh"
work="$repo/downloads/gpu"
version=26.2.2
prefix="/opt/foldgpt-gpu/mesa-$version-foldgpt5"
build="$work/build-$version"
# APT's unprivileged downloader needs real POSIX chmod semantics. Its cache stays
# on WSL's Linux filesystem; source, sysroot and deliverables stay in C:\Dev.
apt_cache=/var/cache/foldgpt-gpu-apt
mkdir -p "$work/apt" "$apt_cache/lists/partial" "$apt_cache/archives/partial" "$work/sysroot/.packages" "$work/stage"
printf '%s\n' 'deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://ports.ubuntu.com/ubuntu-ports noble main universe' \
    'deb [arch=arm64 signed-by=/usr/share/keyrings/ubuntu-archive-keyring.gpg] http://ports.ubuntu.com/ubuntu-ports noble-updates main universe' \
    > "$work/apt/arm64.list"
apt_args=(-o "Dir::Etc::sourcelist=$work/apt/arm64.list" -o Dir::Etc::sourceparts=-
    -o APT::Architecture=arm64 -o "Dir::State::lists=$apt_cache/lists"
    -o Dir::State::status=/dev/null -o "Dir::Cache::archives=$apt_cache/archives")
apt-get "${apt_args[@]}" update -qq
apt-get "${apt_args[@]}" --download-only --no-install-recommends -y install \
    libc6-dev libstdc++-13-dev zlib1g-dev libzstd-dev libdrm-dev libexpat1-dev \
    libx11-dev libx11-xcb-dev libxcb-glx0-dev libxcb-dri3-dev libxcb-present-dev \
    libxcb-randr0-dev libxcb-sync-dev libxcb-shm0-dev libxcb-xfixes0-dev \
    libxshmfence-dev libxext-dev libxxf86vm-dev libxfixes-dev libxrandr-dev libvulkan-dev
for package in "$apt_cache/archives/"*.deb; do
    stamp="$work/sysroot/.packages/$(basename "$package").sha256"
    checksum=$(sha256sum "$package")
    if [ ! -f "$stamp" ] || [ "$(cat "$stamp")" != "$checksum" ]; then
        dpkg-deb -x "$package" "$work/sysroot"
        printf '%s\n' "$checksum" > "$stamp"
    fi
done
# Noble packages use merged /usr. dpkg-deb extracts package payloads but does not
# run the base-files pre-install script that creates this standard alias.
if [ ! -e "$work/sysroot/lib" ] && [ ! -L "$work/sysroot/lib" ]; then
    ln -s usr/lib "$work/sysroot/lib"
fi
[ "$(readlink "$work/sysroot/lib")" = usr/lib ]
cat > "$work/aarch64.ini" <<EOF
[binaries]
c = 'aarch64-linux-gnu-gcc'
cpp = 'aarch64-linux-gnu-g++'
ar = 'aarch64-linux-gnu-ar'
strip = 'aarch64-linux-gnu-strip'
pkg-config = 'pkg-config'
[host_machine]
system = 'linux'
cpu_family = 'aarch64'
cpu = 'aarch64'
endian = 'little'
[properties]
sys_root = '$work/sysroot'
pkg_config_libdir = ['$work/sysroot/usr/lib/aarch64-linux-gnu/pkgconfig', '$work/sysroot/usr/share/pkgconfig']
needs_exe_wrapper = true
[built-in options]
c_args = ['--sysroot=$work/sysroot']
cpp_args = ['--sysroot=$work/sysroot']
c_link_args = ['--sysroot=$work/sysroot']
cpp_link_args = ['--sysroot=$work/sysroot']
EOF
meson="$work/build-venv/bin/meson"
setup_args=()
if [ -f "$build/meson-private/coredata.dat" ]; then setup_args+=(--reconfigure); fi
"$meson" setup "${setup_args[@]}" "$build" "$work/src/mesa-$version" --cross-file "$work/aarch64.ini" \
    --prefix "$prefix" --libdir lib --buildtype release --wrap-mode nofallback \
    -Dplatforms=x11 -Dgallium-drivers=zink -Dvulkan-drivers=freedreno -Dfreedreno-kmds=kgsl \
    -Dllvm=disabled -Dgallium-rusticl=false -Dglx=dri -Degl=enabled -Dgbm=disabled \
    -Dglvnd=disabled -Dvideo-codecs= -Dbuild-tests=false -Dtools= -Dlibunwind=disabled
jobs=$(python3 -c 'import os; print(max(1, int(os.cpu_count()/1.618)))')
ninja -C "$build" -j "$jobs"
bash "$repo/tools/gpu/package-build.sh"
