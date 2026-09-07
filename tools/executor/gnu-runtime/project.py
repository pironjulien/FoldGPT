"""A real offline GNU project build run inside the protected PRoot process tree."""
import ctypes
import errno
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

assert os.getuid() != 0
libc = ctypes.CDLL(None, use_errno=True)
libc.prctl.restype = ctypes.c_int
assert libc.prctl(39, 0, 0, 0, 0) == 1, 'Actual no_new_privs must remain enabled'
assert libc.prctl(21, 0, 0, 0, 0) == 2, 'Native seccomp filter must remain installed'

denials = []
for name, action in (
    ('outside-file-read', lambda: Path('/outside/victim.txt').read_bytes()),
    ('workspace-symlink-outside-read', lambda: Path('/foldgpt-fixture/outside-link/victim.txt').read_bytes()),
    ('actual-proc-environment-read', lambda: Path('/proc/self/environ').read_bytes()),
    ('outside-file-write', lambda: Path('/outside/victim.txt').write_text('forbidden')),
    ('outside-mode-change', lambda: os.chmod('/outside/victim.txt', 0o777)),
    ('external-network-socket', lambda: socket.socket(socket.AF_INET, socket.SOCK_STREAM)),
):
    try:
        result = action()
    except OSError as error:
        assert error.errno in (errno.EACCES, errno.EPERM), (name, error)
        denials.append({'name': name, 'errno': error.errno})
    else:
        raise RuntimeError(f'Required kernel protection did not deny {name}: {result!r}')

ctypes.set_errno(0)
assert libc.unshare(0x40000000) == -1 and ctypes.get_errno() == errno.EPERM, 'Network namespace denied by inherited filter'
denials.append({'name':'network-namespace-unshare', 'errno':ctypes.get_errno()})
ctypes.set_errno(0)
assert libc.prctl(4, 0, 0, 0, 0) == -1 and ctypes.get_errno() == errno.EOPNOTSUPP, 'Strict PRoot must report unsupported dumpability protection honestly'
denials.append({'name':'unsupported-pr-set-dumpable', 'errno':ctypes.get_errno()})

project = Path('/tmp/project')
project.mkdir(mode=0o700)
(project/'dist').mkdir(mode=0o700)
(project/'app').mkdir(mode=0o700)
(project/'app'/'maths.py').write_text('def doubled(value):\n    return value + value\n')
(project/'app'/'__main__.py').write_text('from maths import doubled\nprint(f"native GNU project: {doubled(21)}")\n')
(project/'test_maths.py').write_text('''import sys
import unittest
sys.path.insert(0, 'app')
from maths import doubled
class MathsTests(unittest.TestCase):
    def test_positive(self): self.assertEqual(doubled(21), 42)
    def test_zero(self): self.assertEqual(doubled(0), 0)
    def test_negative(self): self.assertEqual(doubled(-8), -16)
if __name__ == '__main__': unittest.main()
''')
# Bash and GNU Python are real guest ELF executables, launched through strict
# PRoot. The source edit, bytecode compilation, tests, package and execution are
# recorded as actual artifacts in the physical scratch directory.
script = '''set -euo pipefail
test "$PWD" = /tmp/project
python3 -c "from pathlib import Path; p=Path('app/maths.py'); p.write_text(p.read_text().replace('value + value', 'value * 2'))"
python3 -m py_compile app/maths.py app/__main__.py test_maths.py
python3 -m unittest discover -v
python3 -m zipapp app -o dist/app.pyz
python3 dist/app.pyz > dist/result.txt
python3 -c "from pathlib import Path; assert Path('dist/result.txt').read_text() == 'native GNU project: 42\\n'"
'''
result = subprocess.run(['/bin/bash', '-c', script], cwd=project, text=True, capture_output=True, timeout=40)
(project/'build.stdout').write_text(result.stdout)
(project/'build.stderr').write_text(result.stderr)
if result.returncode:
    print(result.stdout, end='')
    print(result.stderr, file=sys.stderr, end='')
    raise RuntimeError(f'Actual GNU project build failed: {result.returncode}')
assert 'Ran 3 tests' in result.stderr and '\nOK\n' in result.stderr
assert (project/'dist/result.txt').read_text() == 'native GNU project: 42\n'
assert 'value * 2' in (project/'app/maths.py').read_text()
assert (project/'dist/app.pyz').read_bytes().startswith(b'PK')
nonzero = subprocess.run(['/bin/bash', '-c', 'exit 23'], capture_output=True)
assert nonzero.returncode == 23, nonzero.returncode
report = {'status':'PASS', 'uid':os.getuid(), 'python':sys.version, 'machine':os.uname().machine,
          'tests':3, 'buildExit':result.returncode, 'nonzeroExit':nonzero.returncode, 'denials':denials,
          'artifacts':{str(p.relative_to(project)):hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted(project.rglob('*')) if p.is_file()}}
(project/'report.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps({'status':'PASS', 'project':'/tmp/project', 'tests':3, 'denials':len(denials)}))
