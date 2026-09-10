"""Stage only FoldGPT's diagnostic routing sources and packaged GNU bridge.

Uses a fresh app-private cache directory, checks exact APK identity and every
transferred byte. Does not edit the official client, account or normal profile.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import tempfile
import uuid
import zipfile


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--apk',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[2]
    adb=['adb','-s',args.serial]
    def command(*parts,app=True,data=None):
        argv=['run-as','app.foldgpt',*parts] if app else list(parts)
        result=subprocess.run(adb+['exec-out',shlex.join(argv)],input=data,capture_output=True,timeout=30)
        if result.returncode or result.stderr:raise RuntimeError('Staging command failed: '+parts[0])
        return result.stdout
    apk_path=command('pm','path','app.foldgpt',app=False).decode().strip()
    if not apk_path.startswith('package:/data/app/') or '\n' in apk_path:raise RuntimeError('Unexpected package identity')
    apk_path=apk_path.removeprefix('package:')
    digest=hashlib.sha256(args.apk.read_bytes()).hexdigest()
    if command('sha256sum',apk_path).split()[0].decode()!=digest:raise RuntimeError('Supplied APK is not installed')
    uid=int(command('id','-u'))
    if uid<=0:raise RuntimeError('Ordinary app UID required')
    name='fgroute-'+uuid.uuid4().hex
    remote='cache/x11/'+name
    command('mkdir','-m','700',remote)
    sources=('tools/executor/app_server_adapter.py','tools/executor/app_server_routing.py',
        'tools/executor/exec_server.py','tools/executor/verify_official_environment.py',
        'tools/executor/gnu-runtime/verify_official_gnu_environment.py')
    files={name:(root/name).read_bytes() for name in sources}
    with zipfile.ZipFile(args.apk) as apk:files['gnu-bridge']=apk.read('lib/arm64-v8a/libfoldgpt-exec-bridge.so')
    hashes={}
    for relative,data in files.items():
        target=remote+'/'+relative
        command('mkdir','-p',str(PurePosixPath(target).parent))
        # adb sync is the binary input transport; exec-out is output-only on
        # the current ADB build. Staged inputs contain code, never credentials.
        transfer='/data/local/tmp/'+name+'-'+uuid.uuid4().hex
        with tempfile.TemporaryDirectory(prefix='foldgpt-route-') as temporary:
            payload=Path(temporary)/'payload';payload.write_bytes(data)
            pushed=subprocess.run(adb+['push',str(payload),transfer],capture_output=True,timeout=30)
            if pushed.returncode:raise RuntimeError('Routing source push failed')
            try:
                command('chmod','644',transfer,app=False)
                command('cp',transfer,target)
            finally:
                command('rm',transfer,app=False)
        command('chmod','700' if relative=='gnu-bridge' else '600',target)
        if command('cat',target)!=data:raise RuntimeError('Staged bytes changed')
        hashes[relative]=hashlib.sha256(data).hexdigest()
    report={'remote':remote,'guest':'/tmp/'+name,'uid':uid,'apkSha256':digest,'sources':hashes,
        'scope':'Fresh diagnostic sources only; no profile or official client modified'}
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'stage.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
