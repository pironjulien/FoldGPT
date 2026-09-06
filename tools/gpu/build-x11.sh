#!/bin/bash
# Reproducible native ARM64 X11 build in WSL/Linux; never installs an APK or
# overwrites android/native/x11. CMake's upstream patch steps run on a snapshot.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
source_root="$repo/vendor/termux-x11/lorie/src/main/cpp"
# Linux NDK headers contain case-distinct names (xt_RATEEST.h/xt_rateest.h).
# Keep the toolchain on WSL's POSIX filesystem; ordinary NTFS loses those files.
ndk=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}
version=29.0.14206865
archive_sha256=4abbbcdc842f3d4879206e9695d52709603e52dd68d3c1fff04b3b5e7a308ecf
archive_url=https://dl.google.com/android/repository/android-ndk-r29-linux.zip
archive=${FOLDGPT_NDK_ARCHIVE:-/mnt/c/Dev/AndroidSdk-Linux/downloads/android-ndk-r29-linux.zip}
build_parent="$repo/downloads/gpu/x11"
for program in cmake ninja python3 bison flex gcc patch git sha256sum tar; do
    command -v "$program" >/dev/null || { echo "Missing host tool: $program" >&2; exit 1; }
done
[ "$(uname -s)" = Linux ] && [ "$(uname -m)" = x86_64 ]
grep -qx "Pkg.Revision = $version" "$ndk/source.properties"
printf '%s  %s\n' "$archive_sha256" "$archive" | sha256sum -c -
toolchain="$ndk/toolchains/llvm/prebuilt/linux-x86_64/bin"
"$toolchain/clang" --version
export LC_ALL=C TZ=UTC
export SOURCE_DATE_EPOCH
SOURCE_DATE_EPOCH=$(git -C "$repo/vendor/termux-x11" show -s --format=%ct HEAD)
mkdir -p "$build_parent"
work=$(mktemp -d "$build_parent/build-XXXXXXXX")
mkdir "$work/source" "$work/artifact"
artifact="$work/artifact"
native_work=$(mktemp -d /var/tmp/foldgpt-x11-XXXXXXXX)
mkdir "$native_work/source"
printf '%s\n' "$native_work" > "$artifact/native-build-directory.txt"
# Use the host Python for NTFS snapshot I/O under WSL. Thousands of file/hash
# operations through 9P take minutes; Windows accesses the same files directly.
# Compilation still uses only the verified Linux NDK and Linux host utilities.
snapshot_python=python3
source_arg="$source_root"; work_arg="$work"; repo_arg="$repo"
if grep -qi microsoft /proc/version && command -v python.exe >/dev/null \
        && [[ "$repo" == /mnt/c/* ]]; then
    snapshot_python=$(command -v python.exe)
    source_arg=$(wslpath -w "$source_root")
    work_arg=$(wslpath -w "$work")
    repo_arg=$(wslpath -w "$repo")
fi
"$snapshot_python" --version > "$artifact/snapshot-python-version.txt"

# Snapshot and hash the exact current C sources, including untracked correction
# headers. Reject concurrent source changes; never change the submodule checkout.
"$snapshot_python" - "$source_arg" "$work_arg" <<'PY'
import hashlib, json, pathlib, shutil, sys
origin, work = map(pathlib.Path, sys.argv[1:])
def manifest(root):
    result = {}
    for path in sorted(root.rglob('*')):
        relative = path.relative_to(root)
        if '.git' in relative.parts:
            continue
        if path.is_symlink():
            result[relative.as_posix()] = {'symlink': str(path.readlink())}
        elif path.is_file():
            result[relative.as_posix()] = {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    return result
before = manifest(origin)
shutil.copytree(origin, work / 'source', symlinks=True, dirs_exist_ok=True,
                ignore=shutil.ignore_patterns('.git'))
if before != manifest(origin) or before != manifest(work / 'source'):
    raise SystemExit('Sources changed during snapshot; rerun when corrections are stable')
(work / 'artifact/source-input.json').write_text(json.dumps(before, sort_keys=True, indent=2) + '\n')
# Windows Git can check out CRLF or mixed endings. GNU patch strips CR from
# patch files but cannot match CRLF sources. Normalize text in the snapshot
# only, record this transformation, and preserve every original input hash.
normalized = []
for name in before:
    path = work / 'source' / name
    if path.is_symlink():
        continue
    data = path.read_bytes()
    if b'\0' in data or b'\r\n' not in data:
        continue
    try:
        data.decode('utf-8')
    except UnicodeDecodeError:
        continue
    path.write_bytes(data.replace(b'\r\n', b'\n'))
    normalized.append(name)
(work / 'artifact/normalized-text-files.json').write_text(json.dumps(normalized, indent=2) + '\n')
(work / 'artifact/source-normalized.json').write_text(json.dumps(manifest(work / 'source'), sort_keys=True, indent=2) + '\n')
PY
git -C "$repo/vendor/termux-x11" rev-parse HEAD > "$artifact/upstream-commit.txt"
git -C "$repo/vendor/termux-x11" submodule status --recursive > "$artifact/submodule-commits.txt"
git -C "$repo/vendor/termux-x11" diff --binary -- lorie/src/main/cpp > "$artifact/tracked-source.patch"
cp "$ndk/source.properties" "$artifact/ndk-source.properties"
cp "$repo/vendor/termux-x11/LICENSE" "$artifact/Termux-X11-LICENSE"
sha256sum "$toolchain/clang" > "$artifact/compiler.sha256"
printf '%s\n' "$archive_url" > "$artifact/ndk-archive-url.txt"
printf '%s\n' "$archive_sha256" > "$artifact/ndk-archive.sha256"

# A clean public clone has no dirty vendor changes. Apply the versioned FoldGPT
# patch, or verify it is already present, only in our normalized source copy.
cp "$repo/tools/gpu/termux-x11-dmabuf-sync.patch" "$artifact/foldgpt-source.patch"
sha256sum "$artifact/foldgpt-source.patch" > "$artifact/foldgpt-source.patch.sha256"
if ! patch -p5 -R --dry-run -d "$work/source" -i "$artifact/foldgpt-source.patch" >/dev/null 2>&1; then
    patch -p5 --dry-run -d "$work/source" -i "$artifact/foldgpt-source.patch" >/dev/null
    patch -p5 -d "$work/source" -i "$artifact/foldgpt-source.patch"
fi
patch -p5 -R --dry-run -d "$work/source" -i "$artifact/foldgpt-source.patch" >/dev/null

# Native source compilation also needs POSIX case semantics: on NTFS, Bionic's
# <xlocale.h> incorrectly resolves to libX11's Xlocale.h through its -I path.
# Transfer a tar stream assembled with native Windows I/O, then compile on ext4.
"$snapshot_python" - "$work_arg" <<'PY'
import pathlib, sys, tarfile
work = pathlib.Path(sys.argv[1])
with tarfile.open(work / 'artifact/source-prepared.tar', 'w') as archive:
    archive.add(work / 'source', arcname='.', recursive=True)
PY
tar -xf "$artifact/source-prepared.tar" -C "$native_work/source"
cmake -S "$native_work/source" -B "$native_work/build" -G Ninja \
    -DCMAKE_TOOLCHAIN_FILE="$ndk/build/cmake/android.toolchain.cmake" \
    -DANDROID_ABI=arm64-v8a -DANDROID_PLATFORM=android-24 \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    "-DCMAKE_C_FLAGS=-ffile-prefix-map=$native_work=/foldgpt-x11-build" \
    "-DCMAKE_CXX_FLAGS=-ffile-prefix-map=$native_work=/foldgpt-x11-build" \
    2>&1 | tee "$artifact/configure.log"

# Upstream's CMake patch helper ignores the patch process's result. Verify all
# expected patches are actually present instead of accepting a partial configure.
while IFS=$'\t' read -r directory patch_file; do
    patch -p1 -R --dry-run -d "$native_work/source/$directory" \
        -i "$native_work/source/patches/$patch_file" >/dev/null
done <<'PATCHES'
libxtrans	Xtrans.patch
pixman	pixman.patch
xkbcomp	xkbcomp.patch
libxkbfile	xkbfile.patch
libx11	x11.patch
xserver	xserver.patch
libepoxy	libepoxy.patch
PATCHES

jobs=${FOLDGPT_BUILD_JOBS:-$(python3 -c 'import os; print(max(1, int(os.cpu_count()/1.618)))')}
cmake --build "$native_work/build" --target Xlorie --parallel "$jobs" \
    2>&1 | tee "$artifact/build.log"
cp "$native_work/build/libXlorie.so" "$artifact/libXlorie.unstripped.so"
"$toolchain/llvm-strip" --strip-unneeded "$native_work/build/libXlorie.so" -o "$artifact/libXlorie.so"
"$toolchain/llvm-readelf" -h -l -d -n "$artifact/libXlorie.so" > "$artifact/elf-report.txt"
"$toolchain/llvm-nm" -D --defined-only "$artifact/libXlorie.so" > "$artifact/exported-symbols.txt"
cp "$native_work/build/compile_commands.json" "$artifact/compile_commands.json"
tar -czf "$artifact/source-built.tar.gz" -C "$native_work/source" .

"$snapshot_python" - "$source_arg" "$work_arg" "$repo_arg" "$version" <<'PY'
import hashlib, json, pathlib, re, struct, subprocess, sys
origin, work, repo = map(pathlib.Path, sys.argv[1:4])
artifact = work / 'artifact'
initial = json.loads((artifact / 'source-input.json').read_text())
current_paths = {path.relative_to(origin).as_posix() for path in origin.rglob('*')
                 if '.git' not in path.relative_to(origin).parts
                 and (path.is_file() or path.is_symlink())}
if current_paths != initial.keys():
    raise SystemExit('Source file set changed during build; rerun before publishing')
for name, value in initial.items():
    path = origin / name
    observed = ({'symlink': str(path.readlink())} if path.is_symlink()
                else {'sha256': hashlib.sha256(path.read_bytes()).hexdigest()})
    if observed != value:
        raise SystemExit('Source changed during build: ' + name + '; rerun before publishing')
report = (artifact / 'elf-report.txt').read_text()
assert re.search(r'Machine:\s+AArch64', report), 'Wrong ELF architecture'
assert re.search(r'Type:\s+DYN', report), 'Not a shared library'
assert 'libc.so.6' not in report and 'ld-linux' not in report, 'Wrong host ABI'
symbols = (artifact / 'exported-symbols.txt').read_text()
# Upstream uses RegisterNatives from JNI_OnLoad, not Java_* name exports.
assert re.search(r'\bT JNI_OnLoad\s*$', symbols, re.M), 'Missing JNI_OnLoad entry point'
library = (artifact / 'libXlorie.so').read_bytes()
assert library[:6] == b'\x7fELF\x02\x01', 'Not little-endian ELF64'
phoff = struct.unpack_from('<Q', library, 32)[0]
phsize, phnum = struct.unpack_from('<HH', library, 54)
loads = [struct.unpack_from('<IIQQQQQQ', library, phoff + phsize * i)
         for i in range(phnum) if struct.unpack_from('<I', library, phoff + phsize * i)[0] == 1]
assert loads and all(p[7] >= 16384 and p[2] % 16384 == p[3] % 16384 for p in loads), 'Invalid Android 16 KiB load alignment'
digest = hashlib.sha256(library).hexdigest()
manifest = {
    'library': 'libXlorie.so', 'sha256': digest, 'abi': 'arm64-v8a', 'api': 24,
    'ndkVersion': sys.argv[4], 'upstreamCommit': (artifact / 'upstream-commit.txt').read_text().strip(),
    'loadPageAlignment': 16384, 'jniEntryPoint': 'JNI_OnLoad',
    'foldgptPatchSha256': hashlib.sha256((artifact / 'foldgpt-source.patch').read_bytes()).hexdigest(),
    'sourceInputSha256': hashlib.sha256((artifact / 'source-input.json').read_bytes()).hexdigest(),
    'sourceDateEpoch': int(subprocess.check_output(['git', '-C', str(repo / 'vendor/termux-x11'),
                                                 'show', '-s', '--format=%ct', 'HEAD'])),
    'deviceTested': False, 'installedIntoApk': False,
}
(artifact / 'build-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps(manifest))
PY
printf 'Verified build artifact (not installed): %s\n' "$artifact"
