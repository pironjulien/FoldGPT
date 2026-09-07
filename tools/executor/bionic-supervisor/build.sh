#!/usr/bin/env bash
# Freeze the real factory, compile Linux and Android, test on a nonroot host.
# Android artifacts are built and inspected only; this script has no adb route.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-bionic-supervisor-XXXXXXXX)
chmod 755 "$work"
source_dir="$work/package/tools/executor"
mkdir -p "$source_dir/bionic-supervisor" "$work/package/tools/policy" "$work/backend-sources/tools/executor/bionic-supervisor"
for package in tools tools/executor tools/policy; do
    : > "$work/package/$package/__init__.py"
done
for name in exec_server native_executor_backend native_file_streams native_files native_processes \
    native_process_policy native_environment native_environment_unicode policy_intent private_exec_broker; do
    cp "$repo/tools/executor/$name.py" "$source_dir/"
done
cp "$repo/tools/policy/managed_policy.py" "$work/package/tools/policy/"
cp "$repo/tools/executor/"{native-runner-seccomp.h,native-files.c,native-file-handle.c,native-process-fd-abi.c} "$source_dir/"
cp "$repo/tools/executor/bionic-supervisor/"*.py "$source_dir/bionic-supervisor/"
cp "$repo/tools/executor/bionic-supervisor/"{runner.c,qualification-worker.c} "$source_dir/bionic-supervisor/"
cp "$repo/tools/executor/bionic-supervisor/build.sh" "$repo/tools/executor/bionic-supervisor/README.md" "$work/"
cp "$repo/tools/executor/bionic-runtime/shizuku-check-elf.py" "$work/check-elf.py"
for name in __init__ factory policy processes wire; do
    cp "$source_dir/bionic-supervisor/$name.py" "$work/backend-sources/tools/executor/bionic-supervisor/"
done
compiler=${ANDROID_NDK_HOME:-/opt/foldgpt/android-ndk-r29}/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android35-clang
for program in runner native-files native-file-handle qualification-worker; do
    source="$source_dir/$program.c"
    if [ "$program" = runner ] || [ "$program" = qualification-worker ]; then source="$source_dir/bionic-supervisor/$program.c"; fi
    extra=(); if [ "$program" = qualification-worker ]; then extra=(-pthread); fi
    gcc -std=c11 -O2 -Wall -Wextra -Werror "${extra[@]}" -I"$source_dir" "$source" -o "$work/$program"
    library="libfoldgpt_${program//-/_}.so"
    [ "$program" != runner ] || library=libfoldgpt_bionic_supervisor.so
    "$compiler" -std=c11 -O2 -Wall -Wextra -Werror "${extra[@]}" -fPIE -pie -I"$source_dir" \
        -Wl,-z,max-page-size=16384,-z,common-page-size=16384,-z,relro,-z,now \
        "$source" -o "$work/$library"
    python3 -B "$work/check-elf.py" "$work/$library" > "$work/$library.elf.json"
done
python3 - "$source_dir/bionic-supervisor/runner.c" "$work/runner-after-final-stop.c" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
anchor = '(void)packet(final,(size_t)length,1);return '
assert source.count(anchor) == 1
Path(sys.argv[2]).write_text(source.replace(anchor, '(void)packet(final,(size_t)length,1);raise(SIGSTOP);return '))
PY
gcc -std=c11 -O2 -Wall -Wextra -Werror -I"$source_dir" "$work/runner-after-final-stop.c" -o "$work/runner-after-final-stop"
python3 - "$source_dir/bionic-supervisor/runner.c" "$work/runner-getdents-memory-missing.c" <<'PY'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_text()
anchor = 'case SYS_getdents64:{int mem=memory(listener,n);'
assert source.count(anchor) == 1
replacement = '''case SYS_getdents64:{
      char fault_fd[96],fault_path[MAX_PATH];
      snprintf(fault_fd,sizeof(fault_fd),"/proc/%u/fd/%d",n->pid,(int)n->data.args[0]);
      ssize_t fault_len=readlink(fault_fd,fault_path,sizeof(fault_path)-1);
      int fault_project=fault_len>=8&&!memcmp(fault_path+fault_len-8,"/project",8);
      int mem=fault_project?-1:memory(listener,n);if(fault_project)errno=ENOENT;'''
Path(sys.argv[2]).write_text(source.replace(anchor, replacement))
PY
gcc -std=c11 -O2 -Wall -Wextra -Werror -I"$source_dir" "$work/runner-getdents-memory-missing.c" -o "$work/runner-getdents-memory-missing"
gcc -std=c11 -O2 -Wall -Wextra -Werror "$source_dir/native-process-fd-abi.c" -o "$work/native-process-fd-abi"
"$compiler" -std=c11 -O2 -Wall -Wextra -Werror -fPIE -pie \
    -Wl,-z,max-page-size=16384,-z,common-page-size=16384,-z,relro,-z,now \
    "$source_dir/native-process-fd-abi.c" -o "$work/libfoldgpt_fd_abi.so"
"$work/native-process-fd-abi" > "$work/fd-abi.json"
gcc --version > "$work/compilers.txt"
"$compiler" --version >> "$work/compilers.txt"
if [ "$(id -u)" = 0 ]; then
    chown -R nobody:nogroup "$work"
    run=(runuser -u nobody --)
else
    run=()
fi
"${run[@]}" id > "$work/test-identity.txt"
"${run[@]}" python3 -B "$source_dir/bionic-supervisor/test_kernel.py" "$work/runner" 2>&1 | tee "$work/kernel-tests.txt"
"${run[@]}" python3 -B "$source_dir/bionic-supervisor/test_factory.py" "$work" 2>&1 | tee "$work/factory-tests.txt"
"${run[@]}" python3 -B "$source_dir/bionic-supervisor/qualification.py" "$work" 2>&1 | tee "$work/qualification-tests.txt"
(cd "$work" && python3 -B - <<'PY'
from pathlib import Path
import json
import shutil
rows = [json.loads(line) for line in Path('qualification-tests.txt').read_text().splitlines() if line.startswith('{')]
assert len(rows) == 1 and rows[0]['success'] is True
shutil.copyfile(Path(rows[0]['evidence']) / 'qualification.json', 'qualification.json')
PY
)
(cd "$work" && find package backend-sources -type f -print0 | sort -z | xargs -0 sha256sum > SOURCES.sha256)
(cd "$work" && sha256sum runner native-files native-file-handle qualification-worker *.so > BINARIES.sha256)
destination="$repo/downloads/bionic-supervisor/$(basename "$work")"
mkdir -p "$(dirname "$destination")"
[ ! -e "$destination" ]
python3 - "$work" "$destination" <<'PY'
from pathlib import Path
import hashlib
import shutil
import sys
source, target = map(Path, sys.argv[1:])
target.mkdir()
for path in sorted(source.rglob('*')):
    if path.is_symlink():
        raise ValueError('Unexpected alias in frozen build')
    output = target / path.relative_to(source)
    if path.is_dir():
        output.mkdir()
    else:
        # Copy bytes only. DrvFS ownership/timestamp propagation is unavailable
        # to this nonroot host UID and is not evidence of build content.
        shutil.copyfile(path, output)
        if hashlib.sha256(path.read_bytes()).digest() != hashlib.sha256(output.read_bytes()).digest():
            raise OSError('Frozen build transfer changed bytes')
PY
printf 'Frozen nonroot host qualification and Android compile evidence: %s\n' "$destination"
printf 'Native host build: %s\nNo Android execution was performed.\n' "$work"
