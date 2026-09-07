"""Observe native mmap requests of the installed PRoot --version only.

This is a separate same-UID ptrace diagnostic, without policy changes or guest
commands. It records syscall arguments and procfs maps, never process contents.
"""
import argparse
import ctypes
import json
import os
from pathlib import Path
import resource
import signal
import struct
import sys
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proot',type=Path,required=True)
    p.add_argument('--address-space-bytes',type=int,required=True)
    p.add_argument('--fd-capacity',type=int,required=True)
    args=p.parse_args()
    if sys.platform!='android' or os.uname().machine!='aarch64' or os.getuid()==0:
        raise RuntimeError('This probe is only for the observed nonroot Android ARM64 UID')
    libc=ctypes.CDLL(None,use_errno=True);libc.ptrace.restype=ctypes.c_long
    def ptrace(request,pid,address=0,data=0):
        value=libc.ptrace(ctypes.c_uint(request),ctypes.c_int(pid),ctypes.c_void_p(address),ctypes.c_void_p(data))
        if value<0:raise OSError(ctypes.get_errno(),os.strerror(ctypes.get_errno()))
        return value
    native=args.proot.parent
    env={'LD_PRELOAD':str(native/'libtalloc.so'),'LD_LIBRARY_PATH':str(native),'PATH':'/system/bin'}
    readfd,writefd=os.pipe2(os.O_CLOEXEC)
    pid=os.fork()
    if pid==0:
        try:
            os.close(readfd);os.setpgid(0,0);os.dup2(writefd,1);os.dup2(writefd,2);os.close(writefd)
            ptrace(0,0);os.kill(os.getpid(),signal.SIGSTOP)
            resource.setrlimit(resource.RLIMIT_NOFILE,(args.fd_capacity,args.fd_capacity))
            resource.setrlimit(resource.RLIMIT_AS,(args.address_space_bytes,args.address_space_bytes))
            os.execve(str(args.proot),[str(args.proot),'--version'],env)
        except BaseException as error:
            os.write(2,repr(error).encode());os._exit(125)
    os.close(writefd);os.set_blocking(readfd,False)
    observations=[];out=bytearray();complete=False;last=None;syscalls=0;executed=False
    def maps():
        data=Path(f'/proc/{pid}/maps').read_text()
        values=[]
        for line in data.splitlines():
            interval=line.split(None,1)[0];lo,hi=(int(v,16) for v in interval.split('-'))
            values.append((hi-lo,line))
        return {'mappedBytes':sum(v[0] for v in values),'maps':data,
            'largest':sorted(values,reverse=True)[:12],
            'status':Path(f'/proc/{pid}/status').read_text()}
    deadline=time.monotonic()+25
    try:
        waited,status=os.waitpid(pid,0)
        if waited!=pid or not os.WIFSTOPPED(status):raise RuntimeError('Native probe failed before tracing')
        ptrace(0x4200,pid,0,0x1|0x10|0x100000) # TRACESYSGOOD, TRACEEXEC, EXITKILL
        ptrace(24,pid)
        while True:
            if time.monotonic()>=deadline:raise TimeoutError('Native address diagnostic deadline')
            waited,status=os.waitpid(pid,os.WNOHANG)
            try:
                data=os.read(readfd,65536)
                if data:out.extend(data)
            except BlockingIOError:pass
            if not waited:time.sleep(0.0001);continue
            if os.WIFEXITED(status) or os.WIFSIGNALED(status):complete=True;break
            signum=os.WSTOPSIG(status);event=status>>16
            if event==4:
                executed=True;observations.append({'phase':'exec','snapshot':maps()})
            elif signum==(signal.SIGTRAP|0x80):
                buffer=ctypes.create_string_buffer(88)
                length=ptrace(0x420e,pid,len(buffer),ctypes.addressof(buffer))
                if length<24:raise RuntimeError('Incomplete native syscall observation')
                op=buffer.raw[0]
                if op==1:
                    number,*values=struct.unpack_from('<7Q',buffer.raw,24);syscalls+=1
                    last=(number,values)
                    if executed and number==222 and values[1]>=64*1024*1024:
                        observations.append({'phase':'mmap-enter','syscall':number,'args':values,'snapshot':maps()})
                elif op==2 and last is not None:
                    number,values=last
                    result=struct.unpack_from('<q',buffer.raw,24)[0]
                    if executed and number==222 and (values[1]>=64*1024*1024 or result<0):
                        observations.append({'phase':'mmap-exit','syscall':number,'args':values,'result':result,'snapshot':maps()})
                    last=None
            elif executed:
                observations.append({'phase':'signal','signal':signum,'snapshot':maps()})
            deliver=0 if signum in (signal.SIGTRAP,signal.SIGTRAP|0x80) else signum
            ptrace(24,pid,0,deliver)
        while True:
            try:data=os.read(readfd,65536)
            except BlockingIOError:break
            if not data:break
            out.extend(data)
        print(json.dumps({'uid':os.getuid(),'proot':str(args.proot),'addressSpaceBytes':args.address_space_bytes,
            'fdCapacity':args.fd_capacity,'syscalls':syscalls,'exitCode':os.waitstatus_to_exitcode(status),
            'output':out.decode(errors='replace'),'observations':observations},indent=2),flush=True)
    finally:
        if not complete:
            try:os.kill(pid,signal.SIGKILL)
            except ProcessLookupError:pass
            os.waitpid(pid,0)
        os.close(readfd)


if __name__=='__main__':main()
