"""Independently reread real host artifacts; never execute or repair evidence."""
import hashlib
import json
from pathlib import Path
import re
import sys

work = Path(sys.argv[1]).resolve(strict=True)
log = (work/'runtime.log').read_text()
match = re.search(r'independent_parent_verification=PASS evidence_directory=(.+)', log)
if not match:
    raise RuntimeError('Actual native independent verification absent')
case = Path(match.group(1)).resolve(strict=True)
if case.parent != work:
    raise RuntimeError('Fixture escaped the selected evidence directory')
assert 'owned_descendant_cleanup=PASS' in log
assert '=FAIL' not in log
project = case/'scratch/project'
report = json.loads((project/'report.json').read_text())
assert report['status'] == 'PASS' and report['uid'] != 0 and report['tests'] == 3
assert report['buildExit'] == 0 and report['nonzeroExit'] == 23
assert len(report['denials']) == 8
assert (project/'dist/result.txt').read_text() == 'native GNU project: 42\n'
assert (case/'outside/victim.txt').read_text() == 'Outside file remains intact\n'
assert (case/'outside/victim.txt').stat().st_mode & 0o777 == 0o600
assert (case/'workspace/.git/config').read_text() == 'Protected metadata remains intact\n'
assert 'Ran 3 tests' in (project/'build.stderr').read_text()
for name, expected in report['artifacts'].items():
    path = project/name
    if not path.resolve(strict=True).is_relative_to(project):
        raise RuntimeError('Invalid artifact path')
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError(f'Changed actual artifact: {name}')
summary = {'status':'PASS', 'scope':'independent host bytes and source hashes; historical process observations remain native fixture evidence',
           'case':str(case), 'uid':report['uid'], 'tests':report['tests'],
           'kernelDenials':len(report['denials']), 'verifiedProjectFiles':len(report['artifacts'])}
(work/'independent-verification.json').write_text(json.dumps(summary, indent=2)+'\n')
print(json.dumps(summary))
