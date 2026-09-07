"""Real official app-server handshake with the native Android GNU broker.

Creates a private diagnostic profile and invokes no account, thread or model
method. The GNU bridge connects to the separately running native service.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from tools.executor.verify_official_environment import Peer, SHA256


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--parent',type=Path,required=True)
    parser.add_argument('--bridge',type=Path,required=True)
    parser.add_argument('--socket',required=True)
    parser.add_argument('--uid',type=int,required=True)
    args=parser.parse_args()
    official=Path('/usr/lib/chatgpt/resources/codex')
    if hashlib.sha256(official.read_bytes()).hexdigest()!=SHA256:
        raise RuntimeError('Official executable differs from reviewed version')
    work=Path(tempfile.mkdtemp(prefix='official-gnu-',dir=args.parent.resolve(strict=True)))
    for name in ('home','codex','tmp','config','cache','state'):(work/name).mkdir(mode=0o700)
    config=('default = "foldgpt-native"\ninclude_local = true\n[[environments]]\n'
        'id = "foldgpt-native"\nprogram = '+json.dumps(str(args.bridge.resolve(strict=True)))+'\n'
        'args = '+json.dumps(['--socket',args.socket,'--peer-uid',str(args.uid)])+'\n'
        'cwd = "/workspace"\ninitialize_timeout_sec = 30\n')
    (work/'codex/environments.toml').write_text(config)
    environment={'PATH':'/usr/bin:/bin','HOME':str(work/'home'),'CODEX_HOME':str(work/'codex'),
        'TMPDIR':str(work/'tmp'),'XDG_CONFIG_HOME':str(work/'config'),'XDG_CACHE_HOME':str(work/'cache'),
        'XDG_STATE_HOME':str(work/'state'),'LANG':'C.UTF-8'}
    adapter=Path(__file__).parents[1]/'app_server_adapter.py'
    command=['/usr/bin/python3','-B',str(adapter),'--official',str(official),
        '--environment','foldgpt-native','--cwd','/workspace','--','app-server','--listen','stdio://']
    report={'scope':'Real official GNU environment handshake; no model or normal UI acceptance',
        'officialSha256':SHA256,'work':str(work),'status':'FAIL'}
    with (work/'stderr.log').open('wb') as errors:
        process=subprocess.Popen(command,env=environment,cwd='/workspace',stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=errors,close_fds=True)
        peer=Peer(process)
        try:
            peer.send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'foldgpt_native_gnu_probe','version':'1'},
                'capabilities':{'experimentalApi':False}}})
            initialized=peer.receive(1)
            if initialized['codexHome']!=str(work/'codex'):raise RuntimeError('Diagnostic profile mismatch')
            peer.send({'method':'initialized','params':{}})
            peer.send({'id':2,'method':'environment/info','params':{'environmentId':'foldgpt-native'}})
            info=peer.receive(2)
            if info['cwd']!='file:///workspace' or info['shell']!={'name':'bash','path':'/bin/bash'}:
                raise RuntimeError('GNU environment metadata differs')
            # app-server v0.153.4 projects exec-server EnvironmentInfo to just
            # shell and cwd. Home/temp belong to the lower transport contract.
            if set(info)!={'shell','cwd'}:
                raise RuntimeError('Official environment projection differs')
            peer.send({'id':3,'method':'environment/status','params':{'environmentId':'foldgpt-native'}})
            status=peer.receive(3)
            if status!={'status':'ready'}:raise RuntimeError('GNU environment is not ready')
            process.stdin.close();process.wait(timeout=25)
            if process.returncode:raise RuntimeError('Official adapter did not shut down')
            report.update(status='PASS',environmentInfo=info,environmentStatus=status,requests=peer.requests,exitCode=0)
        finally:
            peer.selector.close()
            if process.poll() is None:
                process.terminate()
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
            (work/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
