#!/usr/bin/env bash
# The sudo operations install PC build prerequisites only. Tests run as runner.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
stage=${1:?Expected native-python, linux-tests or arm64-build}
case "$stage" in native-python|linux-tests|arm64-build) ;; *) exit 2 ;; esac
cd "$repo"
mkdir -p work/ci/evidence work/ci/tools work/ci/cache
packages=(build-essential pkg-config clang cmake ninja-build libssl-dev libdbus-1-dev libcap-dev bubblewrap zsh ripgrep)
if [[ "$stage" = arm64-build ]]; then
    packages+=(gcc-aarch64-linux-gnu g++-aarch64-linux-gnu binutils-aarch64-linux-gnu)
fi
sudo apt-get update 2>&1 | tee work/ci/evidence/apt-update.log
sudo apt-get install --yes --no-install-recommends "${packages[@]}" 2>&1 | tee work/ci/evidence/apt-install.log
dpkg-query -W "${packages[@]}" > work/ci/evidence/apt-versions.txt
python3 -B tools/ci/native_validation.py identity
if [[ "$stage" = native-python ]]; then exit 0; fi
rustup toolchain install 1.95.0 --profile minimal --component rustfmt --component clippy
if [[ "$stage" = arm64-build ]]; then
    rustup target add --toolchain 1.95.0 aarch64-unknown-linux-gnu
fi
if [[ "$stage" = linux-tests ]]; then
    if [[ ! -x work/ci/tools/bin/just ]] || [[ "$(work/ci/tools/bin/just --version)" != 'just 1.58.0' ]]; then
        cargo +1.95.0 install --locked --version 1.58.0 just --root "$repo/work/ci/tools" --force
    fi
    if [[ ! -x work/ci/tools/bin/cargo-nextest ]] || [[ "$(work/ci/tools/bin/cargo-nextest nextest --version)" != 'cargo-nextest 0.9.143'* ]]; then
        cargo +1.95.0 install --locked --version 0.9.143 cargo-nextest --root "$repo/work/ci/tools" --force
    fi
fi
printf '%s\n' "$repo/work/ci/tools/bin" >> "$GITHUB_PATH"
rustc +1.95.0 -vV > work/ci/evidence/rustc.txt
cargo +1.95.0 -vV > work/ci/evidence/cargo.txt
rustup target list --toolchain 1.95.0 --installed > work/ci/evidence/rust-targets.txt
