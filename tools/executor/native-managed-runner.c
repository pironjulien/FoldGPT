/* SPDX-License-Identifier: GPL-3.0-only
 * Private native managed-acquisition increment. No official RPC endpoint.
 * The existing runner/profile is included unchanged for its audited native
 * parser, limits, ordinary-tree checks and allowlist; its entry point is not
 * exposed by this executable. Policy decisions use a separate trusted channel.
 */
#define main native_runner_reference_main
#include "native-runner.c"
#undef main
#include "native-managed-filter.h"
#include <sys/un.h>
#include <sys/pidfd.h>

#define MG_FRAME 16384
static int mg_channel=-1, mg_root=-1, mg_exec=-1;
static char mg_root_path[PATH_MAX];
static uint64_t mg_grants, mg_denials;
static int64_t mg_deadline;
static uint64_t mg_uid_tasks,mg_uid_budget,mg_nproc_soft,mg_nproc_hard,mg_nproc_limit;
static int mg_process_mode,mg_input=-1,mg_command=-1,mg_leader=-1,mg_started,mg_reaped,mg_reporting;
static int mg_identity_gate;

/* A separate trusted control socket never competes with an open decision.
 * The single-threaded supervisor signals only while it still owns the leader
 * PID. No process-group signal is issued after waitpid can release that PID.
 */
static int mg_commands(void) {
    if(mg_command<0||mg_reporting)return 0;
    for(int i=0;i<128;i++) {
        char command[2];struct iovec vec={.iov_base=command,.iov_len=sizeof(command)};
        struct msghdr msg={.msg_iov=&vec,.msg_iovlen=1};
        ssize_t n=recvmsg(mg_command,&msg,MSG_DONTWAIT|MSG_CMSG_CLOEXEC);
        if(n<0){if(errno==EAGAIN||errno==EWOULDBLOCK)return 0;if(errno==EINTR)continue;return -1;}
        if(!n){cancelled=SIGTERM;return 0;}
        if(n!=1||(msg.msg_flags&(MSG_TRUNC|MSG_CTRUNC))||(command[0]!='I'&&command[0]!='T')){errno=EPROTO;return -1;}
        if(command[0]=='T')cancelled=SIGTERM;
        else if(mg_started&&!mg_reaped&&mg_leader>0&&kill(-mg_leader,SIGINT)<0&&errno!=ESRCH)return -1;
    }
    return 0;
}

/* Linux RLIMIT_NPROC counts tasks for the real UID, including the GUI and
 * trusted supervisor. This is a contemporaneous procfs snapshot, not an atomic
 * reservation or a per-descendant quota. Foreign unreadable status files are
 * outside the visible snapshot; Android collection independently compares it
 * with ps -AT for the same UID. The inherited ceiling is never raised.
 */
static int mg_uid_limit(uint64_t budget) {
    struct rlimit inherited;
    if(getrlimit(RLIMIT_NPROC,&inherited)<0)return -1;
    DIR *processes=opendir("/proc");if(!processes)return -1;
    uint64_t count=0;int saw_self=0,result=0;struct dirent *entry;
    errno=0;
    while((entry=readdir(processes))) {
        const char *p=entry->d_name;if(!*p)continue;
        while(*p>='0'&&*p<='9')p++;
        if(*p)continue;
        char path[128];int length=snprintf(path,sizeof(path),"/proc/%s/status",entry->d_name);
        if(length<0||length>=(int)sizeof(path)){errno=EOVERFLOW;result=-1;break;}
        FILE *status=fopen(path,"re");
        if(!status){if(errno==ENOENT||errno==ESRCH||errno==EACCES||errno==EPERM){errno=0;continue;}result=-1;break;}
        char line[256];unsigned long uid=ULONG_MAX,threads=0;
        while(fgets(line,sizeof(line),status)) {
            unsigned long value;
            if(sscanf(line,"Uid:\t%lu",&value)==1)uid=value;
            if(sscanf(line,"Threads:\t%lu",&value)==1)threads=value;
        }
        if(ferror(status)){fclose(status);errno=EIO;result=-1;break;}
        fclose(status);
        if(uid==(unsigned long)getuid()) {
            if(!threads||count>UINT64_MAX-threads){errno=EOVERFLOW;result=-1;break;}
            count+=threads;
            if(strtol(entry->d_name,NULL,10)==getpid())saw_self=1;
        }
        errno=0;
    }
    if(errno)result=-1;
    int saved=errno;closedir(processes);errno=saved;
    if(result<0)return -1;
    if(!saw_self||!budget||count>UINT64_MAX-budget){errno=EINVAL;return -1;}
    mg_uid_tasks=count;mg_uid_budget=budget;
    mg_nproc_soft=(uint64_t)inherited.rlim_cur;mg_nproc_hard=(uint64_t)inherited.rlim_max;
    uint64_t ceiling=mg_nproc_soft<mg_nproc_hard?mg_nproc_soft:mg_nproc_hard;
    mg_nproc_limit=count+budget<ceiling?count+budget:ceiling;
    if(mg_nproc_limit<=count){errno=EAGAIN;return -1;}
    return 0;
}

static int mg_packet(int fd,const void *data,size_t size) {
    for(;;) {
        if(mg_commands()<0)return -1;
        if(cancelled||now_ms()>=mg_deadline) { errno=ECANCELED; return -1; }
        ssize_t n=send(fd,data,size,MSG_NOSIGNAL|MSG_DONTWAIT);
        if(n==(ssize_t)size) return 0;
        if(n>=0) { errno=EIO; return -1; }
        if(errno!=EAGAIN&&errno!=EWOULDBLOCK&&errno!=EINTR) return -1;
        struct pollfd p={.fd=fd,.events=POLLOUT};
        if(poll(&p,1,20)<0&&errno!=EINTR) return -1;
    }
}
static int mg_receive(int fd,char *data,size_t capacity) {
    for(;;) {
        if(mg_commands()<0)return -1;
        if(cancelled||now_ms()>=mg_deadline) { errno=ECANCELED; return -1; }
        struct iovec vec={.iov_base=data,.iov_len=capacity};
        struct msghdr msg={.msg_iov=&vec,.msg_iovlen=1};
        ssize_t n=recvmsg(fd,&msg,MSG_DONTWAIT|MSG_CMSG_CLOEXEC);
        if(n>0) {
            if(msg.msg_flags&(MSG_TRUNC|MSG_CTRUNC)) { errno=EPROTO; return -1; }
            return (int)n;
        }
        if(!n) { errno=EPIPE; return -1; }
        if(errno!=EAGAIN&&errno!=EWOULDBLOCK&&errno!=EINTR) return -1;
        struct pollfd p={.fd=fd,.events=POLLIN};
        if(poll(&p,1,20)<0&&errno!=EINTR) return -1;
    }
}
/* Pin our own identity, pass that actual pidfd, then wait for its parent's
 * acknowledgement before creating any worker. No parent-side numeric PID
 * lookup races asyncio's unique waitpid owner. The descriptor still denotes
 * this exact supervisor after exit and returns ESRCH when it is gone.
 */
static int mg_supervisor_identity(void) {
    int identity=pidfd_open(getpid(),0);if(identity<0)return -1;
    char data[128];int length=snprintf(data,sizeof(data),
        "{\"type\":\"supervisor\",\"pid\":%d,\"profile\":\"managed-process-v2\"}",getpid());
    union {struct cmsghdr aligned;unsigned char bytes[CMSG_SPACE(sizeof(int))];} control={0};
    struct iovec vec={.iov_base=data,.iov_len=(size_t)length};
    struct msghdr message={.msg_iov=&vec,.msg_iovlen=1,.msg_control=control.bytes,.msg_controllen=sizeof(control.bytes)};
    struct cmsghdr *header=CMSG_FIRSTHDR(&message);
    header->cmsg_level=SOL_SOCKET;header->cmsg_type=SCM_RIGHTS;header->cmsg_len=CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(header),&identity,sizeof(identity));
    ssize_t sent;
    do {sent=sendmsg(mg_channel,&message,MSG_NOSIGNAL);}while(sent<0&&errno==EINTR);
    int saved=errno;close(identity);errno=saved;
    if(sent!=length)return -1;
    char acknowledgement[2];int received=mg_receive(mg_channel,acknowledgement,sizeof(acknowledgement));
    if(received!=1||acknowledgement[0]!='P'){if(received>=0)errno=EPROTO;return -1;}
    return 0;
}
static int mg_send_listener(int channel,int listener) {
    char byte='L';
    union {struct cmsghdr aligned; unsigned char bytes[CMSG_SPACE(sizeof(int))];} control={0};
    struct iovec vec={.iov_base=&byte,.iov_len=1};
    struct msghdr msg={.msg_iov=&vec,.msg_iovlen=1,.msg_control=control.bytes,.msg_controllen=sizeof(control.bytes)};
    struct cmsghdr *header=CMSG_FIRSTHDR(&msg);
    header->cmsg_level=SOL_SOCKET; header->cmsg_type=SCM_RIGHTS; header->cmsg_len=CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(header),&listener,sizeof(listener));
    ssize_t n;
    do {n=syscall(SYS_sendmsg,channel,&msg,MSG_NOSIGNAL);} while(n<0&&errno==EINTR);
    return n==1?0:-1;
}
static int mg_receive_listener(int channel) {
    struct pollfd p={.fd=channel,.events=POLLIN};
    for(;;) {
        if(mg_commands()<0)return -1;
        if(cancelled||now_ms()>=mg_deadline) {errno=ECANCELED; return -1;}
        int ready=poll(&p,1,20);
        if(ready<0&&errno!=EINTR) return -1;
        if(ready>0) break;
    }
    char byte=0;
    union {struct cmsghdr aligned; unsigned char bytes[CMSG_SPACE(8*sizeof(int))];} control={0};
    struct iovec vec={.iov_base=&byte,.iov_len=1};
    struct msghdr msg={.msg_iov=&vec,.msg_iovlen=1,.msg_control=control.bytes,.msg_controllen=sizeof(control.bytes)};
    ssize_t n=recvmsg(channel,&msg,MSG_CMSG_CLOEXEC);
    int result=-1,count=0,valid=n==1&&byte=='L'&&!(msg.msg_flags&(MSG_CTRUNC|MSG_TRUNC));
    for(struct cmsghdr *h=CMSG_FIRSTHDR(&msg);h;h=CMSG_NXTHDR(&msg,h)) {
        if(h->cmsg_level!=SOL_SOCKET||h->cmsg_type!=SCM_RIGHTS||h->cmsg_len<CMSG_LEN(0)) {valid=0;continue;}
        size_t size=h->cmsg_len-CMSG_LEN(0);
        if(size%sizeof(int)) valid=0;
        for(size_t k=0;k+sizeof(int)<=size;k+=sizeof(int)) {
            int fd; memcpy(&fd,(unsigned char *)CMSG_DATA(h)+k,sizeof(fd));
            if(!count++) result=fd; else close(fd);
        }
    }
    if(!valid||count!=1) {if(result>=0)close(result);errno=EPROTO;return -1;}
    return result;
}
static int mg_keep_three(int a,int b,int c) {
    int fds[3]={a,b,c};
    for(int i=0;i<3;i++)for(int j=i+1;j<3;j++)if(fds[j]<fds[i]){int t=fds[i];fds[i]=fds[j];fds[j]=t;}
    unsigned first=3;
    for(int i=0;i<3;i++) {
        if(fds[i]<3||(i&&fds[i]==fds[i-1])) {errno=EINVAL;return -1;}
        if(first<(unsigned)fds[i]&&syscall(SYS_close_range,first,(unsigned)fds[i]-1,0U)<0)return -1;
        first=(unsigned)fds[i]+1;
    }
    return (int)syscall(SYS_close_range,first,UINT_MAX,0U);
}
static int mg_static_elf(int fd) {
    Elf64_Ehdr header;
    if(pread(fd,&header,sizeof(header),0)!=(ssize_t)sizeof(header)||memcmp(header.e_ident,ELFMAG,SELFMAG)||
       header.e_ident[EI_CLASS]!=ELFCLASS64||header.e_ident[EI_DATA]!=ELFDATA2LSB||header.e_type!=ET_EXEC||
       header.e_phentsize!=sizeof(Elf64_Phdr)||!header.e_phnum||header.e_phnum>128) {errno=ENOEXEC;return -1;}
#if defined(__aarch64__)
    if(header.e_machine!=EM_AARCH64) {errno=ENOEXEC;return -1;}
#else
    if(header.e_machine!=EM_X86_64) {errno=ENOEXEC;return -1;}
#endif
    for(unsigned i=0;i<header.e_phnum;i++) {
        Elf64_Phdr segment;
        uint64_t offset=header.e_phoff+(uint64_t)i*sizeof(segment);
        if(offset>INT64_MAX||pread(fd,&segment,sizeof(segment),(off_t)offset)!=(ssize_t)sizeof(segment)||
           segment.p_type==PT_INTERP||(segment.p_type==PT_LOAD&&(segment.p_flags&(PF_W|PF_X))==(PF_W|PF_X))) {errno=ENOEXEC;return -1;}
    }
    return 0;
}
static void mg_launch(struct config *c,int input,int output,int error,int setup,int channel,pid_t supervisor) {
    struct setup_error failure={.stage=1};
    if(setpgid(0,0)<0||prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0)<0||getppid()!=supervisor||
       dup2(input,0)<0||dup2(output,1)<0||dup2(error,2)<0||ptrace(PTRACE_TRACEME,0,NULL,NULL)<0||raise(SIGSTOP)!=0)goto failed;
    failure.stage=2;
    if(fchdir(mg_root)<0||prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)<0||restrict_landlock(c)<0||
       mg_keep_three(setup,channel,mg_exec)<0)goto failed;
    umask(0077);
    failure.stage=3;
    if(limit(RLIMIT_CORE,0)<0||limit(RLIMIT_AS,c->memory)<0||limit(RLIMIT_FSIZE,c->file)<0||
       limit(RLIMIT_NOFILE,c->fds)<0||limit(RLIMIT_NPROC,c->processes)<0||limit(RLIMIT_CPU,(c->wall+999)/1000+1)<0)goto failed;
    signal(SIGTERM,SIG_DFL);signal(SIGINT,SIG_DFL);signal(SIGPIPE,SIG_DFL);
    failure.stage=4;
    int listener=mg_notification_filter();
    if(listener<0||mg_send_listener(channel,listener)<0)goto failed;
    close(listener);close(channel);
    if(nr_install_seccomp()<0)goto failed;
    failure.stage=5;
    syscall(SYS_execveat,mg_exec,"",c->argv,c->env,AT_EMPTY_PATH);
failed:
    failure.error=errno?errno:EIO;
    ssize_t n=write(setup,&failure,sizeof(failure));
    _exit(n==(ssize_t)sizeof(failure)?125:126);
}
static int mg_valid(int listener,uint64_t id) {
    if(ioctl(listener,SECCOMP_IOCTL_NOTIF_ID_VALID,&id)==0)return 1;
    return errno==ENOENT?0:-1;
}
static int mg_deny(int listener,uint64_t id,int error) {
    struct seccomp_notif_resp reply={.id=id,.error=-error};
    if(ioctl(listener,SECCOMP_IOCTL_NOTIF_SEND,&reply)<0&&errno!=ENOENT)return -1;
    mg_denials++;return 0;
}
static int mg_copy(pid_t pid,uint64_t address,void *data,size_t length,int string) {
    struct iovec local={.iov_base=data,.iov_len=length},remote={.iov_base=(void *)(uintptr_t)address,.iov_len=length};
    ssize_t n=process_vm_readv(pid,&local,1,&remote,1,0);
    if(n<=0)return EFAULT;
    if(string)return memchr(data,0,(size_t)n)?0:ENAMETOOLONG;
    return n==(ssize_t)length?0:EFAULT;
}
static int mg_relative(char *path) {
    if(path[0]=='/') {
        size_t root_length=strlen(mg_root_path);
        if(strncmp(path,mg_root_path,root_length)||path[root_length]!='/')return 0;
        memmove(path,path+root_length+1,strlen(path+root_length+1)+1);
    }
    if(!path[0])return 0;
    const char *p=path;
    for(;;) {
        const char *end=strchr(p,'/');size_t size=end?(size_t)(end-p):strlen(p);
        if(!size||(size==1&&*p=='.')||(size==2&&!memcmp(p,"..",2)))return 0;
        if(!end)return 1;
        p=end+1;
    }
}
struct mg_decision {uint64_t allow,device,inode,parent_device,parent_inode;};
static int mg_decide(const struct seccomp_notif *request,uint64_t address,const char *path,uint64_t flags,uint64_t mode,struct mg_decision *d) {
    uint64_t id=request->id,how_address=request->data.nr==SYS_openat2?request->data.args[2]:0;
    int nr=request->data.nr;
    char hexpath[2*PATH_MAX+1],frame[MG_FRAME],reply[1024];
    size_t size=strlen(path);const char digits[]="0123456789abcdef";
    for(size_t i=0;i<size;i++){unsigned char b=(unsigned char)path[i];hexpath[2*i]=digits[b>>4];hexpath[2*i+1]=digits[b&15];}hexpath[2*size]=0;
    int length=snprintf(frame,sizeof(frame),"{\"type\":\"open\",\"id\":%"PRIu64",\"syscall\":%d,\"flags\":%"PRIu64",\"mode\":%"PRIu64",\"pathHex\":\"%s\",\"pid\":%u,\"pathAddress\":%"PRIu64",\"howAddress\":%"PRIu64"}",id,nr,flags,mode,hexpath,request->pid,address,how_address);
    if(length<0||length>=(int)sizeof(frame)||mg_packet(mg_channel,frame,(size_t)length)<0)return -1;
    int received=mg_receive(mg_channel,reply,sizeof(reply));if(received<0)return -1;
    struct parser *parser=calloc(1,sizeof(*parser));if(!parser)return -1;
    parser->cursor=(unsigned char *)reply;parser->end=(unsigned char *)reply+received;
    static const char *const expected[]={"id","allow","device","inode","parentDevice","parentInode"};
    int root=value(parser,0);space(parser);uint64_t got=0;
    int valid=root>=0&&parser->cursor==parser->end&&keys(parser,root,expected,6)==0&&
        number_field(parser,root,"id",0,UINT64_MAX,&got)==0&&got==id&&
        number_field(parser,root,"allow",0,1,&d->allow)==0&&
        number_field(parser,root,"device",0,UINT64_MAX,&d->device)==0&&
        number_field(parser,root,"inode",0,UINT64_MAX,&d->inode)==0&&
        number_field(parser,root,"parentDevice",0,UINT64_MAX,&d->parent_device)==0&&
        number_field(parser,root,"parentInode",0,UINT64_MAX,&d->parent_inode)==0;
    /* The tiny response has only names and numbers. Free parser-owned names. */
    for(int i=1;i<=parser->used;i++)if(parser->nodes[i].type==STRING)free(parser->nodes[i].string);
    free(parser);if(!valid){errno=EPROTO;return -1;}return 0;
}
static int mg_ordinary(int fd,struct stat *info,int directory) {
    if(fstat(fd,info)<0)return 0;
    if(!ordinary_filesystem(fd)||info->st_uid!=getuid()||
       (directory?!S_ISDIR(info->st_mode):(!S_ISREG(info->st_mode)||info->st_nlink!=1))) {errno=EPERM;return 0;}
    return 1;
}
static int mg_open_file(const char *relative,uint64_t flags,uint64_t mode,const struct mg_decision *d) {
    char parent_path[PATH_MAX];strcpy(parent_path,relative);char *slash=strrchr(parent_path,'/');
    const char *name=relative;
    if(slash){*slash=0;name=relative+(slash-parent_path)+1;}else strcpy(parent_path,".");
    struct open_how how={.flags=O_PATH|O_DIRECTORY|O_CLOEXEC,.resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    int parent=(int)syscall(SYS_openat2,mg_root,parent_path,&how,sizeof(how));
    if(parent<0)return -1;
    struct stat info;
    if(!mg_ordinary(parent,&info,1)||(uint64_t)info.st_dev!=d->parent_device||(uint64_t)info.st_ino!=d->parent_inode){close(parent);errno=ESTALE;return -1;}
    how.flags=O_PATH|O_NOFOLLOW|O_CLOEXEC;
    int pin=(int)syscall(SYS_openat2,parent,name,&how,sizeof(how));int file=-1;
    if(pin<0) {
        int saved=errno;
        if(saved!=ENOENT||d->device||d->inode||!(flags&O_CREAT)){close(parent);errno=saved;return -1;}
        how.flags=flags|O_CLOEXEC|O_NOFOLLOW|O_EXCL;how.mode=mode;
        file=(int)syscall(SYS_openat2,parent,name,&how,sizeof(how));
    } else {
        if(!mg_ordinary(pin,&info,0)||(uint64_t)info.st_dev!=d->device||(uint64_t)info.st_ino!=d->inode){close(pin);close(parent);errno=ESTALE;return -1;}
        if((flags&(O_CREAT|O_EXCL))==(O_CREAT|O_EXCL)){close(pin);close(parent);errno=EEXIST;return -1;}
        char procpath[64];snprintf(procpath,sizeof(procpath),"/proc/self/fd/%d",pin);
        file=open(procpath,(int)((flags&~(O_CREAT|O_EXCL|O_NOFOLLOW))|O_CLOEXEC));
        close(pin);
    }
    int saved=errno;
    if(file>=0&&!mg_ordinary(file,&info,0)){saved=errno;close(file);file=-1;}
    close(parent);errno=saved;return file;
}
static int mg_notification(int listener,const struct seccomp_notif *request) {
    uint64_t path_pointer=0,flags=0,mode=0;int32_t dirfd=AT_FDCWD;int error=0;
    if(request->flags||request->data.arch!=MG_ARCH)return mg_deny(listener,request->id,EPERM);
    int valid=mg_valid(listener,request->id);if(valid<=0)return valid;
    if(request->data.nr==SYS_openat) {dirfd=(int32_t)request->data.args[0];path_pointer=request->data.args[1];flags=request->data.args[2];mode=request->data.args[3];}
    else if(request->data.nr==SYS_openat2) {
        dirfd=(int32_t)request->data.args[0];path_pointer=request->data.args[1];struct open_how how={0};
        if(request->data.args[3]!=sizeof(how))return mg_deny(listener,request->id,EINVAL);
        error=mg_copy((pid_t)request->pid,request->data.args[2],&how,sizeof(how),0);
        if(error)return mg_deny(listener,request->id,error);
        if(how.resolve&~(uint64_t)(RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_MAGICLINKS|RESOLVE_NO_XDEV))return mg_deny(listener,request->id,EOPNOTSUPP);
        flags=how.flags;mode=how.mode;
        if(!(flags&O_CREAT)&&mode)return mg_deny(listener,request->id,EINVAL);
    }
#ifdef SYS_open
    else if(request->data.nr==SYS_open){path_pointer=request->data.args[0];flags=request->data.args[1];mode=request->data.args[2];}
#endif
#ifdef SYS_creat
    else if(request->data.nr==SYS_creat){path_pointer=request->data.args[0];flags=O_WRONLY|O_CREAT|O_TRUNC;mode=request->data.args[1];}
#endif
    else return mg_deny(listener,request->id,EPERM);
    const uint64_t supported=O_ACCMODE|O_APPEND|O_CLOEXEC|O_CREAT|O_EXCL|O_TRUNC|O_NOFOLLOW|O_NONBLOCK|O_LARGEFILE;
    if((flags&~supported)||(flags&O_ACCMODE)==O_ACCMODE||((flags&O_TRUNC)&&(flags&O_ACCMODE)==O_RDONLY))return mg_deny(listener,request->id,EOPNOTSUPP);
    if(!(flags&O_CREAT))mode=0;
    if(mode&~0777ULL)return mg_deny(listener,request->id,EINVAL);
    char path[PATH_MAX];error=mg_copy((pid_t)request->pid,path_pointer,path,sizeof(path),1);
    if(error)return mg_deny(listener,request->id,error);
    if((path[0]!='/'&&dirfd!=AT_FDCWD)||!mg_relative(path))return mg_deny(listener,request->id,EPERM);
    struct mg_decision decision={0};
    if(mg_decide(request,path_pointer,path,flags,mode,&decision)<0)return -1;
    if(!decision.allow)return mg_deny(listener,request->id,EACCES);
    valid=mg_valid(listener,request->id);if(valid<=0)return valid;
    int file=mg_open_file(path,flags,mode,&decision);
    if(file<0)return mg_deny(listener,request->id,errno);
    struct seccomp_notif_addfd add={.id=request->id,.flags=SECCOMP_ADDFD_FLAG_SEND,.srcfd=(uint32_t)file,
        .newfd_flags=(flags&O_CLOEXEC)?O_CLOEXEC:0};
    int installed=ioctl(listener,SECCOMP_IOCTL_NOTIF_ADDFD,&add);int saved=errno;close(file);
    if(installed<0){if(saved==ENOENT)return 0;return mg_deny(listener,request->id,saved);}
    mg_grants++;return 0;
}

static int mg_supervise(struct config *c) {
    int input[2],output[2],error[2],setup[2],bootstrap[2];
    if(pipe2(input,O_CLOEXEC)<0||pipe2(output,O_CLOEXEC)<0||pipe2(error,O_CLOEXEC)<0||
       pipe2(setup,O_CLOEXEC)<0||socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,bootstrap)<0||
       prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0)<0)return fail("managed-pipes");
    pid_t supervisor=getpid(),pid=fork();
    if(!pid)mg_launch(c,mg_process_mode?mg_input:input[0],output[1],error[1],setup[1],bootstrap[1],supervisor);
    close(input[0]);close(input[1]);close(output[1]);close(error[1]);close(setup[1]);close(bootstrap[1]);
    if(mg_input>=0){close(mg_input);mg_input=-1;}
    if(pid<0)return fail("managed-fork");
    mg_leader=pid;
    int listener=-1,traced=0,started=0,leader_observed=0,leader_reaped=0,alive=1,terminating=0;
    int leader_status=0,eof[3]={0,0,0},saved_error=0,stage=0;int64_t cleanup_end=0;
    uint64_t bytes[2]={0,0};size_t setup_size=0;struct setup_error failure={0};
    const char *outcome="exited";
    (void)set_nonblock(output[0]);(void)set_nonblock(error[0]);(void)set_nonblock(setup[0]);
    struct seccomp_notif_sizes sizes={0};
    if(syscall(SYS_seccomp,SECCOMP_GET_NOTIF_SIZES,0,&sizes)<0||sizes.seccomp_notif<sizeof(struct seccomp_notif)) {saved_error=errno?errno:EPROTO;terminating=1;}
    struct seccomp_notif *request=calloc(1,sizes.seccomp_notif?sizes.seccomp_notif:sizeof(*request));
    if(!request){saved_error=ENOMEM;terminating=1;}
    if(terminating){outcome="setup_error";cleanup_end=now_ms()+5000;}
    while(alive||!eof[0]||!eof[1]||!eof[2]) {
        int64_t now=now_ms();
        if(!terminating&&mg_commands()<0)goto runtime_failed;
        if(!terminating&&(cancelled||now>=mg_deadline)){outcome=cancelled?"cancelled":"timeout";terminating=1;cleanup_end=now+5000;}
        if(!started&&!leader_observed&&!terminating) {
            siginfo_t observed={0};
            if(waitid(P_PID,(id_t)pid,&observed,WSTOPPED|WEXITED|WNOHANG|WNOWAIT)==0&&observed.si_pid==pid&&
               (observed.si_code==CLD_TRAPPED||observed.si_code==CLD_STOPPED)) {
                int status=0;
                if(waitpid(pid,&status,WNOHANG|__WALL)==pid&&WIFSTOPPED(status)) {
                    if(!traced&&WSTOPSIG(status)==SIGSTOP) {
                        if(getpgid(pid)!=pid||ptrace(PTRACE_SETOPTIONS,pid,NULL,(void *)(uintptr_t)(PTRACE_O_TRACEEXEC|PTRACE_O_EXITKILL))<0||
                           ptrace(PTRACE_CONT,pid,NULL,NULL)<0)goto startup_failed;
                        traced=1;
                        listener=mg_receive_listener(bootstrap[0]);
                        if(listener<0)goto startup_failed;
                    } else if(traced&&((unsigned)status>>16)==PTRACE_EVENT_EXEC) {
                        if(ptrace(PTRACE_DETACH,pid,NULL,NULL)<0)goto startup_failed;
                        mg_started=1;
                        char message[512];int n=snprintf(message,sizeof(message),"{\"type\":\"started\",\"pid\":%d,\"profile\":\"%s\",\"uidTasksObserved\":%"PRIu64",\"uidTaskBudget\":%"PRIu64",\"uidNprocLimit\":%"PRIu64",\"inheritedNprocSoft\":%"PRIu64",\"inheritedNprocHard\":%"PRIu64"}",pid,mg_identity_gate?"managed-process-v2":mg_process_mode?"managed-process-v1":"managed-acquisition-v1",mg_uid_tasks,mg_uid_budget,mg_nproc_limit,mg_nproc_soft,mg_nproc_hard);
                        if(mg_packet(mg_channel,message,(size_t)n)<0)goto startup_failed;
                        started=1;
                    } else if(ptrace(PTRACE_CONT,pid,NULL,(void *)(uintptr_t)WSTOPSIG(status))<0)goto startup_failed;
                }
            }
        }
        if(terminating) {
            if(!leader_reaped){(void)kill(-pid,SIGKILL);(void)kill(pid,SIGKILL);}
            if(now>=cleanup_end){outcome="cleanup_error";saved_error=ETIMEDOUT;break;}
        }
        struct pollfd polls[4]={{.fd=eof[0]?-1:output[0],.events=POLLIN},{.fd=eof[1]?-1:error[0],.events=POLLIN},
            {.fd=eof[2]?-1:setup[0],.events=POLLIN},{.fd=terminating?-1:listener,.events=POLLIN}};
        if(poll(polls,4,20)<0&&errno!=EINTR)goto runtime_failed;
        if(!terminating&&(polls[3].revents&POLLIN)) {
            memset(request,0,sizes.seccomp_notif);
            if(ioctl(listener,SECCOMP_IOCTL_NOTIF_RECV,request)<0){if(errno!=EINTR&&errno!=ENOENT)goto runtime_failed;}
            else if(mg_notification(listener,request)<0)goto runtime_failed;
        }
        for(int i=0;i<3;i++)if(!eof[i]&&(polls[i].revents&(POLLIN|POLLHUP|POLLERR))) {
            char buffer[8192];ssize_t n=read(polls[i].fd,buffer,sizeof(buffer));
            if(!n)eof[i]=1;
            else if(n>0) {
                if(i==2) {
                    if((size_t)n>sizeof(failure)-setup_size){saved_error=EPROTO;goto runtime_failed;}
                    memcpy((char *)&failure+setup_size,buffer,(size_t)n);setup_size+=(size_t)n;
                    if(setup_size==sizeof(failure)){errno=failure.error;stage=failure.stage;goto startup_failed;}
                } else {
                    uint64_t remaining=c->output-bytes[0]-bytes[1];size_t accepted=(uint64_t)n<remaining?(size_t)n:(size_t)remaining;
                    size_t offset=0;
                    while(offset<accepted) {
                        if(mg_commands()<0||cancelled||now_ms()>=mg_deadline){errno=ECANCELED;goto runtime_failed;}
                        ssize_t sent=write(i+1,buffer+offset,accepted-offset);
                        if(sent>0){offset+=(size_t)sent;bytes[i]+=(uint64_t)sent;continue;}
                        if(sent<0&&(errno==EAGAIN||errno==EWOULDBLOCK||errno==EINTR)) {
                            struct pollfd ready={.fd=i+1,.events=POLLOUT};
                            if(poll(&ready,1,20)>=0||errno==EINTR)continue;
                        }
                        goto runtime_failed;
                    }
                    if(accepted<(size_t)n){outcome="output_limit";terminating=1;cleanup_end=now_ms()+5000;}
                }
            } else if(errno!=EAGAIN&&errno!=EINTR)goto runtime_failed;
        }
        if(!leader_observed) {
            siginfo_t info={0};
            if(waitid(P_PID,(id_t)pid,&info,WEXITED|WNOHANG|WNOWAIT)==0&&info.si_pid==pid&&
               (info.si_code==CLD_EXITED||info.si_code==CLD_KILLED||info.si_code==CLD_DUMPED)) {
                leader_observed=1;
                if(!terminating){terminating=1;cleanup_end=now_ms()+5000;}
                (void)kill(-pid,SIGKILL);
                if(mg_process_mode&&started) {
                    char message[128];int code=info.si_code==CLD_EXITED?info.si_status:-1;
                    int sig=info.si_code==CLD_EXITED?0:info.si_status;
                    int length=snprintf(message,sizeof(message),"{\"type\":\"exited\",\"exitCode\":%d,\"signal\":%d}",code,sig);
                    /* Cancellation stops work, not truthful terminal reporting. */
                    sig_atomic_t previous=cancelled;int64_t deadline=mg_deadline;
                    cancelled=0;mg_deadline=cleanup_end;mg_reporting=1;
                    int sent=mg_packet(mg_channel,message,(size_t)length);
                    cancelled=previous;mg_deadline=deadline;mg_reporting=0;
                    if(sent<0){outcome="broker_error";saved_error=errno?errno:EIO;}
                }
            }
        }
        if(leader_observed&&!leader_reaped){mg_reaped=1;if(waitpid(pid,&leader_status,WNOHANG)==pid)leader_reaped=1;}
        if(leader_reaped)for(;;){int status;pid_t child=waitpid(-1,&status,WNOHANG|__WALL);if(child>0)continue;if(child<0&&errno==ECHILD)alive=0;break;}
        continue;
startup_failed:
        outcome="setup_error";saved_error=errno?errno:EIO;terminating=1;cleanup_end=now_ms()+5000;continue;
runtime_failed:
        outcome=cancelled?"cancelled":now_ms()>=mg_deadline?"timeout":"broker_error";
        saved_error=errno?errno:EIO;terminating=1;cleanup_end=now_ms()+5000;
    }
    free(request);if(listener>=0)close(listener);close(bootstrap[0]);close(output[0]);close(error[0]);close(setup[0]);
    int complete=!alive&&leader_reaped;
    if(!complete)outcome="cleanup_error";
    if(!started&&!strcmp(outcome,"exited")){outcome="setup_error";saved_error=EIO;}
    int code=leader_reaped&&WIFEXITED(leader_status)?WEXITSTATUS(leader_status):-1;
    int sig=leader_reaped&&WIFSIGNALED(leader_status)?WTERMSIG(leader_status):0;
    char result[512];int length=snprintf(result,sizeof(result),"{\"type\":\"result\",\"outcome\":\"%s\",\"exitCode\":%d,\"signal\":%d,\"cleanupComplete\":%s,\"started\":%s,\"grants\":%"PRIu64",\"denials\":%"PRIu64",\"stdoutBytes\":%"PRIu64",\"stderrBytes\":%"PRIu64",\"stage\":%d,\"errno\":%d}",outcome,code,sig,complete?"true":"false",started?"true":"false",mg_grants,mg_denials,bytes[0],bytes[1],stage,saved_error);
    if(mg_command>=0){close(mg_command);mg_command=-1;}
    cancelled=0;mg_deadline=now_ms()+1000;
    if(mg_packet(mg_channel,result,(size_t)length)<0)return 1;
    return !strcmp(outcome,"exited")?0:1;
}
int main(int argc,char **argv) {
    /* All roots and native FD numbers are supplied by the trusted parent. */
    if(argc<10){fprintf(stderr,"usage: managed ROOT_FD CONTROL_FD STATIC_ELF WALL_MS ADDRESS_BYTES OUTPUT_BYTES UID_TASK_BUDGET [--process-v2 STDIN_FD COMMAND_FD ENV_FD] -- ARGV...\n");return 2;}
    int arg_start=9,env_fd=-1;
    if(!strcmp(argv[8],"--process-v1")||!strcmp(argv[8],"--process-v2")) {
        mg_identity_gate=!strcmp(argv[8],"--process-v2");
        if(argc<14||strcmp(argv[12],"--"))return 2;
        int *fields[]={&mg_input,&mg_command,&env_fd};
        for(int i=0;i<3;i++) {
            char *end=NULL;errno=0;unsigned long value=strtoul(argv[9+i],&end,10);
            if(errno||!argv[9+i][0]||*end||value<3||value>INT_MAX)return 2;
            *fields[i]=(int)value;
        }
        if(mg_input==mg_command||mg_input==env_fd||mg_command==env_fd)return 2;
        mg_process_mode=1;arg_start=13;
    }else if(strcmp(argv[8],"--"))return 2;
    uint64_t root,control,wall,memory,output,budget;
    char *end=NULL;
    errno=0;root=strtoull(argv[1],&end,10);if(errno||!*argv[1]||*end||root<3||root>INT_MAX)return 2;
    errno=0;control=strtoull(argv[2],&end,10);if(errno||!*argv[2]||*end||control<3||control>INT_MAX||root==control)return 2;
    errno=0;wall=strtoull(argv[4],&end,10);if(errno||!*argv[4]||*end||wall<1||wall>3600000)return 2;
    errno=0;memory=strtoull(argv[5],&end,10);if(errno||!*argv[5]||*end||memory<16777216||memory>NR_MAX_ADDRESS_SPACE_BYTES)return 2;
    errno=0;output=strtoull(argv[6],&end,10);if(errno||!*argv[6]||*end||output<1||output>67108864)return 2;
    errno=0;budget=strtoull(argv[7],&end,10);if(errno||!*argv[7]||*end||budget<1||budget>UINT32_MAX)return 2;
    if(!no_privilege()||syscall(SYS_landlock_create_ruleset,NULL,0,1U)<6)return fail("managed-admission");
    if(mg_uid_limit(budget)<0)return fail("managed-uid-task-budget");
    mg_root=(int)root;mg_channel=(int)control;
    if(mg_process_mode&&(mg_input==mg_root||mg_input==mg_channel||mg_command==mg_root||mg_command==mg_channel||env_fd==mg_root||env_fd==mg_channel))return fail("managed-process-fds");
    struct stat root_info;unsigned objects=0;
    if(fstat(mg_root,&root_info)<0||!S_ISDIR(root_info.st_mode)||scan_workspace(mg_root,&objects,0)<0)return fail("managed-root");
    char procpath[64];snprintf(procpath,sizeof(procpath),"/proc/self/fd/%d",mg_root);
    ssize_t n=readlink(procpath,mg_root_path,sizeof(mg_root_path)-1);
    if(n<1||n>=(ssize_t)sizeof(mg_root_path)-1)return fail("managed-root-path");
    mg_root_path[n]=0;
    if(!canonical(mg_root_path)||forbidden_tree(mg_root_path)||!canonical(argv[3]))return fail("managed-path");
    struct sockaddr_un address;socklen_t address_length=sizeof(address),type_length=sizeof(int);int type=0;
    struct ucred peer;socklen_t peer_length=sizeof(peer);
    if(getsockname(mg_channel,(struct sockaddr *)&address,&address_length)<0||address.sun_family!=AF_UNIX||
       getsockopt(mg_channel,SOL_SOCKET,SO_TYPE,&type,&type_length)<0||type!=SOCK_SEQPACKET||
       getsockopt(mg_channel,SOL_SOCKET,SO_PEERCRED,&peer,&peer_length)<0||peer_length!=sizeof(peer)||peer.uid!=getuid()||peer.pid!=getppid())return fail("managed-channel");
    if(mg_process_mode) {
        address_length=sizeof(address);type_length=sizeof(type);peer_length=sizeof(peer);
        if(getsockname(mg_command,(struct sockaddr *)&address,&address_length)<0||address.sun_family!=AF_UNIX||
           getsockopt(mg_command,SOL_SOCKET,SO_TYPE,&type,&type_length)<0||type!=SOCK_SEQPACKET||
           getsockopt(mg_command,SOL_SOCKET,SO_PEERCRED,&peer,&peer_length)<0||peer_length!=sizeof(peer)||peer.uid!=getuid()||peer.pid!=getppid())return fail("managed-command-channel");
        struct stat input_info;
        int flags=fcntl(mg_input,F_GETFL);
        if(flags<0||(flags&O_ACCMODE)!=O_RDONLY||fstat(mg_input,&input_info)<0||!S_ISFIFO(input_info.st_mode)||input_info.st_uid!=getuid())return fail("managed-input-pipe");
    }
    mg_exec=open(argv[3],O_RDONLY|O_CLOEXEC|O_NOFOLLOW);struct stat executable;
    if(mg_exec<0||fstat(mg_exec,&executable)<0||!S_ISREG(executable.st_mode)||(executable.st_mode&07000)||
       !ordinary_filesystem(mg_exec)||mg_static_elf(mg_exec)<0)return fail("managed-static-executable");
    struct config c={.wall=wall,.memory=memory,.output=output,.file=16777216,.fds=128,.processes=mg_nproc_limit,.count=1};
    c.grants[0]=(struct grant){.fd=mg_exec,.rights=LL_EXECUTE|LL_READ_FILE};
    char *environment=NULL;
    if(mg_process_mode) {
        struct stat env_info;int seals=fcntl(env_fd,F_GET_SEALS);
        int required=F_SEAL_WRITE|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_SEAL;
        if(seals<0||(seals&required)!=required||fstat(env_fd,&env_info)<0||!S_ISREG(env_info.st_mode)||env_info.st_uid!=getuid()||env_info.st_size<0||env_info.st_size>65536)return fail("managed-environment-seals");
        size_t size=(size_t)env_info.st_size;environment=calloc(1,size+1);
        if(!environment)return fail("managed-environment-allocation");
        if(pread(env_fd,environment,size,0)!=(ssize_t)size)return fail("managed-environment-read");
        close(env_fd);env_fd=-1;
        unsigned count=0;size_t offset=0;
        while(offset<size) {
            char *entry=environment+offset,*end=memchr(entry,0,size-offset),*equal=end?memchr(entry,'=',(size_t)(end-entry)):NULL;
            if(!end||!equal||equal==entry||count==MAX_ENV)return fail("managed-environment-shape");
            for(unsigned i=0;i<count;i++)if(!strncmp(c.env[i],entry,(size_t)(equal-entry))&&c.env[i][equal-entry]=='=')return fail("managed-environment-duplicate");
            c.env[count++]=entry;offset=(size_t)(end-environment)+1;
        }
    }
    if(argc-arg_start>MAX_ARGS)return 2;
    for(int i=arg_start;i<argc;i++)c.argv[i-arg_start]=argv[i];
    struct sigaction action={.sa_handler=cancel_signal};sigemptyset(&action.sa_mask);
    if(sigaction(SIGTERM,&action,NULL)<0||sigaction(SIGINT,&action,NULL)<0)return fail("managed-signals");
    signal(SIGPIPE,SIG_IGN);umask(0077);(void)set_nonblock(1);(void)set_nonblock(2);
    mg_deadline=now_ms()+(int64_t)wall;
    if(mg_identity_gate&&mg_supervisor_identity()<0)return fail("managed-supervisor-identity");
    int result=mg_supervise(&c);free(environment);close(mg_exec);close(mg_root);close(mg_channel);return result;
}
