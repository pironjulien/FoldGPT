"""Capacity for the immutable native PRoot loader, never a guest policy grant.

Bionic keeps one FD per newly found DT_NEEDED library in LoadTask until the
complete find_libraries scope ends. Reserve the existing 128 process handles
plus the actual APK/system dependency closure; never hardcode a Fold OS count.
"""
import os
from pathlib import Path
import resource
import struct
import sys

BASE_PROCESS_FDS = 128


def elf_dynamic(path):
    """Read a native ELF64 dependency table with file-backed bounds checks."""
    with open(path,'rb') as stream:
        info=os.fstat(stream.fileno())
        def read(offset,size):
            if offset<0 or size<0 or offset>info.st_size or size>info.st_size-offset:
                raise ValueError('Native ELF table exceeds its actual file')
            stream.seek(offset);value=stream.read(size)
            if len(value)!=size:raise ValueError('Native ELF changed while reading')
            return value
        header=read(0,64)
        if header[:6]!=b'\x7fELF\x02\x01':raise ValueError('Expected native little-endian ELF64')
        phoff=struct.unpack_from('<Q',header,32)[0]
        phsize,phnum=struct.unpack_from('<HH',header,54)
        if phsize!=56 or not phnum:raise ValueError('Unsupported native ELF program headers')
        loads=[];dynamic=None
        for index in range(phnum):
            kind,flags,offset,virtual,physical,filesz,memsz,align=struct.unpack('<IIQQQQQQ',read(phoff+index*phsize,56))
            if kind==1:loads.append((virtual,offset,filesz))
            if kind==2:
                if dynamic is not None:raise ValueError('Duplicate native ELF dynamic table')
                dynamic=(offset,filesz)
        if dynamic is None:return {'needed':[],'soname':None,'stat':(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)}
        data=read(*dynamic);strings=None;string_size=None;needed=[];soname=None;terminated=False
        if len(data)%16:raise ValueError('Incomplete native ELF dynamic entry')
        for at in range(0,len(data),16):
            tag,value=struct.unpack_from('<qQ',data,at)
            if tag==0:terminated=True;break
            if tag==1:needed.append(value)
            elif tag==5:strings=value
            elif tag==10:string_size=value
            elif tag==14:soname=value
        if not terminated or strings is None or string_size is None:raise ValueError('Incomplete native dynamic string table')
        segment=next(((offset+strings-virtual,filesz-(strings-virtual)) for virtual,offset,filesz in loads if virtual<=strings<virtual+filesz),None)
        if segment is None or string_size>segment[1]:raise ValueError('Native dynamic strings are not file-backed')
        table=read(segment[0],string_size)
        def name(index):
            end=table.find(b'\0',index)
            if index>=len(table) or end<0:raise ValueError('Invalid native library name')
            value=table[index:end].decode('utf-8')
            if not value or '/' in value or value in ('.','..'):raise ValueError('Unsupported native library dependency path')
            return value
        current=os.fstat(stream.fileno())
        if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns):
            raise ValueError('Native runtime file changed during capacity admission')
        return {'needed':[name(index) for index in needed],'soname':name(soname) if soname is not None else None,
            'stat':(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)}


def android_dependency_closure(proot):
    native=Path(proot).resolve(strict=True).parent
    directories=[native,Path('/system/lib64'),Path('/system_ext/lib64'),
        Path('/apex/com.android.runtime/lib64/bionic'),Path('/apex/com.android.i18n/lib64'),
        Path('/apex/com.android.art/lib64'),Path('/apex/com.android.tethering/lib64')]
    # These are the same explicit native search roots as the GNU constructor.
    # Unknown platform dependency locations fail admission instead of guessing.
    preload=native/'libtalloc.so'
    preloaded=elf_dynamic(preload)
    if preloaded['soname']!='libtalloc.so.2':raise ValueError('Native talloc preload SONAME differs')
    aliases={preloaded['soname']:preload}
    pending=[Path(proot),preload];seen={}
    while pending:
        path=pending.pop().resolve(strict=True)
        if str(path) in seen:continue
        entry=elf_dynamic(path);seen[str(path)]=entry
        for name in entry['needed']:
            found=aliases.get(name)
            if found is None:found=next((directory/name for directory in directories if (directory/name).is_file()),None)
            if found is None:raise ValueError('Native runtime dependency is unresolved: '+name)
            pending.append(found)
    return seen


def runtime_fd_admission(proot):
    dependencies=android_dependency_closure(proot) if sys.platform=='android' else {}
    capacity=BASE_PROCESS_FDS+len(dependencies)
    soft,hard=resource.getrlimit(resource.RLIMIT_NOFILE)
    if any(value!=resource.RLIM_INFINITY and capacity>value for value in (soft,hard)):
        raise ValueError('Inherited descriptor ceiling cannot fit the immutable GNU runtime')
    return {'baseProcessCapacity':BASE_PROCESS_FDS,'nativeDependencyCount':len(dependencies),
        'capacity':capacity,'inheritedSoft':soft,'inheritedHard':hard,'dependencies':dependencies}
