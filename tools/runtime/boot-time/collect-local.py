"""Verify and export local test evidence without installing anything."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('work',type=Path)
parser.add_argument('destination',type=Path)
args=parser.parse_args()
work=args.work.resolve()
report=json.loads((work/'report.json').read_text())
assert report['status']=='PASS' and report['uid']>0
for rel,digest in report['artifacts'].items():
    assert hashlib.sha256((work/rel).read_bytes()).hexdigest()==digest,rel
for rel,digest in report['test_sources'].items():
    assert hashlib.sha256((work/'test-source'/rel).read_bytes()).hexdigest()==digest,rel
assert not args.destination.exists(), 'never overwrite existing evidence'
args.destination.mkdir(parents=True)
for rel in ['report.json','live-results.json',*report['artifacts'].keys()]:
    target=args.destination/rel
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(work/rel,target)
shutil.copytree(work/'test-source',args.destination/'test-source')
print(json.dumps({'exported':str(args.destination),'report_sha256':hashlib.sha256((args.destination/'report.json').read_bytes()).hexdigest()}))
