"""Run actual GNU ps against real live children, with native Landlock refusal.

No LD_PRELOAD, procfs replacement, clock changes, mount or privilege escalation.
The kernel ABI fixture fails rather than skips if Landlock is unavailable.
"""
import datetime
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import time

work = Path(sys.argv[1])
assert os.getuid() != 0, 'live tests must run nonroot'
env = os.environ | {'LC_ALL':'C', 'TZ':'UTC'}
fields = 'pid=,ppid=,%cpu=,rss=,lstart=,command='
checks=[]

def run(which,pids,denied=False,extra=None):
    command = [str(work/which/'src/ps/.libs/pscommand'),'-p',','.join(map(str,pids)),'-o',fields]
    if extra:
        command.extend(extra)
    if denied:
        command.insert(0,str(work/'deny-proc-stat'))
    private_env=env | {'LD_LIBRARY_PATH':str(work/which/'library/.libs')}
    result=subprocess.run(command,env=private_env,capture_output=True,text=True,timeout=20)
    tag=f'{len(checks)+1:02d}-{which}-denied-{denied}'
    (work/(tag+'.stdout.log')).write_text(result.stdout)
    (work/(tag+'.stderr.log')).write_text(result.stderr)
    return result

def native_error_part(result):
    fixture='test-fixture: real /proc/stat EACCES; /proc/self/stat readable; uid='+str(os.getuid())+'\n'
    assert result.stderr.startswith(fixture),result.stderr
    return result.stderr[len(fixture):]

def rows(result):
    parsed={}
    for line in result.stdout.splitlines():
        match=re.fullmatch(r'\s*(\d+)\s+(\d+)\s+([0-9.]+)\s+(\d+)\s+(.{24})\s+(.*)',line)
        assert match,repr(line)
        pid,ppid,cpu,rss,start,command=match.groups()
        epoch=int(datetime.datetime.strptime(start,'%a %b %d %H:%M:%S %Y').replace(tzinfo=datetime.timezone.utc).timestamp())
        parsed[int(pid)]={'ppid':int(ppid),'cpu':float(cpu),'rss':int(rss),'start_epoch':epoch,'command':command}
    return parsed

before=time.time()
child=subprocess.Popen(['/usr/bin/sleep','30'],env=env)
try:
    after=time.time()
    ids=[os.getpid(),child.pid]
    baseline=run('source',ids)
    assert baseline.returncode==0 and baseline.stderr=='',baseline.stderr
    original=rows(baseline)
    assert set(original)==set(ids)
    checks.append('authenticated baseline: real parent/child sampled')

    denied=run('source',ids,True)
    assert denied.returncode!=0 and 'Unable to get system boot time' in native_error_part(denied)
    checks.append('baseline reproduces sampler failure under native /proc/stat EACCES')

    normal=run('patched',ids)
    assert normal.returncode==0 and normal.stderr=='',normal.stderr
    normal_rows=rows(normal)
    assert {p:r['start_epoch'] for p,r in original.items()}=={p:r['start_epoch'] for p,r in normal_rows.items()}
    checks.append('patched regular procfs: start times unchanged')

    fixed=run('patched',ids,True)
    assert fixed.returncode==0 and native_error_part(fixed)=='',fixed.stderr
    fixed_rows=rows(fixed)
    assert set(fixed_rows)==set(ids)
    for pid,row in fixed_rows.items():
        assert row['start_epoch']==original[pid]['start_epoch'],(row,original[pid])
        assert row['ppid']==original[pid]['ppid'] and row['rss']>0
        assert row['command']==original[pid]['command']
    assert fixed_rows[child.pid]['ppid']==os.getpid()
    assert math.floor(before)-1 <= fixed_rows[child.pid]['start_epoch'] <= math.floor(after)
    checks.append('patched real denied procfs: complete sampler output matches kernel btime baseline')

    # Start time survives later sampling; elapsed CPU and RSS may legitimately vary.
    time.sleep(1.1)
    repeated=run('patched',ids,True)
    assert repeated.returncode==0 and native_error_part(repeated)==''
    assert {p:r['start_epoch'] for p,r in rows(repeated).items()}=={p:r['start_epoch'] for p,r in fixed_rows.items()}
    checks.append('later real sampling preserves process start timestamps')

    invalid=run('patched',ids,False,['--definitely-invalid-option'])
    assert invalid.returncode!=0 and invalid.stderr
    checks.append('unrelated ps errors retain nonzero exit and stderr')
finally:
    child.terminate()
    child.wait(timeout=5)

report={'status':'PASS','uid':os.getuid(),'kernel':os.uname().release,'architecture':os.uname().machine,
        'live_test_count':len(checks),'live_tests':checks,'device_tested':False,
        'scope':'GNU ps x86_64 Linux under nonroot with real Landlock denial; not Android APK validation'}
(work/'live-results.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
