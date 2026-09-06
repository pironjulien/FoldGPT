#!/usr/bin/env bash
# Build only; never use ADB/Termux, overwrite android/native or create an APK.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
ndk_archive=${FOLDGPT_NDK_ARCHIVE:-/mnt/c/Dev/AndroidSdk-Linux/downloads/android-ndk-r29-linux.zip}
ndk_hash=4abbbcdc842f3d4879206e9695d52709603e52dd68d3c1fff04b3b5e7a308ecf
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
proot_commit=7266fb3e8516535682f5a9c8f3a7e70f6506eddb
shmem_commit=7f0bd7e25dbdd146265aff7c6a890029e374622d
talloc_hash=dc46c40b9f46bb34dd97fe41f548b0e8b247b77a918576733c528e83abd854dd
shmem_hash=1e5ff8459bc0a8c229dd8a94b27d119987e09ef3414331c2b5ebfff20b98e867
export LC_ALL=C TZ=UTC
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]
grep -qx 'Pkg.Revision = 29.0.14206865' "$ndk/source.properties"
for command in git make python3 curl tar sha256sum patch; do command -v "$command" >/dev/null; done
printf '%s  %s\n' "$ndk_hash" "$ndk_archive" | sha256sum -c -
[ "$(git -C "$repo/vendor/proot" rev-parse HEAD)" = "$proot_commit" ]
work=$(mktemp -d /var/tmp/foldgpt-native-XXXXXXXX)
artifact="$work/artifact"
mkdir -p "$artifact/runtime/arm64-v8a" "$artifact/sources" "$artifact/notices" "$artifact/build" "$work/deps/include/sys" "$work/deps/lib"
printf '%s\n' "$work" > "$artifact/build/native-directory.txt"
printf 'Native build directory: %s\n' "$work"
cp "$ndk/source.properties" "$artifact/build/ndk-source.properties"
printf '%s  android-ndk-r29-linux.zip\n' "$ndk_hash" > "$artifact/build/ndk-archive.sha256"
"$toolchain/clang" --version > "$artifact/build/compiler-version.txt"
sha256sum "$toolchain/clang" > "$artifact/build/compiler.sha256"
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git -C "$repo/vendor/proot" show -s --format=%ct "$proot_commit")
git -C "$repo/vendor/proot" archive "$proot_commit" > "$artifact/sources/proot-$proot_commit.tar"
curl -fL --retry 2 https://www.samba.org/ftp/talloc/talloc-2.4.3.tar.gz -o "$artifact/sources/talloc-2.4.3.tar.gz"
curl -fL --retry 2 https://codeload.github.com/termux/libandroid-shmem/tar.gz/refs/tags/v0.7 -o "$artifact/sources/android-shmem-0.7.tar.gz"
printf '%s  %s\n' "$talloc_hash" "$artifact/sources/talloc-2.4.3.tar.gz" "$shmem_hash" "$artifact/sources/android-shmem-0.7.tar.gz" | sha256sum -c -
mkdir "$work/proot"
tar -xf "$artifact/sources/proot-$proot_commit.tar" -C "$work/proot"
tar -xf "$artifact/sources/talloc-2.4.3.tar.gz" -C "$work"
tar -xf "$artifact/sources/android-shmem-0.7.tar.gz" -C "$work"
cp -a "$repo/tools/install/native" "$artifact/build/recipe"
patch -p1 --fuzz=0 -d "$work/libandroid-shmem-0.7" < "$artifact/build/recipe/android-shmem-tmpdir.patch"
patch -p1 --fuzz=0 -d "$work/proot" < "$artifact/build/recipe/proot-string-header.patch"
cp "$work/proot/COPYING" "$artifact/notices/PRoot-COPYING"
cp "$work/talloc-2.4.3/LICENSE" "$artifact/notices/talloc-LGPL-3.0"
cp "$work/libandroid-shmem-0.7/LICENSE" "$artifact/notices/android-shmem-BSD-3-Clause"
cp /usr/share/common-licenses/GPL-3 "$artifact/notices/GPL-3.0"

# This driver preserves PRoot's own -m32 loader selection while applying the
# required 16 KiB ELF load alignment to every link, including static loaders.
cat > "$work/cc" <<EOF
#!/usr/bin/env bash
set -euo pipefail
for argument in "\$@"; do
  case "\$argument" in -c|-E|-S|-fsyntax-only) exec "$toolchain/aarch64-linux-android30-clang" "\$@";; esac
done
exec "$toolchain/aarch64-linux-android30-clang" "\$@" -Wl,-z,max-page-size=16384,-z,common-page-size=16384
EOF
chmod 700 "$work/cc"
common="-O2 -fPIC -fstack-protector-strong -D_FORTIFY_SOURCE=2 -ffile-prefix-map=$work=/foldgpt-native-build"
python3 "$artifact/build/recipe/configure-talloc.py" --cc "$work/cc" --out "$work/talloc-config" | tee "$artifact/build/talloc-configure.log"
"$work/cc" $common -D_GNU_SOURCE -D__STDC_WANT_LIB_EXT1__=1 -fvisibility=hidden \
  -I"$work/talloc-config" -I"$work/talloc-2.4.3/lib/replace" -I"$work/talloc-2.4.3" \
  -shared "$work/talloc-2.4.3/talloc.c" -o "$work/deps/lib/libtalloc.so" \
  -Wl,-soname,libtalloc.so.2,--no-undefined,-z,relro,-z,now \
  > "$artifact/build/talloc-build.log" 2>&1
cp "$work/talloc-2.4.3/talloc.h" "$work/deps/include/"
cp -a "$work/talloc-config" "$artifact/build/"

make -C "$work/libandroid-shmem-0.7" CC="$work/cc" AR="$toolchain/llvm-ar" \
  CFLAGS="$common -std=c11 -Wall -Wextra" \
  LDFLAGS='-Wl,--version-script=exports.txt,-soname,libandroid-shmem.so,--no-undefined,-z,relro,-z,now' \
  libandroid-shmem.so > "$artifact/build/android-shmem-build.log" 2>&1
cp "$work/libandroid-shmem-0.7/libandroid-shmem.so" "$work/deps/lib/"
cp "$work/libandroid-shmem-0.7/shm.h" "$work/deps/include/sys/shm.h"

export CFLAGS="$common"
printf '#define VERSION "%s"\n' "$proot_commit" > "$artifact/build/proot-version.h"
export CPPFLAGS="-I$work/deps/include -include $artifact/build/proot-version.h"
export LDFLAGS="-L$work/deps/lib -Wl,--no-undefined,-z,relro,-z,now"
make -C "$work/proot/src" -j"$(nproc)" CC="$work/cc" LD="$work/cc" GIT=false \
  STRIP="$toolchain/llvm-strip" OBJCOPY="$toolchain/llvm-objcopy" OBJDUMP="$toolchain/llvm-objdump" \
  PROOT_UNBUNDLE_LOADER=/foldgpt/runtime PROOT_WITH_LIBANDROID_SHMEM=1 V=1 \
  > "$artifact/build/proot-build.log" 2>&1
cp "$work/proot/src/proot" "$artifact/runtime/arm64-v8a/libproot.so"
cp "$work/proot/src/loader/loader" "$artifact/runtime/arm64-v8a/libproot-loader.so"
cp "$work/proot/src/loader/loader-m32" "$artifact/runtime/arm64-v8a/libproot-loader32.so"
cp "$work/deps/lib/"*.so "$artifact/runtime/arm64-v8a/"
mkdir "$artifact/debug"
cp "$artifact/runtime/arm64-v8a/"*.so "$artifact/debug/"
"$toolchain/llvm-strip" --strip-unneeded "$artifact/runtime/arm64-v8a/"*.so
cp "$work/proot/src/build.h" "$artifact/build/proot-build.h"
python3 "$artifact/build/recipe/verify-elf.py" --artifact "$artifact" --ndk "$ndk" \
  --proot "$proot_commit" --shmem "$shmem_commit"

destination="$repo/downloads/install/native/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
cp -a "$artifact" "$destination"
printf 'Verified cross-build artifacts: %s\nNo Android execution performed.\n' "$destination"
