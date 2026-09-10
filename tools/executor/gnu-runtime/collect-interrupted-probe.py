"""Read-only evidence from the fixed interrupted GNU diagnostic, never reruns it."""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--fixture',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'cache/gm-[0-9]+',args.fixture):raise ValueError('Fixed GNU fixture required')
    args.output.mkdir(parents=True,exist_ok=False)
    adb=['adb','-s',args.serial]
    def read(argv):
        result=subprocess.run(adb+['exec-out',shlex.join(argv)],capture_output=True,timeout=15)
        if len(result.stdout)>4*1024*1024:raise ValueError('Incident evidence exceeded limit')
        return result
    observations={}
    for name,argv in {
        'uptime':['cat','/proc/uptime'], 'bootReason':['getprop','sys.boot.reason'],
        'warrantyBit':['getprop','ro.boot.warranty_bit'],
        'verifiedBoot':['getprop','ro.boot.verifiedbootstate'],
        'flashLocked':['getprop','ro.boot.flash.locked'], 'selinux':['getenforce'],
        'memory':['cat','/proc/meminfo'], 'processes':['ps','-A','-o','UID,PID,PPID,NAME'],
        'services':['dumpsys','activity','services','app.foldgpt'],
        'installedApk':['pm','path','app.foldgpt'],
        'inventory':['run-as','app.foldgpt','find',args.fixture+'/cases','-type','f'],
        'output':['run-as','app.foldgpt','cat',args.fixture+'/fixture-output.txt'],
        'context':['run-as','app.foldgpt','cat',args.fixture+'/android-context-before.json'],
    }.items():
        result=read(argv)
        (args.output/(name+'.txt')).write_bytes(result.stdout)
        observations[name]={'returncode':result.returncode,'sha256':hashlib.sha256(result.stdout).hexdigest(),
            'bytes':len(result.stdout),'stderr':result.stderr.decode(errors='replace')}
    inventory=(args.output/'inventory.txt').read_text().splitlines()
    artifact_hashes={}
    for name in inventory:
        if not re.fullmatch(re.escape(args.fixture)+r'/cases/gnu-rpc-[a-z0-9_]+/workspace/project/(app/(maths|__main__)\.py|test\.py)',name):continue
        result=read(['run-as','app.foldgpt','cat',name])
        if result.returncode:raise ValueError('Retained source read failed')
        local=args.output/'project'/name.split('/workspace/project/',1)[1]
        local.parent.mkdir(parents=True,exist_ok=True);local.write_bytes(result.stdout)
        artifact_hashes[str(local.relative_to(args.output))]=hashlib.sha256(result.stdout).hexdigest()
    report={'status':'INTERRUPTED','observedAt':datetime.now(timezone.utc).isoformat(),
        'fixture':args.fixture,'observations':observations,'artifacts':artifact_hashes,
        'scope':'Read-only reboot incident collection; no historical completion or causal proof'}
    (args.output/'incident.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({'status':report['status'],'output':str(args.output),'artifacts':len(artifact_hashes)}))


if __name__=='__main__':main()
