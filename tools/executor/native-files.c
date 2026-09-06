/* SPDX-License-Identifier: GPL-3.0-only
 * Native path/FD half of the trusted executor's file RPC backend.
 * The caller must authorize the request against its immutable policy first.
 * This helper never runs guest code. See native-files.md for admission limits.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/openat2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_DATA (16U * 1024U * 1024U)
#define MAX_DEPTH 64U

static int error(const char *stage) {
    fprintf(stderr,"{\"stage\":\"%s\",\"errno\":%d}\n",stage,errno);
    return 1;
}
static int valid_relative(const char *path) {
    if (!path[0] || path[0]=='/' || strlen(path)>=PATH_MAX) return 0;
    const char *p=path;
    for (;;) {
        const char *end=strchr(p,'/'); size_t n=end?(size_t)(end-p):strlen(p);
        if (!n || (n==1 && p[0]=='.') || (n==2 && p[0]=='.' && p[1]=='.')) return 0;
        if (!end) return 1;
        p=end+1;
    }
}
static int open_beneath(int root,const char *path,int flags,int mode) {
    struct open_how how={.flags=(uint64_t)flags,.mode=(uint64_t)mode,
        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    return (int)syscall(SYS_openat2,root,path,&how,sizeof(how));
}
static int ordinary(int fd) {
    struct stat st;
    if (fstat(fd,&st)<0) return 0;
    if (!S_ISREG(st.st_mode) || st.st_uid!=getuid() || st.st_nlink!=1) { errno=EPERM; return 0; }
    return 1;
}
static int pinned_open(int root,const char *path,int writing) {
    int pin=open_beneath(root,path,O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
    if (pin<0) {
        if (!writing || errno!=ENOENT) return -1;
        // Never open a racing replacement: this branch exclusively creates a
        // new ordinary file. EEXIST stays an error, not a retry with truncation.
        return open_beneath(root,path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    }
    if (!ordinary(pin)) { int saved=errno; close(pin); errno=saved; return -1; }
    // Reopen the pinned inode, not a second lookup of an attacker-changeable
    // pathname. /proc/self/fd is internal control data, never a request path.
    char proc[64]; snprintf(proc,sizeof(proc),"/proc/self/fd/%d",pin);
    int fd=open(proc,(writing?O_WRONLY:O_RDONLY)|O_CLOEXEC|O_NONBLOCK);
    int saved=errno;
    struct stat before,after;
    if (fd>=0 && (fstat(pin,&before)<0 || fstat(fd,&after)<0 ||
            before.st_dev!=after.st_dev || before.st_ino!=after.st_ino || !ordinary(fd))) {
        saved=errno?errno:ESTALE; close(fd); fd=-1;
    }
    close(pin); errno=saved; return fd;
}
static int write_all(int fd,const void *buffer,size_t length) {
    const unsigned char *p=buffer;
    while(length) {
        ssize_t n=write(fd,p,length);
        if(n<0 && errno==EINTR) continue;
        if(n<=0) { if(!n) errno=EIO; return -1; }
        p+=n; length-=(size_t)n;
    }
    return 0;
}
static int decimal(const char *text,uint64_t *value) {
    if(!text[0]) return 0;
    for(const char *p=text;*p;p++) if(*p<'0' || *p>'9') return 0;
    char *end; errno=0;
    unsigned long long number=strtoull(text,&end,10);
    if(errno || *end) return 0;
    *value=(uint64_t)number;
    return 1;
}
static int create_directories(int root,char **argv) {
    /* The trusted policy side authorizes EVERY missing suffix component and
     * supplies the identity of the last existing directory it inspected.
     * Recheck that immutable plan before the first mutation. Neither an
     * unexpected existing object nor a missing ancestor is adopted/retried.
     */
    uint64_t missing,device,inode;
    if(!decimal(argv[4],&missing) || missing>MAX_DEPTH ||
            !decimal(argv[5],&device) || !decimal(argv[6],&inode)) {
        errno=EINVAL; return error("directory-state");
    }
    char path[PATH_MAX]; strcpy(path,argv[3]);
    char *components[MAX_DEPTH]; unsigned count=0;
    if(strcmp(path,".")) {
        char *next=path;
        for(;;) {
            if(count==MAX_DEPTH) { errno=E2BIG; return error("directory-state"); }
            components[count++]=next;
            char *slash=strchr(next,'/');
            if(slash) *slash=0;
            if(strlen(next)>NAME_MAX) { errno=ENAMETOOLONG; return error("directory-state"); }
            if(!slash) break;
            next=slash+1;
        }
    }
    if(missing>count) { errno=EINVAL; return error("directory-state"); }
    int recursive=!strcmp(argv[1],"mkdirs");
    if(!recursive && missing>1) { errno=ENOENT; return error("open"); }
    /* A request body is never interpreted as more directory authorizations. */
    unsigned char unexpected;
    ssize_t received;
    do { received=read(STDIN_FILENO,&unexpected,1); } while(received<0 && errno==EINTR);
    if(received<0) return error("input");
    if(received) { errno=EMSGSIZE; return error("input-length"); }

    unsigned existing=count-(unsigned)missing;
    char prefix[PATH_MAX]="";
    for(unsigned i=0;i<existing;i++) {
        if(i) strcat(prefix,"/");
        strcat(prefix,components[i]);
    }
    int directory=existing?open_beneath(root,prefix,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0):dup(root);
    if(directory<0) return error("open");
    struct stat st;
    if(fstat(directory,&st)<0) return error("directory-state");
    if(!S_ISDIR(st.st_mode) || st.st_uid!=getuid() ||
            (uint64_t)st.st_dev!=device || (uint64_t)st.st_ino!=inode) {
        errno=ESTALE; return error("directory-state");
    }
    if(!missing) {
        if(!recursive) { errno=EEXIST; return error("mkdir"); }
        if(close(directory)<0) return error("close");
        return 0;
    }
    int check=open_beneath(directory,components[existing],O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
    if(check>=0) { close(check); errno=EEXIST; return error("directory-state"); }
    if(errno!=ENOENT) return error("open");
    umask(0077);
    for(unsigned i=existing;i<count;i++) {
        if(mkdirat(directory,components[i],0700)<0) return error("mkdir");
        int child=open_beneath(directory,components[i],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0);
        if(child<0) return error("open");
        if(fstat(child,&st)<0) return error("directory-state");
        if(!S_ISDIR(st.st_mode) || st.st_uid!=getuid() || (st.st_mode&0777)!=0700) {
            errno=EPERM; return error("directory-state");
        }
        if(fsync(child)<0 || fsync(directory)<0) return error("directory-sync");
        if(close(directory)<0) return error("close");
        directory=child;
    }
    if(close(directory)<0) return error("close");
    return 0;
}
int main(int argc,char **argv) {
    int making=argc==7 && (!strcmp(argv[1],"mkdir") || !strcmp(argv[1],"mkdirs"));
    if((!making && (argc!=5 || (strcmp(argv[1],"read") && strcmp(argv[1],"write")))) ||
            (!valid_relative(argv[3]) && !(making && !strcmp(argv[3],".")))) {
        errno=EINVAL; return error("invocation");
    }
    char *end;
    errno=0; long descriptor=strtol(argv[2],&end,10);
    if(errno || !argv[2][0] || *end || descriptor<3 || descriptor>INT_MAX) { errno=EINVAL; return error("root-fd"); }
    int root=(int)descriptor;
    struct stat root_stat;
    if(fstat(root,&root_stat)<0 || !S_ISDIR(root_stat.st_mode) || root_stat.st_uid!=getuid() || (root_stat.st_mode&0077)) {
        errno=EPERM; return error("root-ownership");
    }
    if(making) return create_directories(root,argv);
    errno=0; unsigned long expected=strtoul(argv[4],&end,10);
    if(errno || !argv[4][0] || *end || expected>MAX_DATA || argv[4][0]=='-') { errno=EINVAL; return error("length"); }
    int writing=!strcmp(argv[1],"write");
    unsigned char *data=malloc(MAX_DATA+1);
    if(!data) return error("allocation");
    size_t length=0;
    // Collect a complete bounded write before opening the destination. A
    // truncated transport or an oversized request cannot truncate a file.
    if(writing) {
        while(length<=MAX_DATA) {
            ssize_t n=read(STDIN_FILENO,data+length,MAX_DATA+1-length);
            if(n<0 && errno==EINTR) continue;
            if(n<0) return error("input");
            if(!n) break;
            length+=(size_t)n;
        }
        if(length!=expected) { errno=EMSGSIZE; return error("input-length"); }
    }
    int fd=pinned_open(root,argv[3],writing);
    if(fd<0) return error("open");
    if(!ordinary(fd)) return error("file-kind");
    if(writing) {
        if(ftruncate(fd,0)<0 || write_all(fd,data,length)<0 || fsync(fd)<0) return error("write");
        // Sync the actual containing directory so creation also survives a
        // normal restart. No recursive operation or policy widening is used.
        char parent[PATH_MAX]; strcpy(parent,argv[3]); char *slash=strrchr(parent,'/');
        int directory;
        if(slash) { *slash=0; directory=open_beneath(root,parent,O_RDONLY|O_DIRECTORY|O_CLOEXEC,0); }
        else directory=dup(root);
        if(directory<0 || fsync(directory)<0) return error("directory-sync");
        close(directory);
    } else {
        while(length<=MAX_DATA) {
            ssize_t n=read(fd,data+length,MAX_DATA+1-length);
            if(n<0 && errno==EINTR) continue;
            if(n<0) return error("read");
            if(!n) break;
            length+=(size_t)n;
        }
        if(length>MAX_DATA) { errno=EFBIG; return error("read-bound"); }
        if(write_all(STDOUT_FILENO,data,length)<0) return error("output");
    }
    if(close(fd)<0) return error("close");
    close(root); free(data); return 0;
}
