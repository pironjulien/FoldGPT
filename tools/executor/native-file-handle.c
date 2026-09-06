/* SPDX-License-Identifier: GPL-3.0-only
 * Native descriptor acquisition/block-read half of the trusted file broker.
 * Policy admission belongs to the supervisor; no guest code is executed here.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <linux/openat2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/un.h>
#include <unistd.h>

#define MAX_BLOCK (1024U * 1024U) /* Official FILE_READ_CHUNK_SIZE. */
static int failure(const char *stage) {
    fprintf(stderr,"{\"stage\":\"%s\",\"errno\":%d}\n",stage,errno); return 1;
}
static int decimal(const char *text,uint64_t *result) {
    if(!text[0]) return 0;
    for(const char *p=text;*p;p++) if(*p<'0'||*p>'9') return 0;
    char *end; errno=0; unsigned long long value=strtoull(text,&end,10);
    if(errno||*end) return 0;
    *result=(uint64_t)value; return 1;
}
static int descriptor(const char *text) {
    uint64_t value;
    if(!decimal(text,&value)||value<3||value>INT_MAX) { errno=EINVAL; return -1; }
    return (int)value;
}
static int relative(const char *path) {
    if(!path[0]||path[0]=='/'||strlen(path)>=PATH_MAX) return 0;
    const char *p=path;
    for(;;) {
        const char *end=strchr(p,'/'); size_t size=end?(size_t)(end-p):strlen(p);
        if(!size||(size==1&&p[0]=='.')||(size==2&&p[0]=='.'&&p[1]=='.')) return 0;
        if(!end) return 1;
        p=end+1;
    }
}
static int ordinary(int fd,struct stat *info) {
    if(fstat(fd,info)<0) return 0;
    if(!S_ISREG(info->st_mode)||info->st_uid!=getuid()||info->st_nlink!=1) { errno=EPERM; return 0; }
    return 1;
}
static void put64(unsigned char *target,uint64_t value) {
    for(unsigned index=0;index<8;index++) target[index]=(unsigned char)(value>>(index*8));
}
static int acquire(int argc,char **argv) {
    if(argc!=7) { errno=EINVAL; return failure("invocation"); }
    int root=descriptor(argv[2]),channel=descriptor(argv[4]);
    uint64_t device,inode;
    if(root<0||channel<0||root==channel||!relative(argv[3])||
            !decimal(argv[5],&device)||!decimal(argv[6],&inode)) { errno=EINVAL; return failure("invocation"); }
    struct stat parent;
    if(fstat(root,&parent)<0) return failure("root-fd");
    if(getuid()==0||!S_ISDIR(parent.st_mode)||parent.st_uid!=getuid()||(parent.st_mode&077)) {
        errno=EPERM; return failure("root-ownership");
    }
    struct sockaddr_un address; socklen_t address_size=sizeof(address);
    int type=0; socklen_t type_size=sizeof(type);
    struct ucred peer; socklen_t peer_size=sizeof(peer);
    if(getsockname(channel,(struct sockaddr *)&address,&address_size)<0||address.sun_family!=AF_UNIX||
            getsockopt(channel,SOL_SOCKET,SO_TYPE,&type,&type_size)<0||type!=SOCK_SEQPACKET||
            getsockopt(channel,SOL_SOCKET,SO_PEERCRED,&peer,&peer_size)<0||peer_size!=sizeof(peer)||
            peer.uid!=getuid()||peer.pid!=getppid()) { errno=EPERM; return failure("channel"); }
    struct open_how how={.flags=O_PATH|O_NOFOLLOW|O_CLOEXEC,
        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    int pin=(int)syscall(SYS_openat2,root,argv[3],&how,sizeof(how));
    if(pin<0) return failure("open");
    struct stat before,after;
    if(!ordinary(pin,&before)) { close(pin); return failure("file-kind"); }
    if((uint64_t)before.st_dev!=device||(uint64_t)before.st_ino!=inode) {
        close(pin); errno=ESTALE; return failure("identity");
    }
    char path[64]; snprintf(path,sizeof(path),"/proc/self/fd/%d",pin);
    int file=open(path,O_RDONLY|O_NONBLOCK|O_CLOEXEC);
    if(file<0) { int saved=errno; close(pin); errno=saved; return failure("reopen"); }
    if(!ordinary(file,&after)||before.st_dev!=after.st_dev||before.st_ino!=after.st_ino) {
        close(file); close(pin); errno=ESTALE; return failure("identity");
    }
    close(pin);
    unsigned char payload[48]={'F','G','F','D','v','1',0,0};
    put64(payload+8,(uint64_t)after.st_dev); put64(payload+16,(uint64_t)after.st_ino);
    put64(payload+24,(uint64_t)after.st_mode); put64(payload+32,(uint64_t)after.st_uid);
    put64(payload+40,(uint64_t)after.st_nlink);
    union { struct cmsghdr alignment; unsigned char data[CMSG_SPACE(sizeof(int))]; } control={0};
    struct iovec vector={.iov_base=payload,.iov_len=sizeof(payload)};
    struct msghdr message={.msg_iov=&vector,.msg_iovlen=1,.msg_control=control.data,.msg_controllen=sizeof(control.data)};
    struct cmsghdr *header=CMSG_FIRSTHDR(&message);
    header->cmsg_level=SOL_SOCKET; header->cmsg_type=SCM_RIGHTS; header->cmsg_len=CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(header),&file,sizeof(file));
    ssize_t sent;
    do { sent=sendmsg(channel,&message,MSG_NOSIGNAL); } while(sent<0&&errno==EINTR);
    int saved=errno;
    close(file); close(channel); close(root);
    if(sent!=(ssize_t)sizeof(payload)) { errno=sent<0?saved:EIO; return failure("send"); }
    return 0;
}
static int block(int argc,char **argv) {
    if(argc!=5) { errno=EINVAL; return failure("invocation"); }
    int file=descriptor(argv[2]); uint64_t offset,length;
    if(file<0||!decimal(argv[3],&offset)||!decimal(argv[4],&length)||length<1||length>MAX_BLOCK) {
        errno=EINVAL; return failure("invocation");
    }
    struct stat info; int flags=fcntl(file,F_GETFL);
    if(flags<0||fstat(file,&info)<0) return failure("read-fd");
    if(!S_ISREG(info.st_mode)||(flags&O_ACCMODE)!=O_RDONLY||(flags&O_PATH)) {
        errno=EPERM; return failure("read-fd");
    }
    /* A handle retains its already-authorized inode even if its pathname is
     * renamed/unlinked or its mode changes. Never resolve its pathname again.
     */
    unsigned char *data=malloc((size_t)length);
    if(!data) return failure("allocation");
    size_t received=0;
    while(received<(size_t)length) {
        if(offset>INT64_MAX-received) { free(data); errno=EINVAL; return failure("offset"); }
        ssize_t count=pread(file,data+received,(size_t)length-received,(off_t)(offset+received));
        if(count<0&&errno==EINTR) continue;
        if(count<0) { int saved=errno; free(data); errno=saved; return failure("read"); }
        if(!count) break;
        received+=(size_t)count;
    }
    size_t written=0;
    while(written<received) {
        ssize_t count=write(STDOUT_FILENO,data+written,received-written);
        if(count<0&&errno==EINTR) continue;
        if(count<=0) { int saved=count<0?errno:EIO; free(data); errno=saved; return failure("output"); }
        written+=(size_t)count;
    }
    free(data);
    if(close(file)<0) return failure("close");
    return 0;
}
int main(int argc,char **argv) {
    if(argc>=2&&!strcmp(argv[1],"open")) return acquire(argc,argv);
    if(argc>=2&&!strcmp(argv[1],"read")) return block(argc,argv);
    errno=EINVAL; return failure("invocation");
}
