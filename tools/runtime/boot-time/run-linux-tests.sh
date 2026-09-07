#!/usr/bin/env bash
# Build only private test artifacts; never install ps or alter /proc.
set -euo pipefail
task_tools=$(cd -- "$(dirname -- "$0")" && pwd)
task_root=$(cd -- "$task_tools/../../.." && pwd)
task_sources="$task_root/downloads/runtime-boot-time/procps-source"
task_work=$(mktemp -d /var/tmp/foldgpt-procps-boot-XXXXXXXX)
printf '%s\n' "$task_work"
cp -a "$task_tools" "$task_work/test-source"
task_tools="$task_work/test-source"
python3 - "$task_tools/source-lock.json" "$task_sources" <<'PY'
import hashlib,json,pathlib,sys
lock=json.loads(pathlib.Path(sys.argv[1]).read_text())
for f in lock['files']:
    data=(pathlib.Path(sys.argv[2])/f['name']).read_bytes()
    assert len(data)==f['bytes'] and hashlib.sha256(data).hexdigest()==f['sha256'],f['name']
PY
dpkg-source --no-check -x "$task_sources/procps_4.0.4-9.dsc" "$task_work/source" >"$task_work/source-extraction.log" 2>&1
python3 "$task_tools/make-patch.py" "$task_work/source"
cp -a "$task_work/source" "$task_work/patched"
patch --fuzz=0 -d "$task_work/patched" -p1 <"$task_tools/procps-4.0.4-9-boot-time.patch" >"$task_work/patch.log" 2>&1
cp "$task_tools/boot-time.h" "$task_tools/test-clock.c" "$task_tools/deny-proc-stat.c" "$task_work/"
if [ "$(id -u)" = 0 ]; then
    chown -R nobody:nogroup "$task_work"
    task_as=(runuser -u nobody --)
else
    task_as=()
fi
for task_tree in source patched; do
    # Authenticated release tarball includes configure; only Makefile.am changed.
    # Regenerate build metadata for a complete redistributable-source patch.
    ( cd "$task_work/$task_tree"
      "${task_as[@]}" autoreconf -fi >"$task_work/$task_tree-autoreconf.log" 2>&1
      "${task_as[@]}" ./configure --without-ncurses --without-systemd --disable-numa --disable-nls >"$task_work/$task_tree-configure.log" 2>&1
      "${task_as[@]}" make -j2 src/ps/pscommand >"$task_work/$task_tree-build.log" 2>&1
    )
done
"${task_as[@]}" cc -std=c11 -Wall -Wextra -Werror -fsanitize=undefined,address -g -o "$task_work/test-clock" "$task_work/test-clock.c"
"${task_as[@]}" cc -std=c11 -Wall -Wextra -Werror -O2 -o "$task_work/deny-proc-stat" "$task_work/deny-proc-stat.c"
"${task_as[@]}" "$task_work/test-clock" >"$task_work/clock-tests.log" 2>&1
"${task_as[@]}" python3 "$task_tools/test-live.py" "$task_work" >"$task_work/live-tests.log" 2>&1
python3 - "$task_work" "$task_tools" <<'PY'
import hashlib,json,pathlib,sys
work,tools=map(pathlib.Path,sys.argv[1:])
report=json.loads((work/'live-results.json').read_text())
report['clock_tests']=(work/'clock-tests.log').read_text().strip()
report['source_lock_sha256']=hashlib.sha256((tools/'source-lock.json').read_bytes()).hexdigest()
report['patch_sha256']=hashlib.sha256((tools/'procps-4.0.4-9-boot-time.patch').read_bytes()).hexdigest()
report['test_sources']={str(p.relative_to(tools)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(tools.iterdir()) if p.is_file()}
report['artifacts']={str(p.relative_to(work)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(work.rglob('*')) if p.is_file() and (p.suffix=='.log' or p.name in ('pscommand','libproc2.so.0.0.2','test-clock','deny-proc-stat'))}
(work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:v for k,v in report.items() if k not in ('artifacts','test_sources')},indent=2))
PY
python3 "$task_tools/collect-local.py" "$task_work" "$task_root/downloads/runtime-boot-time/$(basename -- "$task_work")"
