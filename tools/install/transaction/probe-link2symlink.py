"""Bounded host experiment against the existing pinned PRoot binary.

Runs real tracees under the current unprivileged UID; never modifies a rootfs,
the source tree or Android. Retains its private fixture and exact observations.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile


GUEST = r'''
import errno, json, os, stat, subprocess, sys
from pathlib import Path
root=Path(sys.argv[1]); operation=sys.argv[2]
a=root/'a'; b=root/'b'; c=root/'c'
def inspect(path):
    x=path.lstat()
    return {'type':'regular' if stat.S_ISREG(x.st_mode) else 'other',
            'dev':x.st_dev,'ino':x.st_ino,'nlink':x.st_nlink,'mode':stat.S_IMODE(x.st_mode),
            'data':path.read_text(), 'statx_nlink':subprocess.check_output(['/usr/bin/stat','-c','%h',str(path)],text=True).strip()}
if operation=='create':
    a.write_text('one\n'); os.link(a,b)
    data={'a':inspect(a),'b':inspect(b)}
    assert data['a']['ino']==data['b']['ino'] and data['a']['nlink']==data['b']['nlink']==2
    assert data['a']['type']==data['b']['type']=='regular'
    assert data['a']['statx_nlink']==data['b']['statx_nlink']=='2'
    print(json.dumps(data)); sys.exit(0)
if operation=='verify':
    x,y=inspect(a),inspect(b)
    assert x['ino']==y['ino'] and x['nlink']==y['nlink']==2 and x['type']==y['type']=='regular'
    with b.open('a') as f: f.write('two\n')
    assert a.read_text()=='one\ntwo\n'
    os.chmod(b,0o640); assert stat.S_IMODE(a.stat().st_mode)==0o640
    os.utime(b,ns=(1_000_000_000,3_123_456_789)); assert a.stat().st_mtime_ns==3_123_456_789
    os.rename(a,c); assert c.read_text()==b.read_text() and c.stat().st_ino==b.stat().st_ino
    os.unlink(b); assert c.lstat().st_nlink==1 and c.read_text()=='one\ntwo\n'
    os.unlink(c)
    print(json.dumps({'write_alias':True,'chmod_alias':True,'mtime_alias':True,'rename':True,'unlink_survivor':True,'unlink_last':True}));sys.exit(0)
if operation=='eexist':
    a.write_text('left'); b.write_text('right')
    try: os.link(a,b); raise AssertionError('link should refuse EEXIST')
    except FileExistsError: pass
    data={'a':inspect(a),'b':inspect(b)}
    assert data['a']['data']=='left' and data['b']['data']=='right'
    assert data['a']['nlink']==data['b']['nlink']==1
    print(json.dumps(data));sys.exit(0)
raise AssertionError('Unknown operation')
'''


def snapshot(root):
    entries=[]
    for p in sorted(root.iterdir()):
        s=p.lstat()
        entries.append({'name':p.name,'type':'symlink' if p.is_symlink() else 'regular',
                        'mode':stat.S_IMODE(s.st_mode),'nlink':s.st_nlink,'ino':s.st_ino,
                        **({'target':os.readlink(p)} if p.is_symlink() else {'bytes':p.read_text()})})
    return entries


def run(proot, talloc):
    if os.getuid()==0:
        raise ValueError('Use an ordinary unprivileged UID for this experiment')
    work=Path(tempfile.mkdtemp(prefix='foldgpt-l2s-probe-',dir='/var/tmp'))
    script=work/'guest.py';script.write_text(GUEST)
    environment=dict(os.environ,LD_LIBRARY_PATH=str(talloc),PROOT_TMP_DIR=str(work))
    environment.pop('PROOT_L2S_DIR',None)
    observations={'uid':os.getuid(),'work':str(work),'proot_sha256':hashlib.sha256(proot.read_bytes()).hexdigest(),'checks':[]}
    def guest(root,operation):
        child=subprocess.run([str(proot),'-l','/usr/bin/python3','-B',str(script),str(root),operation],
            capture_output=True,text=True,env=environment,timeout=30)
        observations['checks'].append({'fixture':root.name,'operation':operation,'exit':child.returncode,
            'stdout':child.stdout,'stderr':child.stderr,'host_after':snapshot(root)})
        (work/'result.json').write_text(json.dumps(observations,indent=2))
        if child.returncode:
            raise RuntimeError(f'{root.name}/{operation}: {child.stderr}; evidence {work}')
    generated=work/'generated';generated.mkdir();guest(generated,'create');guest(generated,'verify')
    assert snapshot(generated)==[], 'Guest final unlink left backing data'
    # Independent provisioner constructs exactly the three-link / one-data
    # representation observed in the pinned extension, without calling link().
    provisioned=work/'provisioned';provisioned.mkdir()
    backing=provisioned/'.l2s.a0001.0002';backing.write_text('one\n')
    intermediate=provisioned/'.l2s.a0001';intermediate.symlink_to(backing)
    (provisioned/'a').symlink_to(intermediate);(provisioned/'b').symlink_to(intermediate)
    observations['provisioned_initial']=snapshot(provisioned)
    guest(provisioned,'verify');assert snapshot(provisioned)==[]
    eexist=work/'eexist';eexist.mkdir();guest(eexist,'eexist')
    print(json.dumps(observations,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proot',required=True,type=Path);parser.add_argument('--talloc-dir',required=True,type=Path)
    args=parser.parse_args();run(args.proot,args.talloc_dir)
