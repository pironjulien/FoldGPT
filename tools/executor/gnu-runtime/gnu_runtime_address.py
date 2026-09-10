"""Explicit native GNU address-space budget from measured ELF/runtime geometry.

This returns a proposal for NativeProcessLimits, never increases a received
limit silently. Filesystem policies, Scudo, CFI and library ASLR stay intact.
Reviewed Bionic geometry and real Fold syscall evidence are documented in
android-scudo-address.md. Unsupported page/ELF geometry fails admission.
"""
import os
from pathlib import Path
import resource
import struct
import sys

from gnu_runtime_capacity import android_dependency_closure

SCUDO_CLASSES=33
SCUDO_REGION_BYTES=1<<28
WORKLOAD_ADDRESS_HEADROOM=1<<28
CFI_SHADOW_BYTES=1<<31
LIBRARY_ALIGNMENT=1<<18
LIBRARY_GAP_ALIGNMENT=1<<21
MAX_GAP_UNITS=31
MAX_DECLARED_ADDRESS_SPACE=1<<34


def elf_load_span(path,page):
    with open(path,'rb') as stream:
        info=os.fstat(stream.fileno())
        def read(offset,size):
            if offset<0 or size<0 or offset>info.st_size or size>info.st_size-offset:
                raise ValueError('Native load table exceeds file bounds')
            stream.seek(offset);data=stream.read(size)
            if len(data)!=size:raise ValueError('Native load table changed')
            return data
        header=read(0,64)
        if header[:6]!=b'\x7fELF\x02\x01':raise ValueError('Expected native little-endian ELF64')
        offset=struct.unpack_from('<Q',header,32)[0]
        size,count=struct.unpack_from('<HH',header,54)
        if size!=56 or not count:raise ValueError('Unexpected program header table')
        segments=[]
        for index in range(count):
            kind,flags,file_offset,virtual,physical,filesz,memsz,align=struct.unpack('<IIQQQQQQ',read(offset+index*size,56))
            if kind==1:
                if filesz>memsz or align<page or align&(align-1) or virtual+memsz>=1<<64:
                    raise ValueError('Unsupported native load geometry')
                segments.append((virtual,memsz,align))
        if not segments:raise ValueError('No native load segments')
        lower=min(v//page*page for v,m,a in segments)
        upper=max((v+m+page-1)//page*page for v,m,a in segments)
        alignment=max(a for v,m,a in segments)
        if alignment>LIBRARY_GAP_ALIGNMENT:raise ValueError('Unreviewed native ELF alignment')
        current=os.fstat(stream.fileno())
        if (info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)!=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns):
            raise ValueError('Native runtime changed during load-span inspection')
        span=upper-lower
        return {'loadSpanBytes':span,'maxAlignment':alignment,
            'gapEligible':span>LIBRARY_ALIGNMENT or alignment==LIBRARY_GAP_ALIGNMENT}


def runtime_address_admission(proot):
    if sys.platform!='android':
        return {'schema':'foldgpt.gnu-address-admission.v1','addressSpaceBytes':WORKLOAD_ADDRESS_HEADROOM,
            'workloadHeadroomBytes':WORKLOAD_ADDRESS_HEADROOM,'nativeLibraries':{}}
    if os.uname().machine!='aarch64':raise ValueError('GNU native address geometry requires reviewed ARM64')
    page=os.sysconf('SC_PAGE_SIZE')
    if page!=4096:raise ValueError('GNU address admission requires the observed 4KiB native page geometry')
    dependencies=android_dependency_closure(proot)
    spans={path:elf_load_span(path,page) for path in dependencies}
    load_bytes=sum(value['loadSpanBytes'] for value in spans.values())
    gap_count=sum(value['gapEligible'] for value in spans.values())
    gaps=gap_count*MAX_GAP_UNITS*LIBRARY_GAP_ALIGNMENT
    # Bionic holds completed mappings+gaps and transiently reserves at most
    # align_up(size+gap,2MiB)+2MiB-page; retain a conservative 4MiB envelope.
    transient=2*LIBRARY_GAP_ALIGNMENT
    scudo=SCUDO_CLASSES*SCUDO_REGION_BYTES
    capacity=scudo+CFI_SHADOW_BYTES+load_bytes+gaps+transient+WORKLOAD_ADDRESS_HEADROOM
    soft,hard=resource.getrlimit(resource.RLIMIT_AS)
    if capacity>MAX_DECLARED_ADDRESS_SPACE or any(value!=resource.RLIM_INFINITY and capacity>value for value in (soft,hard)):
        raise ValueError('Native GNU geometry exceeds an inherited or supported address ceiling')
    return {'schema':'foldgpt.gnu-address-admission.v1','addressSpaceBytes':capacity,
        'pageSize':page,'scudoClasses':SCUDO_CLASSES,'scudoRegionBytes':SCUDO_REGION_BYTES,
        'scudoReservationBytes':scudo,'cfiShadowBytes':CFI_SHADOW_BYTES,
        'nativeLibraryCount':len(spans),'nativeLoadSpanBytes':load_bytes,'gapEligibleLibraries':gap_count,
        'maximumGapUnits':MAX_GAP_UNITS,'gapAlignmentBytes':LIBRARY_GAP_ALIGNMENT,
        'maximumRetainedGapBytes':gaps,'transientAlignmentBytes':transient,
        'workloadHeadroomBytes':WORKLOAD_ADDRESS_HEADROOM,'inheritedSoft':soft,'inheritedHard':hard,
        'nativeLibraries':spans}
