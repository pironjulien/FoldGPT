"""Controlled nonroot Landlock hierarchy plus actual immutable PRoot tests."""
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

work = Path(sys.argv[1]).resolve()
if os.getuid() == 0:
    raise SystemExit('An ordinary UID is required')
guest = str(work / 'tracer-guest')
records = []
original = 0x1020304050607080
changed = 0x8877665544332211


def run(label, command, env=None, witness=False):
    environment = {'PATH': '/usr/bin:/bin', 'HOME': str(work), 'TMPDIR': str(work), 'LC_ALL': 'C'}
    environment.update(env or {})
    with (work / (label + '.witness')).open('w+b') as report:
        if witness:
            environment.update(LD_PRELOAD=str(work / 'tracer-preload.so'),
                               FOLDGPT_TRACER_TEST_FD=str(report.fileno()))
        process = subprocess.Popen(command, env=environment, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, start_new_session=True,
                                   pass_fds=(report.fileno(),) if witness else ())
        try:
            stdout, stderr = process.communicate(timeout=15)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
            raise RuntimeError(f'{label} timed out: {stdout!r} {stderr!r}')
        report.seek(0)
        observed = report.read().decode()
    record = dict(label=label, command=command, returncode=process.returncode,
                  stdout=stdout.decode(), stderr=stderr.decode(), witness=observed)
    records.append(record)
    (work / 'tracer-observations.json').write_text(json.dumps(records, indent=2) + '\n')
    return record


scope = run('scope-only', [str(work / 'scope-admission')])
assert scope['returncode'] == 0 and 'cross_directory_rename=0' in scope['stdout'], scope
for mode in ('control', 'nested'):
    record = run('hierarchy-' + mode, [guest, 'hierarchy', mode])
    assert record['returncode'] == 0 and 'outer_domain=active' in record['stdout'] and 'parent_to_child=PASS' in record['stdout'], record
    assert 'cleanup=waitpid' in record['stdout'], record

for acceleration in (False, True):
    env = {} if acceleration else {'PROOT_NO_SECCOMP': '1'}
    for binary, strict in (('baseline', False), ('patched', False), ('patched', True)):
        mode = 'nested' if strict else 'control'
        command = [str(work / binary / 'src/proot'), '--kill-on-exit', '-r', '/']
        if strict:
            command += ['--strict-sandbox']
        command += [guest, 'guest', mode]
        record = run(f'proot-{binary}-{mode}-{int(acceleration)}', command, env, True)
        assert record['returncode'] == 0, record
        begin = re.findall(r'begin pid=(\d+) marker=(\d+) yama_relaxed=1', record['witness'])
        end = re.findall(r'end pid=(\d+) marker=(\d+)', record['witness'])
        assert len(begin) == len(end) == 1 and begin[0][0] == end[0][0], record
        assert int(begin[0][1]) == original and int(end[0][1]) == (original if strict else changed), record
        assert 'actual_proot_guest=' + ('DENIED' if strict else 'ALLOWED') in record['stdout'], record
    command = [guest, 'deny-bootstrap', str(work / 'patched/src/proot'), '--kill-on-exit',
               '--strict-sandbox', '-r', '/', '/bin/echo', 'UNPROTECTED_GUEST_STARTED']
    record = run('bootstrap-refused-' + str(int(acceleration)), command, env)
    assert record['returncode'] != 0 and 'UNPROTECTED_GUEST_STARTED' not in record['stdout'], record
    assert 'strict guest Landlock tracer scope' in record['stderr'], record

result = {'status': 'PASS', 'uid': os.getuid(), 'cases': len(records),
          'scope': 'host scope-only hierarchy and controlled PRoot marker, both acceleration modes; no Android execution',
          'observations': records}
(work / 'tracer-verification.json').write_text(json.dumps(result, indent=2) + '\n')
print(f'PASS: {len(records)} native tracer protection cases under uid {os.getuid()}')
