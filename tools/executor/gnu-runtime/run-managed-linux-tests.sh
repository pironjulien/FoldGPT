#!/usr/bin/env bash
set -euo pipefail
if [[ $# != 1 || $1 != /* || ! -x $1 ]]; then
  echo 'usage: run-managed-linux-tests.sh /absolute/path/to/strict-proot' >&2
  exit 2
fi
if [[ $(id -u) == 0 ]]; then
  echo 'Run the actual integration suite as an ordinary non-root UID.' >&2
  exit 2
fi
proot=$1
repository=$(cd "$(dirname "$0")/../../.." && pwd)
work=$(mktemp -d /var/tmp/foldgpt-gnu-managed-XXXXXXXX)
python3 - "$repository" "$work" <<'PY'
from pathlib import Path
import shutil,sys
source=Path(sys.argv[1]);target=Path(sys.argv[2])/'sources'
for subdir in ('tools/executor','tools/policy','tools/executor/gnu-runtime'):
    for path in (source/subdir).iterdir():
        if path.is_file() and path.suffix in ('.py','.c','.h','.json','.sh','.md'):
            destination=target/path.relative_to(source)
            destination.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(path,destination)
PY
cd "$work/sources/tools/executor/gnu-runtime"
python3 prepare-managed-gnu.py
cc -O2 -Wall -Wextra -Werror gnu-managed-runner.c -o "$work/runner"
cc -O2 -Wall -Wextra -Werror ../native-files.c -o "$work/files-helper"
python3 -B test_gnu_process_adapter.py --runner "$work/runner" --files-helper "$work/files-helper" \
  --proot "$proot" --parent "$work" --evidence "$work/report.json" > "$work/tests.log" 2>&1
python3 - "$work" "$proot" <<'PY'
from pathlib import Path
import hashlib,json,os,platform,subprocess,sys
work=Path(sys.argv[1]);proot=Path(sys.argv[2])
files={str(p.relative_to(work)):hashlib.sha256(p.read_bytes()).hexdigest()
       for p in work.rglob('*') if p.is_file()}
manifest={'schema':'foldgpt.gnu-managed-host.v1','uid':os.getuid(),'kernel':platform.release(),
    'compiler':subprocess.check_output(['cc','--version'],text=True).splitlines()[0],
    'proot':str(proot),'prootSha256':hashlib.sha256(proot.read_bytes()).hexdigest(),'files':files}
(work/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
report=json.loads((work/'report.json').read_text())
assert report['status']=='PASS' and report['uid']==os.getuid()
print(json.dumps({'status':'PASS','evidence':str(work),'observations':len(report['observations'])}))
PY
