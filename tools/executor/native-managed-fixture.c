/* SPDX-License-Identifier: GPL-3.0-only
 * Real exec'ed fixed syscall exerciser, not a simulated command backend.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/openat2.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native-runner-memory-contract.h"

extern char **environ;

static void require(int yes,const char *name) {
    if(yes)return;
    dprintf(2,"fixture failure: %s errno=%d\n",name,errno);_exit(31);
}
static int acquire(int kind,const char *source,int flags,int mode) {
    char path[4096]={0};require(strlen(source)<sizeof(path),"path bound");strcpy(path,source);
    if(kind==0)return (int)syscall(SYS_openat,AT_FDCWD,path,flags,mode);
    if(kind==1){struct open_how how={.flags=(uint64_t)flags,.mode=(uint64_t)mode};return (int)syscall(SYS_openat2,AT_FDCWD,path,&how,sizeof(how));}
#ifdef SYS_open
    return (int)syscall(SYS_open,path,flags,mode);
#else
    errno=ENOSYS;return -1;
#endif
}
int main(int argc,char **argv) {
    require(argc>=2,"arguments");
    require(getuid()!=0&&prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)==1&&prctl(PR_GET_SECCOMP,0,0,0,0)==2,"native setup");
    require(environ&&!environ[0],"empty execution environment");
    for(int fd=3;fd<128;fd++){errno=0;require(fcntl(fd,F_GETFD)<0&&errno==EBADF,"no inherited private descriptors");}
    if(!strcmp(argv[1],"exit"))return argc>2?atoi(argv[2]):0;
    if(!strcmp(argv[1],"resources")){
        struct rlimit limit;
        require(getrlimit(RLIMIT_NPROC,&limit)==0,"actual UID task limit");
        dprintf(1,"%llu:%llu\n",(unsigned long long)limit.rlim_cur,(unsigned long long)limit.rlim_max);return 0;
    }
    if(!strcmp(argv[1],"isolation")){
        errno=0;require(socket(AF_INET,SOCK_STREAM,0)<0&&errno==EPERM,"network remains denied");
        errno=0;require(chdir("/")<0&&errno==EPERM,"cwd remains pinned");
        errno=0;require(mkdirat(AT_FDCWD,"unsupported-directory",0700)<0&&errno==EPERM,"namespace mutations denied");
        struct stat metadata;
        errno=0;require(fstatat(AT_FDCWD,"value",&metadata,0)<0&&errno==EPERM,"path metadata explicitly unsupported");
        errno=0;require(fchmod(1,0777)<0&&errno==EPERM,"metadata mutation unavailable");
        dprintf(1,"ISOLATION\n");return 0;
    }
    if(!strcmp(argv[1],"sleep")){for(;;)pause();}
    if(!strcmp(argv[1],"fork")){
        pid_t child=fork();require(child>=0,"fork");
        if(!child){dprintf(1,"CHILD:%d\n",getpid());for(;;)pause();}
        for(;;)pause();
    }
    require(argc==7,"open arguments");
    int kind=atoi(argv[2]),flags=atoi(argv[4]),expected=atoi(argv[5]);
    errno=0;int fd=acquire(kind,argv[3],flags,(flags&O_CREAT)?0600:0),actual=errno;
    if(expected){if(fd>=0)close(fd);require(fd<0&&actual==expected,"expected native denial");dprintf(1,"DENIED:%d\n",actual);return 0;}
    require(fd>=0,"actual acquisition");
    require((fcntl(fd,F_GETFD)&FD_CLOEXEC)==((flags&O_CLOEXEC)?FD_CLOEXEC:0),"requested close-on-exec flag");
    require((fcntl(fd,F_GETFL)&(O_ACCMODE|O_APPEND|O_NONBLOCK))==(flags&(O_ACCMODE|O_APPEND|O_NONBLOCK)),"requested file-description flags");
    if((flags&O_ACCMODE)!=O_WRONLY){char bytes[256];ssize_t n=read(fd,bytes,sizeof(bytes));require(n>=0,"read");require(write(1,bytes,(size_t)n)==n,"read output");}
    if((flags&O_ACCMODE)!=O_RDONLY){size_t size=strlen(argv[6]);require(pwrite(fd,argv[6],size,0)==(ssize_t)size&&fsync(fd)==0,"write");}
    require(close(fd)==0,"close");return 0;
}
