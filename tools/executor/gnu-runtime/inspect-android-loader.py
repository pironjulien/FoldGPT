"""Read observed system ELF dependencies; optionally run only PRoot --version.

No guest command or policy is weakened. The version probe is a separate native
loader diagnostic, using the installed executable and a specified FD ceiling.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import resource
import struct
import subprocess


def needed(path):
    with open(path, 'rb') as stream:
        header = stream.read(64)
        if header[:6] != b'\x7fELF\x02\x01':
            raise ValueError('Expected little endian ELF64')
        phoff = struct.unpack_from('<Q', header, 32)[0]
        phsize, phnum = struct.unpack_from('<HH', header, 54)
        loads, dynamic = [], None
        for index in range(phnum):
            stream.seek(phoff + index * phsize)
            kind, flags, offset, virtual, physical, filesz, memsz, align = struct.unpack('<IIQQQQQQ', stream.read(56))
            if kind == 1: loads.append((virtual, offset, filesz))
            if kind == 2: dynamic = (offset, filesz)
        if dynamic is None: return []
        stream.seek(dynamic[0]); data = stream.read(dynamic[1])
        strings, names = None, []
        for at in range(0, len(data), 16):
            tag, value = struct.unpack_from('<qQ', data, at)
            if tag == 0: break
            if tag == 1: names.append(value)
            if tag == 5: strings = value
        if strings is None: return []
        base = next(offset + strings - virtual for virtual, offset, size in loads if virtual <= strings < virtual + size)
        result=[]
        for name in names:
            stream.seek(base+name)
            result.append(stream.read(512).split(b'\0',1)[0].decode())
        return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--proot',type=Path,required=True)
    parser.add_argument('--fd-limit',type=int)
    args=parser.parse_args()
    native=args.proot.parent
    directories=[native,Path('/system/lib64'),Path('/system_ext/lib64'),
        Path('/apex/com.android.runtime/lib64/bionic'),Path('/apex/com.android.i18n/lib64'),
        Path('/apex/com.android.art/lib64'),Path('/apex/com.android.tethering/lib64')]
    pending=[args.proot];seen={};missing=set()
    while pending:
        path=pending.pop()
        if str(path) in seen:continue
        deps=needed(path);seen[str(path)]=deps
        for name in deps:
            if name=='libtalloc.so.2':name='libtalloc.so'
            found=next((directory/name for directory in directories if (directory/name).is_file()),None)
            if found:pending.append(found)
            else:missing.add(name)
    print(json.dumps({'resolvedLibraries':len(seen),'missing':sorted(missing),'fdLimit':resource.getrlimit(resource.RLIMIT_NOFILE),
        'dependencies':seen},indent=2),flush=True)
    if args.fd_limit is not None:
        def limit():resource.setrlimit(resource.RLIMIT_NOFILE,(args.fd_limit,args.fd_limit))
        result=subprocess.run([str(args.proot),'--version'],env={'LD_PRELOAD':str(native/'libtalloc.so'),
            'LD_LIBRARY_PATH':str(native),'PATH':'/system/bin'},preexec_fn=limit,capture_output=True,timeout=15)
        print(json.dumps({'versionExit':result.returncode,'stdout':result.stdout.decode(errors='replace'),
                          'stderr':result.stderr.decode(errors='replace')}))


if __name__=='__main__':main()
