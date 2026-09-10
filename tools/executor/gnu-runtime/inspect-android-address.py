"""Read native ELF load spans; run only the installed PRoot --version.

Separate read-only loader diagnostic; never changes executor permissions,
installs a package, or runs a guest command.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import struct
import subprocess
import sys


def load_span(path,page):
    with open(path,'rb') as stream:
        header=stream.read(64)
        if header[:6]!=b'\x7fELF\x02\x01':raise ValueError('Expected native ELF64')
        offset=struct.unpack_from('<Q',header,32)[0]
        size,count=struct.unpack_from('<HH',header,54)
        if size!=56:raise ValueError('Unexpected program header size')
        segments=[]
        for index in range(count):
            stream.seek(offset+index*size)
            kind,flags,file_offset,virtual,physical,filesz,memsz,align=struct.unpack('<IIQQQQQQ',stream.read(56))
            if kind==1:segments.append((virtual,memsz,align))
        if not segments:raise ValueError('No native load segments')
        lower=min(v//page*page for v,m,a in segments)
        upper=max((v+m+page-1)//page*page for v,m,a in segments)
        return {'loadSpanBytes':upper-lower,'maxAlignment':max(a for v,m,a in segments)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proot',type=Path,required=True)
    parser.add_argument('--capacity-source',type=Path,required=True)
    parser.add_argument('--address-space-bytes',type=int)
    args=parser.parse_args()
    sys.path.insert(0,str(args.capacity_source))
    from gnu_runtime_capacity import runtime_fd_admission
    admission=runtime_fd_admission(args.proot)
    page=os.sysconf('SC_PAGE_SIZE')
    spans={path:load_span(path,page) for path in admission['dependencies']}
    print(json.dumps({'pageSize':page,'fdCapacity':admission['capacity'],
        'libraryCount':len(spans),'totalLoadSpanBytes':sum(s['loadSpanBytes'] for s in spans.values()),
        'totalAlignmentBytes':sum(s['maxAlignment'] for s in spans.values()),
        'libraries':spans},indent=2),flush=True)
    if args.address_space_bytes is not None:
        def limit():
            resource.setrlimit(resource.RLIMIT_NOFILE,(admission['capacity'],admission['capacity']))
            resource.setrlimit(resource.RLIMIT_AS,(args.address_space_bytes,args.address_space_bytes))
        native=args.proot.parent
        result=subprocess.run([str(args.proot),'--version'],env={'LD_PRELOAD':str(native/'libtalloc.so'),
            'LD_LIBRARY_PATH':str(native),'PATH':'/system/bin'},preexec_fn=limit,capture_output=True,timeout=15)
        print(json.dumps({'addressSpaceBytes':args.address_space_bytes,'versionExit':result.returncode,
            'stdout':result.stdout.decode(errors='replace'),'stderr':result.stderr.decode(errors='replace')}),flush=True)


if __name__=='__main__':main()
