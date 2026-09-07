"""Actual nonroot GNU process RPCs, complete-policy decisions and lifecycle."""
import argparse
import asyncio
import base64
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0,str(Path(__file__).resolve().parents[3]))
from tools.executor.exec_server import BackendCall, RpcError, encode_message
from tools.executor.native_files import NativeFilesBackend
from tools.executor.native_processes import NativeProcessLimits
from gnu_process_adapter import GnuProcessesBackend


def context():
    return {'permissions':{'type':'managed','file_system':{'type':'restricted','entries':[
        {'path':{'type':'path','path':'file:///'},'access':'read'},
        {'path':{'type':'path','path':'file:///workspace'},'access':'write'},
        {'path':{'type':'path','path':'file:///workspace/readonly'},'access':'read'}]},'network':'restricted'},
        'cwd':'file:///workspace','workspaceRoots':['file:///workspace'],'useLegacyLandlock':False,
        'windowsSandboxLevel':'disabled','windowsSandboxPrivateDesktop':False}


async def main(options):
    assert os.getuid()!=0
    work=Path(tempfile.mkdtemp(prefix='gnu-rpc-',dir=options.parent))
    root=work/'workspace';root.mkdir(mode=0o700)
    home=root/'.home';home.mkdir(mode=0o700)
    (home/'.bash_profile').write_text('export FOLDGPT_LOGIN_PROFILE="actual workspace bash profile"\n')
    (home/'.bash_profile').chmod(0o600)
    scratch=work/'scratch';scratch.mkdir(mode=0o700)
    guest_tmp=work/'guest-tmp';guest_tmp.mkdir(mode=0o700)
    for name in ('.git','readonly'):(guest_tmp/name).mkdir(mode=0o700)
    for name in ('.git/config','readonly/value'):
        (guest_tmp/name).write_text('protected\n');(guest_tmp/name).chmod(0o600)
    for name in ('.git','readonly'):(root/name).mkdir(mode=0o700)
    for name in ('.git/config','readonly/value'):
        (root/name).write_text('protected\n');(root/name).chmod(0o600)
    files=NativeFilesBackend(options.files_helper,root)
    limits=lambda wall:NativeProcessLimits(wall_ms=wall,address_space_bytes=options.address_space_bytes)
    backend=GnuProcessesBackend(options.runner,root,proot=options.proot,rootfs=options.rootfs,
        loader=options.loader or options.proot.parent/'loader/loader',loader32=options.loader32 or options.proot.parent/'loader/loader-m32',scratch=scratch,
        guest_tmp=guest_tmp,files_backend=files,limits=limits(options.wall_ms),parent_environment={'PATH':'/usr/bin:/bin'})
    observations=[];notifications=[];sequence=0
    async def notify(method,params):notifications.append({'method':method,'params':params})
    async def call(method,params):
        nonlocal sequence
        sequence+=1
        return await backend.handle(BackendCall('gnu-session',sequence,method,encode_message(params)),notify)
    async def start(key,argv,**extra):
        params={'processId':key,'argv':argv,'cwd':'file:///workspace','env':{'PATH':'/usr/bin:/bin'},'tty':False,'sandbox':context(),**extra}
        try:return await call('process/start',params)
        except BaseException:
            if backend.failed:
                failed=backend.failed[-1]
                print('GNU setup:',failed.setup_diagnostic.decode(errors='replace'),failed.native_result,file=sys.stderr)
            raise
    async def completed(key):
        record=backend.processes[('gnu-session',key)]
        await asyncio.wait_for(asyncio.shield(record.finished),25)
        response=await call('process/read',{'processId':key})
        for stream in ('stdout','stderr'):
            (work/f'{key}.{stream}').write_bytes(b''.join(base64.b64decode(c['chunk']) for c in response['chunks'] if c['stream']==stream))
        print(key,response,file=sys.stderr)
        assert record.native_result['cleanupComplete'] is True,record.native_result
        assert response['closed'] is True and response['exited'] is True,response
        observations.append({'key':key,'response':response,'nativeStarted':record.native_started,'nativeResult':record.native_result,'supervisorIdentity':record.supervisor_identity})
        return response
    def output(response,stream='stdout'):
        return b''.join(base64.b64decode(c['chunk']) for c in response['chunks'] if c['stream']==stream)
    async def ready(key,expected=1):
        deadline=asyncio.get_running_loop().time()+options.wall_ms/1000
        cursor=0;received=b''
        while asyncio.get_running_loop().time()<deadline:
            response=await call('process/read',{'processId':key,'waitMs':100,'afterSeq':cursor})
            cursor=response['nextSeq']-1;received+=output(response)
            if sum(line.startswith(b'READY') for line in received.splitlines(keepends=True) if line.endswith(b'\n'))>=expected:return received
            if response['closed']:break
        raise RuntimeError('Actual GNU process did not report readiness')
    try:
        source='''from pathlib import Path
import compileall, zipapp, subprocess, sys, os, resource
assert os.environ['FOLDGPT_LOGIN_PROFILE']=='actual workspace bash profile'
assert os.environ['HOME']=='/workspace/.home'
assert os.getcwd()=='/workspace'
assert resource.getrlimit(resource.RLIMIT_NOFILE)==(EXPECTED_FDS,EXPECTED_FDS)
p=Path('project');p.mkdir()
(p/'app').mkdir();(p/'dist').mkdir()
(p/'app'/'maths.py').write_text('def doubled(n): return n + n\\n')
(p/'app'/'maths.py').write_text('def doubled(n): return n * 2\\n')
(p/'app'/'__main__.py').write_text('from maths import doubled\\nprint(doubled(21))\\n')
(p/'test.py').write_text('import sys,unittest\\nsys.path.insert(0,"app")\\nfrom maths import doubled\\nclass T(unittest.TestCase):\\n def test_positive(self): self.assertEqual(doubled(21),42)\\n def test_zero(self): self.assertEqual(doubled(0),0)\\n def test_negative(self): self.assertEqual(doubled(-2),-4)\\nunittest.main()\\n')
subprocess.run([sys.executable,'test.py'],cwd=p,check=True)
assert compileall.compile_dir(p,quiet=1)
zipapp.create_archive(p/'app',p/'dist'/'app.pyz')
result=subprocess.check_output([sys.executable,str(p/'dist'/'app.pyz')])
assert result==b'42\\n'
(p/'dist'/'temporary').write_bytes(result)
(p/'dist'/'temporary').rename(p/'dist'/'result')
(p/'obsolete').write_text('remove');(p/'obsolete').unlink()
print('GNU_MANAGED_PROJECT_PASS')
'''.replace('EXPECTED_FDS',str(backend.gnu_fd_admission['capacity']))
        await start('project',['/bin/bash','-lc','printf "actual null redirection" >/dev/null && /usr/bin/python3 -c "$1"','bash',source],env={'HOME':'/workspace/.home','PATH':'/usr/bin:/bin'})
        result=await completed('project')
        assert result['exitCode']==0 and result['failure'] is None,(result,output(result,'stderr'))
        assert b'Permission denied' not in output(result,'stderr') and b'Operation not supported' not in output(result,'stderr'),output(result,'stderr')
        assert b'GNU_MANAGED_PROJECT_PASS' in output(result)
        assert (root/'project/dist/result').read_bytes()==b'42\n'
        assert not (root/'project/obsolete').exists()
        policy_checks='''import os,errno
from pathlib import Path
checks=[lambda:Path('.git/config').write_text('bad'),lambda:Path('readonly/value').write_text('bad'),lambda:Path('readonly/newdir').mkdir(),lambda:Path('readonly/value').unlink(),lambda:Path('readonly/value').rename('stolen'),lambda:Path('.git/config').rename('config')]
for check in checks:
 try: check()
 except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM),e
 else: raise AssertionError('policy was bypassed')
print('FULL_POLICY_DENIALS_PASS')
'''
        await start('policy',['/usr/bin/python3','-c',policy_checks])
        result=await completed('policy');assert result['exitCode']==0 and b'FULL_POLICY_DENIALS_PASS' in output(result),result
        assert (root/'.git/config').read_text()=='protected\n' and (root/'readonly/value').read_text()=='protected\n'
        temp_denial='''import errno,os
from pathlib import Path
for path in ['/tmp/new-file','/tmp/readonly/value',INTERNAL+'/intrusion']:
 try: Path(path).write_text('unauthorized')
 except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM) or (path.startswith(INTERNAL+'/') and e.errno==errno.ENOENT),e
 else: raise AssertionError('temporary write was implicitly granted: '+path)
for path in ['/tmp/new-dir',INTERNAL+'/intrusion-dir']:
 try: Path(path).mkdir()
 except OSError as e: assert e.errno in (errno.EACCES,errno.EPERM) or (path.startswith(INTERNAL+'/') and e.errno==errno.ENOENT),e
 else: raise AssertionError('temporary mkdir was implicitly granted: '+path)
print('TEMP_NO_IMPLICIT_GRANT_PASS')
'''.replace('INTERNAL',repr(str(scratch)))
        await start('temp-denied',['/usr/bin/python3','-c',temp_denial])
        result=await completed('temp-denied');assert result['exitCode']==0 and b'TEMP_NO_IMPLICIT_GRANT_PASS' in output(result),result
        temp_policy=context()
        temp_policy['permissions']['file_system']['entries'] += [
            {'path':{'type':'path','path':'file:///tmp'},'access':'write'},
            {'path':{'type':'path','path':'file:///tmp/readonly'},'access':'read'}]
        temp_allowed='''import errno,tempfile
from pathlib import Path
p=Path(tempfile.mkdtemp(dir='/tmp'));(p/'value').write_text('real temp');(p/'value').rename(p/'renamed');(p/'renamed').unlink();p.rmdir()
checks=[lambda:Path('/tmp/readonly/value').write_text('bad'),lambda:Path('/tmp/.git/config').write_text('bad'),lambda:Path('/tmp/readonly/new').mkdir(),lambda:Path('/tmp/readonly/value').unlink(),lambda:Path('/tmp/readonly/value').rename('/tmp/stolen'),lambda:Path('/tmp/.git').rename('/tmp/stolen-git')]
for check in checks:
 try:check()
 except OSError as e:assert e.errno in (errno.EACCES,errno.EPERM),e
 else:raise AssertionError('temporary subpath policy was bypassed')
print('TEMP_COMPLETE_POLICY_PASS')
'''
        await start('temp-admitted',['/usr/bin/python3','-c',temp_allowed],sandbox=temp_policy)
        result=await completed('temp-admitted');assert result['exitCode']==0 and b'TEMP_COMPLETE_POLICY_PASS' in output(result),result
        assert (guest_tmp/'.git/config').read_text()=='protected\n' and (guest_tmp/'readonly/value').read_text()=='protected\n'
        await start('stdin',['/usr/bin/python3','-c','import os,sys; assert os.environ["EXACT"]=="one two"; assert os.environ["--chdir"]=="literal value"; assert "PROOT_TMP_DIR" not in os.environ; sys.stdout.buffer.write(sys.stdin.buffer.read(5)); sys.exit(23)'],pipeStdin=True,env={'EXACT':'one two','--chdir':'literal value'})
        await call('process/write',{'processId':'stdin','writeId':'native-input','chunk':base64.b64encode(b'\x00\xffABC').decode()})
        result=await completed('stdin');assert result['exitCode']==23 and output(result)==b'\x00\xffABC'
        denied=context();denied['permissions']['file_system']['entries'].append({'path':{'type':'path','path':'file:///workspace/secret'},'access':'deny'})
        before=len(backend.processes)
        try:await start('unsupported',['/bin/true'],sandbox=denied)
        except RpcError:pass
        else:raise AssertionError('Unsupported confidential metadata profile was admitted')
        assert len(backend.processes)==before
        await start('cancel',['/usr/bin/python3','-c','import os,time; pid=os.fork(); print("READY",os.getpid(),flush=True); time.sleep(100)'])
        await ready('cancel',2)
        await call('process/terminate',{'processId':'cancel'})
        result=await completed('cancel');assert result['failure'] is None
        for line in output(result).decode().splitlines():
            if line.startswith('READY '):
                try:os.kill(int(line.split()[1]),0)
                except ProcessLookupError:pass
                else:raise AssertionError('Cancelled GNU descendant still exists')
        backend.limits=limits(options.timeout_wall_ms)
        await start('timeout',['/usr/bin/python3','-c','import time; print("READY",flush=True); time.sleep(100)'])
        await ready('timeout')
        result=await completed('timeout')
        assert result['failure']=='Native process ended with timeout'
        sources={str(p.relative_to(Path(__file__).parent)):hashlib.sha256(p.read_bytes()).hexdigest()
            for p in Path(__file__).parent.iterdir() if p.suffix in ('.py','.c','.h')}
        report={'status':'PASS','uid':os.getuid(),'workspace':str(root),'observations':observations,'notifications':notifications,'sources':sources,
            'runtimeFdAdmission':backend.gnu_fd_admission,
            'scope':'actual GNU login shell and profile, native FD capacity, process wire and managed writes/mkdir/rename/unlink in workspace and temporary root; no implicit temp grant; root-read/no-DENY admission'}
        options.evidence.write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({'status':'PASS','tests':8,'workspace':str(root)}))
    finally:
        await backend.close('gnu-session')
        await files.close('gnu-session')


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ('runner','files-helper','proot','parent','evidence'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--rootfs',type=Path,default=Path('/'))
    parser.add_argument('--loader',type=Path)
    parser.add_argument('--loader32',type=Path)
    parser.add_argument('--address-space-bytes',type=int,default=NativeProcessLimits().address_space_bytes)
    parser.add_argument('--wall-ms',type=int,default=15000)
    parser.add_argument('--timeout-wall-ms',type=int,default=1500)
    args=parser.parse_args()
    asyncio.run(main(args))
