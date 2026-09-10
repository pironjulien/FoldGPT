#!/usr/bin/env python3
"""Apply diagnostic patch only to a temporary copy and syntax-check ARM64 objects."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--repo', type=Path, required=True)
args = p.parse_args()
repo = args.repo.resolve()
source = repo / 'downloads/gpu/src/mesa-26.2.2'
build = repo / 'downloads/gpu/build-26.2.2'
relative = Path('src/freedreno/vulkan')
original = source / relative
names = ['tu_cmd_buffer.cc', 'tu_clear_blit.cc', 'tu_util.cc', 'tu_util.h']
before = {n: hashlib.sha256((original / n).read_bytes()).hexdigest() for n in names}
stage = Path(tempfile.mkdtemp(prefix='foldgpt-gmem-metadata-', dir='/var/tmp'))
overlay = stage / relative
shutil.copytree(original, overlay)
patch = repo / 'tools/gpu/diagnostics/mesa-gmem-metadata.patch'
with patch.open('rb') as inp:
    subprocess.run(['patch', '--fuzz=0', '-p1', '-d', str(stage)], stdin=inp, check=True)
commands = json.loads((build / 'compile_commands.json').read_text())
report = {'stage': str(stage), 'sourceBefore': before, 'checks': []}
for name in names[:3]:
    original_command = next(c for c in commands if c['file'].endswith('/' + name))
    parts = shlex.split(original_command['command'])
    filtered = []
    i = 0
    while i < len(parts):
        if parts[i] in ['-o', '-MQ', '-MF']:
            i += 2
            continue
        if parts[i] in ['-c', '-MD']:
            i += 1
            continue
        if parts[i].endswith('/' + name):
            i += 1
            continue
        filtered.append(parts[i])
        i += 1
    filtered[1:1] = ['-I' + str(overlay)]
    filtered += ['-fsyntax-only', str(overlay / name)]
    result = subprocess.run(filtered, cwd=build, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT)
    (stage / (name + '.log')).write_text(result.stdout)
    report['checks'].append({'name': name, 'exitCode': result.returncode})
    print(name, 'PASS' if result.returncode == 0 else 'FAIL', flush=True)
    if result.returncode:
        print(result.stdout, flush=True)
report['sourceAfter'] = {n: hashlib.sha256((original / n).read_bytes()).hexdigest() for n in names}
report['sourceUnchanged'] = report['sourceBefore'] == report['sourceAfter']
(stage / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report), flush=True)
raise SystemExit(not (report['sourceUnchanged'] and all(c['exitCode'] == 0 for c in report['checks'])))
