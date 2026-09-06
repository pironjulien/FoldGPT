"""Replace the known obsolete developer URL adapter, preserving Debian's opener.

Requires authorized ADB and the debug installation. Fresh installs use the
authenticated guest bundle instead. Refuses an unknown existing adapter.
"""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import uuid

LEGACY=b'#!/bin/sh\nexec /data/data/com.termux/files/usr/bin/termux-open-url "$@"\n'
TARGET='files/debian/usr/local/bin/xdg-open'

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    args=parser.parse_args()
    adb=['adb','-s',args.serial]
    data=Path(__file__).with_name('foldgpt-open.py').read_bytes().replace(b'\r\n',b'\n')
    previous=subprocess.check_output(adb+['exec-out','run-as','app.foldgpt','cat',TARGET])
    if previous not in (LEGACY,data): raise RuntimeError('Unknown existing URL adapter; review it before replacing')
    digest=lambda value:hashlib.sha256(value).hexdigest()
    if previous==data:
        print('Already deployed: '+digest(data)); return
    evidence=Path(__file__).resolve().parents[2]/'downloads/browser'/('opener-'+uuid.uuid4().hex)
    evidence.mkdir(parents=True)
    (evidence/'previous-xdg-open').write_bytes(previous)
    (evidence/'new-xdg-open').write_bytes(data)
    staging=TARGET+'.foldgpt-'+uuid.uuid4().hex
    script=f'''set -eu
test ! -L {TARGET}
test -f {TARGET}
test "$(sha256sum {TARGET} | cut -d ' ' -f 1)" = {digest(previous)}
set -C
cat > {staging}
test "$(sha256sum {staging} | cut -d ' ' -f 1)" = {digest(data)}
chmod 755 {staging}
sync -f {staging}
mv -f {staging} {TARGET}
sync -f files/debian/usr/local/bin
'''
    subprocess.run(adb+['shell','run-as app.foldgpt sh -c '+shlex.quote(script)],input=data,check=True)
    actual=subprocess.check_output(adb+['exec-out','run-as','app.foldgpt','cat',TARGET])
    if actual!=data: raise RuntimeError('Deployed opener differs from source')
    print('Verified URL adapter: '+digest(data))
    print('Previous adapter preserved: '+str(evidence))

if __name__=='__main__': main()
