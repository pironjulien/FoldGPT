/* SPDX-License-Identifier: GPL-3.0-only
 * Native dynamic process supervisor. Every policy-sensitive pathname syscall
 * is mediated; no pointer-bearing syscall is approved with CONTINUE.
 */
#define _GNU_SOURCE
#include "native-runner-seccomp.h"
#include <dirent.h>
#include <linux/capability.h>
#include <linux/openat2.h>
#ifdef __ANDROID__
#include <linux/pidfd.h>
#endif
#include <linux/stat.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <time.h>

#if defined(__aarch64__)
#define BS_ARCH AUDIT_ARCH_AARCH64
#else
#define BS_ARCH AUDIT_ARCH_X86_64
#endif

#define MAX_FRAME 196608
#ifndef PIDFD_THREAD
/* Linux6.12.58 UAPI and NDK r29 linux/pidfd.h: older host headers may
 * omit the name although the running kernel implements the exact flag. */
#define PIDFD_THREAD O_EXCL
#endif
#define MAX_PATH 4096
#define READ_FILE (1ULL<<2)
#define READ_DIR (1ULL<<3)
#define WRITE_FILE (1ULL<<1)
#define EXECUTE (1ULL<<0)
#define TRUNCATE (1ULL<<14)
struct ruleset { uint64_t fs,net,scoped; };
struct rule { uint64_t allowed; int32_t fd; } __attribute__((packed));
struct configuration {
  uint64_t wall,data,file,output,tasks,cpu,descriptors;
  uint32_t argc,envc,grants;
  char *workspace,*cwd,*executable,*argv[257],*env[129],*runtime[64];
  uint32_t execute[64];
  int pins[64],root,cwd_fd,input,control,command;
};
static struct configuration cfg;
static int64_t deadline;
static volatile sig_atomic_t cancelled;
static int leader=-1,reaped;
static uint64_t grants,denials;
static unsigned char envelope[MAX_FRAME+1];
static int64_t milliseconds(void) {
  struct timespec t;if(clock_gettime(CLOCK_MONOTONIC,&t)<0)return -1;
  return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int nonblock(int fd) { int f=fcntl(fd,F_GETFL);return f<0?-1:fcntl(fd,F_SETFL,f|O_NONBLOCK); }
static int commands(void) {
  for(int i=0;i<32;i++) {
    char b[2];ssize_t n=recv(cfg.command,b,sizeof(b),MSG_DONTWAIT);
    if(!n){cancelled=1;return 0;}
    if(n<0){if(errno==EAGAIN||errno==EWOULDBLOCK)return 0;if(errno==EINTR)continue;return -1;}
    if(n!=1||(b[0]!='I'&&b[0]!='T')){errno=EPROTO;return -1;}
    if(b[0]=='T')cancelled=1;
    else if(leader>0&&!reaped&&kill(-leader,SIGINT)<0&&errno!=ESRCH)return -1;
  }
  return 0;
}
static int packet(const void *data,size_t length,int during_cleanup) {
  int64_t end=during_cleanup?milliseconds()+500:deadline;
  for(;;) {
    if(commands()<0)return -1;
    if((!during_cleanup&&cancelled)||milliseconds()>=end){errno=ECANCELED;return -1;}
    ssize_t n=send(cfg.control,data,length,MSG_NOSIGNAL|MSG_DONTWAIT);
    if(n==(ssize_t)length)return 0;
    if(n>=0){errno=EIO;return -1;}
    if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK)return -1;
    struct pollfd p={cfg.control,POLLOUT,0};(void)poll(&p,1,20);
  }
}
static int receive(void *data,size_t length) {
  for(;;) {
    if(commands()<0)return -1;
    if(cancelled||milliseconds()>=deadline){errno=ECANCELED;return -1;}
    struct iovec vec={data,length};struct msghdr m={.msg_iov=&vec,.msg_iovlen=1};
    ssize_t n=recvmsg(cfg.control,&m,MSG_DONTWAIT|MSG_CMSG_CLOEXEC);
    if(n>0){if(m.msg_flags&(MSG_TRUNC|MSG_CTRUNC)){errno=EPROTO;return -1;}return (int)n;}
    if(!n){errno=EPIPE;return -1;}
    if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK)return -1;
    struct pollfd p={cfg.control,POLLIN,0};(void)poll(&p,1,20);
  }
}
static int identity(void) {
  uid_t a,b,c;gid_t d,e,f;
  struct __user_cap_header_struct h={.version=_LINUX_CAPABILITY_VERSION_3};
  struct __user_cap_data_struct caps[2]={{0},{0}};
  if(getresuid(&a,&b,&c)<0||getresgid(&d,&e,&f)<0||!a||a!=b||a!=c||d!=e||d!=f||
     syscall(SYS_capget,&h,caps)<0||caps[0].effective||caps[1].effective||
     caps[0].permitted||caps[1].permitted||caps[0].inheritable||caps[1].inheritable){errno=EPERM;return -1;}
  for(unsigned bit=0;bit<64;bit++){int r=prctl(PR_CAP_AMBIENT,PR_CAP_AMBIENT_IS_SET,bit,0,0);
    if(!r)continue;
    if(r<0&&errno==EINVAL)break;
    errno=EPERM;return -1;}
  return 0;
}
static void cancelled_signal(int number) { (void)number;cancelled=1; }
static int uid_tasks(rlim_t *ceiling) {
  DIR *directory=opendir("/proc");if(!directory)return -1;
  struct dirent *entry;uint64_t total=0;int failed=0;
  while((entry=readdir(directory))){char *end;long pid=strtol(entry->d_name,&end,10);if(!*entry->d_name||*end||pid<=0)continue;
    char path[80];struct stat st;snprintf(path,sizeof(path),"/proc/%ld",pid);
    if(stat(path,&st)<0||st.st_uid!=getuid())continue;
    snprintf(path,sizeof(path),"/proc/%ld/status",pid);FILE *f=fopen(path,"re");
    if(!f){if(errno!=ENOENT&&errno!=ESRCH)failed=1;continue;}
    char line[512];unsigned long threads=0;while(fgets(line,sizeof(line),f))if(sscanf(line,"Threads: %lu",&threads)==1)break;
    fclose(f);if(!threads||total>4096){failed=1;break;}total+=threads;
  }
  closedir(directory);if(failed||!total){errno=EACCES;return -1;}
  struct rlimit inherited;if(getrlimit(RLIMIT_NPROC,&inherited)<0)return -1;
  *ceiling=(rlim_t)(total+cfg.tasks);if(*ceiling>inherited.rlim_cur)*ceiling=inherited.rlim_cur;
  if(*ceiling>inherited.rlim_max)*ceiling=inherited.rlim_max;
  if(*ceiling<=total){errno=EAGAIN;return -1;}return 0;
}
static int keep(const int *fds,size_t count) {
  int ordered[16];if(count>16){errno=EINVAL;return -1;}
  memcpy(ordered,fds,count*sizeof(int));
  for(size_t i=0;i<count;i++)for(size_t j=i+1;j<count;j++)if(ordered[j]<ordered[i]){int t=ordered[i];ordered[i]=ordered[j];ordered[j]=t;}
  unsigned first=3;
  for(size_t i=0;i<count;i++){
    if(ordered[i]<3||(i&&ordered[i]==ordered[i-1])){errno=EINVAL;return -1;}
    if(first<(unsigned)ordered[i]&&syscall(SYS_close_range,first,(unsigned)ordered[i]-1,0)<0)return -1;
    first=(unsigned)ordered[i]+1;
  }
  return (int)syscall(SYS_close_range,first,UINT_MAX,0);
}
static char *string(unsigned char **p,unsigned char *end) {
  if(end-*p<4)return NULL;
  uint32_t n;memcpy(&n,*p,4);*p+=4;
  if(n>65536||end-*p<(ptrdiff_t)n||memchr(*p,0,n))return NULL;
  char *s=malloc((size_t)n+1);if(!s)return NULL;
  memcpy(s,*p,n);s[n]=0;*p+=n;return s;
}
static int configuration(int fd) {
  struct stat st;int seals=fcntl(fd,F_GET_SEALS);
  int required=F_SEAL_SEAL|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_WRITE;
  if(fstat(fd,&st)<0||st.st_size<76||st.st_size>MAX_FRAME||(seals&required)!=required)return -1;
  if(pread(fd,envelope,(size_t)st.st_size,0)!=st.st_size)return -1;
  unsigned char *p=envelope,*end=p+st.st_size;
  if(memcmp(p,"FGBP0001",8)){errno=EPROTO;return -1;}p+=8;
  uint64_t limits[7];memcpy(limits,p,sizeof(limits));p+=sizeof(limits);
  cfg.wall=limits[0];cfg.data=limits[1];cfg.file=limits[2];cfg.output=limits[3];cfg.tasks=limits[4];cfg.cpu=limits[5];cfg.descriptors=limits[6];
  uint32_t counts[3];memcpy(counts,p,sizeof(counts));p+=sizeof(counts);cfg.argc=counts[0];cfg.envc=counts[1];cfg.grants=counts[2];
  if(!cfg.argc||cfg.argc>256||cfg.envc>128||cfg.grants>64||!cfg.wall||cfg.wall>3600000||
     cfg.data<16777216||cfg.data>2147483648ULL||!cfg.file||cfg.file>1073741824||
     !cfg.output||cfg.output>67108864||!cfg.tasks||cfg.tasks>128||!cfg.cpu||cfg.cpu>3600||
     cfg.descriptors<16||cfg.descriptors>1024){errno=EINVAL;return -1;}
  cfg.workspace=string(&p,end);cfg.cwd=string(&p,end);cfg.executable=string(&p,end);
  if(!cfg.workspace||!cfg.cwd||!cfg.executable||cfg.workspace[0]!='/'||cfg.executable[0]!='/')return -1;
  for(unsigned i=0;i<cfg.argc;i++)if(!(cfg.argv[i]=string(&p,end)))return -1;
  for(unsigned i=0;i<cfg.envc;i++)if(!(cfg.env[i]=string(&p,end))||!strchr(cfg.env[i],'='))return -1;
  for(unsigned i=0;i<cfg.grants;i++){
    if(end-p<4)return -1;
    memcpy(&cfg.execute[i],p,4);p+=4;
    if(cfg.execute[i]>1||!(cfg.runtime[i]=string(&p,end))||cfg.runtime[i][0]!='/')return -1;
  }
  if(p!=end){errno=EPROTO;return -1;}return 0;
}
static int beneath(int root,const char *path,int flags,mode_t mode) {
  struct open_how how={.flags=(uint64_t)flags|O_CLOEXEC,.mode=mode,
    .resolve=RESOLVE_BENEATH|RESOLVE_NO_MAGICLINKS|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
  return (int)syscall(SYS_openat2,root,path,&how,sizeof(how));
}
static int setup_paths(void) {
  struct stat root,actual;
  if(fstat(cfg.root,&root)<0||!S_ISDIR(root.st_mode)||root.st_uid!=getuid()||(root.st_mode&0077)||
     lstat(cfg.workspace,&actual)<0||!S_ISDIR(actual.st_mode)||root.st_dev!=actual.st_dev||root.st_ino!=actual.st_ino){errno=EPERM;return -1;}
  cfg.cwd_fd=beneath(cfg.root,cfg.cwd,O_RDONLY|O_DIRECTORY,0);if(cfg.cwd_fd<0)return -1;
  for(unsigned i=0;i<cfg.grants;i++){
    cfg.pins[i]=open(cfg.runtime[i],O_PATH|O_CLOEXEC);
    struct stat s;if(cfg.pins[i]<0||fstat(cfg.pins[i],&s)<0||(!S_ISREG(s.st_mode)&&!S_ISDIR(s.st_mode)))return -1;
  }
  return 0;
}
static int limit(int resource,rlim_t value) {
  struct rlimit old;if(getrlimit(resource,&old)<0)return -1;
  if(value>old.rlim_cur)value=old.rlim_cur;
  if(value>old.rlim_max)value=old.rlim_max;
  struct rlimit r={value,value};return setrlimit(resource,&r);
}
static int ll_rule(int rs,int fd,uint64_t rights) {
  struct stat s;if(fstat(fd,&s)<0)return -1;if(!S_ISDIR(s.st_mode))rights&=~READ_DIR;
  struct rule r={rights,fd};return (int)syscall(SYS_landlock_add_rule,rs,1,&r,0);
}
static int landlock(void) {
  struct ruleset r={(1ULL<<16)-1,0,3};int rs=(int)syscall(SYS_landlock_create_ruleset,&r,sizeof(r),0);if(rs<0)return -1;
  /* This is a kernel ceiling. Every acquisition and namespace change inside
   * it is separately mediated against the complete portable policy. */
  uint64_t workspace=READ_FILE|READ_DIR|WRITE_FILE|TRUNCATE|(1ULL<<7)|(1ULL<<8);
  int result=ll_rule(rs,cfg.root,workspace);
  for(unsigned i=0;!result&&i<cfg.grants;i++)result=ll_rule(rs,cfg.pins[i],READ_FILE|READ_DIR|(cfg.execute[i]?EXECUTE:0));
  if(!result)result=(int)syscall(SYS_landlock_restrict_self,rs,0);
  int e=errno;close(rs);errno=e;return result;
}
#define NOTIFY(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_##n,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_USER_NOTIF)
#define DENY(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,__NR_##n,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ERRNO|EPERM)
static int notification_filter(void) {
  const struct sock_filter f[]={
    BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,arch)),
    BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K,BS_ARCH,1,0),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
    BPF_STMT(BPF_LD|BPF_W|BPF_ABS,offsetof(struct seccomp_data,nr)),
#if defined(__x86_64__)
    BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K,0x40000000U,0,1),BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_KILL_PROCESS),
#endif
    NOTIFY(openat),NOTIFY(openat2),NOTIFY(newfstatat),NOTIFY(statx),NOTIFY(readlinkat),NOTIFY(mkdirat),
    /* fchdir takes a capability FD, never a pointer: every available directory
     * FD was acquired by this broker. A concurrent FD replacement can select
     * only another admitted capability. Relative acquisition pins actual cwd. */
    DENY(chdir),DENY(unlinkat),DENY(renameat),DENY(renameat2),DENY(linkat),DENY(symlinkat),
    DENY(faccessat),DENY(faccessat2),NOTIFY(getdents64),DENY(statfs),DENY(truncate),
#ifdef __NR_open
    NOTIFY(open),NOTIFY(creat),NOTIFY(stat),NOTIFY(lstat),NOTIFY(readlink),NOTIFY(mkdir),
    DENY(rmdir),DENY(unlink),DENY(rename),DENY(link),DENY(symlink),DENY(access),DENY(getdents),
#endif
    BPF_STMT(BPF_RET|BPF_K,SECCOMP_RET_ALLOW)};
  struct sock_fprog p={(unsigned short)(sizeof(f)/sizeof(f[0])),(struct sock_filter*)f};
  return (int)syscall(SYS_seccomp,SECCOMP_SET_MODE_FILTER,SECCOMP_FILTER_FLAG_NEW_LISTENER,&p);
}
static int send_fd(int socket,int fd,char tag) {
  union {struct cmsghdr align;char b[CMSG_SPACE(sizeof(int))];} control={0};
  struct iovec v={&tag,1};struct msghdr m={.msg_iov=&v,.msg_iovlen=1,.msg_control=control.b,.msg_controllen=sizeof(control.b)};
  struct cmsghdr *c=CMSG_FIRSTHDR(&m);c->cmsg_level=SOL_SOCKET;c->cmsg_type=SCM_RIGHTS;c->cmsg_len=CMSG_LEN(sizeof(int));
  memcpy(CMSG_DATA(c),&fd,sizeof(int));return sendmsg(socket,&m,MSG_NOSIGNAL)==1?0:-1;
}
static int receive_fd(int socket) {
  char tag;union {struct cmsghdr align;char b[CMSG_SPACE(8*sizeof(int))];} control={0};
  struct iovec v={&tag,1};struct msghdr m={.msg_iov=&v,.msg_iovlen=1,.msg_control=control.b,.msg_controllen=sizeof(control.b)};
  ssize_t n=recvmsg(socket,&m,MSG_CMSG_CLOEXEC);int fd=-1,count=0,valid=n==1&&tag=='L'&&!(m.msg_flags&(MSG_TRUNC|MSG_CTRUNC));
  for(struct cmsghdr *c=CMSG_FIRSTHDR(&m);c;c=CMSG_NXTHDR(&m,c)){
    if(c->cmsg_level!=SOL_SOCKET||c->cmsg_type!=SCM_RIGHTS||c->cmsg_len<CMSG_LEN(0)){valid=0;continue;}
    size_t size=c->cmsg_len-CMSG_LEN(0);if(size%sizeof(int))valid=0;
    for(size_t k=0;k+sizeof(int)<=size;k+=sizeof(int)){int x;memcpy(&x,(char*)CMSG_DATA(c)+k,sizeof(x));if(!count++)fd=x;else close(x);}
  }
  if(!valid||count!=1){if(fd>=0)close(fd);errno=EPROTO;return -1;}return fd;
}
static void child(int output,int error,int setup,int listener_socket,pid_t parent,rlim_t tasks) {
  int stage=1;
  if(setpgid(0,0)<0||prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0)<0||getppid()!=parent||
     dup2(cfg.input,0)<0||dup2(output,1)<0||dup2(error,2)<0||identity()<0||
     prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)<0)goto failed;
  stage=2;
  if(fchdir(cfg.cwd_fd)<0||limit(RLIMIT_CORE,0)<0||limit(RLIMIT_DATA,cfg.data)<0||
     limit(RLIMIT_FSIZE,cfg.file)<0||limit(RLIMIT_NOFILE,cfg.descriptors)<0||limit(RLIMIT_CPU,cfg.cpu)<0||limit(RLIMIT_NPROC,tasks)<0)goto failed;
  struct sigaction normal={.sa_handler=SIG_DFL};sigemptyset(&normal.sa_mask);
  if(sigaction(SIGINT,&normal,NULL)<0||sigaction(SIGTERM,&normal,NULL)<0||sigaction(SIGPIPE,&normal,NULL)<0)goto failed;
  stage=3;if(landlock()<0)goto failed;
  {int descriptors[]={setup,listener_socket};if(keep(descriptors,2)<0)goto failed;}
  stage=4;
  int listener=notification_filter();if(listener<0)goto failed;
  if(send_fd(listener_socket,listener,'L')<0)goto failed;
  close(listener);close(listener_socket);
  if(nr_install_seccomp()<0)goto failed;
  stage=0;if(write(setup,&stage,sizeof(stage))!=sizeof(stage))_exit(70);
  execve(cfg.executable,cfg.argv,cfg.env);
  stage=5;
failed:;
  int message[2]={stage,errno};ssize_t n=write(setup,message,sizeof(message));(void)n;_exit(70);
}
static int valid(int listener,uint64_t id){return ioctl(listener,SECCOMP_IOCTL_NOTIF_ID_VALID,&id)==0;}
static int reply(int listener,uint64_t id,int64_t value,int error) {
  struct seccomp_notif_resp r={.id=id,.val=value,.error=-error};
  if(ioctl(listener,SECCOMP_IOCTL_NOTIF_SEND,&r)<0&&errno!=ENOENT)return -1;
  return 0;
}
/* Pin the mm through procfs before validating the still-blocked notification.
 * Once pinned it cannot become a different process after numeric PID reuse.
 * There is no ptrace attach and no mutable-pointer CONTINUE path. */
static int memory(int listener,const struct seccomp_notif *n) {
  char path[80];snprintf(path,sizeof(path),"/proc/%u/mem",n->pid);
  int fd=open(path,O_RDWR|O_CLOEXEC);if(fd<0)return -1;
  if(!valid(listener,n->id)){close(fd);errno=ESRCH;return -1;}return fd;
}
static int copy_path(int mem,uint64_t address,char path[MAX_PATH]) {
  if(address>INT64_MAX){errno=EFAULT;return -1;}
  for(size_t used=0;used<MAX_PATH;){
    size_t amount=256;if(amount>MAX_PATH-used)amount=MAX_PATH-used;
    ssize_t got=pread(mem,path+used,amount,(off_t)(address+used));
    if(got<=0){errno=EFAULT;return -1;}
    if(memchr(path+used,0,(size_t)got))return 0;
    used+=(size_t)got;
  }
  errno=ENAMETOOLONG;return -1;
}
static int actual_path(int listener,const struct seccomp_notif *n,char path[MAX_PATH]) {
  if(path[0]=='/'||!path[0])return 0;
  char proc[96],cwd[MAX_PATH],joined[MAX_PATH];
  snprintf(proc,sizeof(proc),"/proc/%u/cwd",n->pid);
  int fd=open(proc,O_PATH|O_DIRECTORY|O_CLOEXEC);if(fd<0)return -1;
  if(!valid(listener,n->id)){close(fd);errno=ESRCH;return -1;}
  snprintf(proc,sizeof(proc),"/proc/self/fd/%d",fd);
  ssize_t length=readlink(proc,cwd,sizeof(cwd)-1);int saved=errno;close(fd);
  if(length<0){errno=saved;return -1;}cwd[length]=0;
  if(cwd[0]!='/'){errno=EACCES;return -1;}
  int count=snprintf(joined,sizeof(joined),"%s/%s",cwd,path);
  if(count<0||count>=MAX_PATH){errno=ENAMETOOLONG;return -1;}
  memcpy(path,joined,(size_t)count+1);return 0;
}
static int contained(const char *root,const char *path) {
  size_t n=strlen(root);return !strncmp(root,path,n)&&(!path[n]||path[n]=='/');
}
static int runtime_object(const char *path,int nofollow,char resolved[MAX_PATH]) {
  int candidate=0;for(unsigned i=0;i<cfg.grants;i++)if(contained(cfg.runtime[i],path))candidate=1;
  if(!candidate)return 0;
  if(nofollow&&path[0]&&path[strlen(path)-1]!='/'){
    char parent[MAX_PATH],canonical[MAX_PATH];strcpy(parent,path);
    char *last=strrchr(parent,'/');if(!last){errno=EINVAL;return -1;}
    char name[MAX_PATH];strcpy(name,last+1);if(last==parent)last[1]=0;else *last=0;
    if(!realpath(parent,canonical))return -1;
    if(!strcmp(name,".")||!strcmp(name,"..")){if(!realpath(path,resolved))return -1;}
    else{int length=snprintf(resolved,MAX_PATH,"%s%s%s",canonical,strcmp(canonical,"/")?"/":"",name);
      if(length<0||length>=MAX_PATH){errno=ENAMETOOLONG;return -1;}}
  }else if(!realpath(path,resolved))return -1;
  for(unsigned i=0;i<cfg.grants;i++)if(contained(cfg.runtime[i],resolved))return 1;
  errno=EACCES;return -1;
}
static int runtime_path(const char *path,char resolved[MAX_PATH]) {return runtime_object(path,0,resolved);}
static int pinned_worker_fd(int listener,const struct seccomp_notif *n,int number,int shared_offset) {
  if(number<0){errno=EBADF;return -1;}
  int fd;
  if(shared_offset){
    /* Notification pid is a TID, including non-leader Python/Bionic threads.
     * Pin precisely that task, never substitute its thread-group leader. */
    int identity=(int)syscall(SYS_pidfd_open,n->pid,PIDFD_THREAD);if(identity<0)return -1;
    if(!valid(listener,n->id)){close(identity);errno=ESRCH;return -1;}
    fd=(int)syscall(SYS_pidfd_getfd,identity,number,0);int saved=errno;close(identity);errno=saved;
  }else{
    char path[96];snprintf(path,sizeof(path),"/proc/%u/fd/%d",n->pid,number);fd=open(path,O_PATH|O_CLOEXEC);
  }
  if(fd>=0&&!valid(listener,n->id)){close(fd);errno=ESRCH;return -1;}return fd;
}
static int authorize_directory(int listener,const struct seccomp_notif *n,int fd,const char *path);
static int directory_setup_error(int listener,const struct seccomp_notif *n,int error) {
  if(!valid(listener,n->id))return 0;
  /* libc readdir may convert ENOENT into EOF. A broker setup failure must
   * remain a real error; only the actual getdents syscall may report EOF. */
  return reply(listener,n->id,0,error==ENOENT?EOPNOTSUPP:error);
}
static int directory_read(int listener,const struct seccomp_notif *n,int mem) {
  if(n->data.args[2]>65536||!n->data.args[2]||n->data.args[1]>INT64_MAX)return reply(listener,n->id,0,EINVAL);
  int fd=pinned_worker_fd(listener,n,(int)n->data.args[0],1);
  if(fd<0)return directory_setup_error(listener,n,errno);
  char proc[80],path[MAX_PATH],resolved[MAX_PATH];snprintf(proc,sizeof(proc),"/proc/self/fd/%d",fd);
  ssize_t length=readlink(proc,path,sizeof(path)-1);if(length<0){int e=errno;close(fd);return directory_setup_error(listener,n,e);}path[length]=0;
  if(runtime_path(path,resolved)!=1){
    int admitted=authorize_directory(listener,n,fd,path);int saved=errno;
    if(admitted){close(fd);return admitted<0?-1:directory_setup_error(listener,n,saved);}
  }
  char *buffer=malloc((size_t)n->data.args[2]);if(!buffer){close(fd);return reply(listener,n->id,0,ENOMEM);}
  ssize_t got=syscall(SYS_getdents64,fd,buffer,(size_t)n->data.args[2]);int error=got<0?errno:0;
  if(got>0&&pwrite(mem,buffer,(size_t)got,(off_t)n->data.args[1])!=got)error=EFAULT;
  free(buffer);close(fd);return reply(listener,n->id,got,error);
}
struct decision {uint64_t id;int32_t error;uint32_t length;uint64_t device,inode,parent_device,parent_inode;};
static int authorize(uint64_t id,const char *path,const char *operation,uint64_t flags,
                     char relative[MAX_PATH],struct decision *decision) {
  char encoded[MAX_PATH*2+1],message[MAX_PATH*2+256];static const char hex[]="0123456789abcdef";
  size_t size=strlen(path);for(size_t i=0;i<size;i++){encoded[2*i]=hex[(unsigned char)path[i]>>4];encoded[2*i+1]=hex[(unsigned char)path[i]&15];}encoded[2*size]=0;
  int count=snprintf(message,sizeof(message),"{\"type\":\"acquire\",\"id\":%llu,\"operation\":\"%s\",\"flags\":%llu,\"pathHex\":\"%s\"}",
    (unsigned long long)id,operation,(unsigned long long)flags,encoded);
  if(packet(message,(size_t)count,0)<0)return -1;
  unsigned char response[sizeof(*decision)+MAX_PATH];int length=receive(response,sizeof(response));
  if(length<(int)sizeof(*decision)){errno=EPROTO;return -1;}memcpy(decision,response,sizeof(*decision));
  if(decision->id!=id||decision->error<0||decision->error>4095||decision->length>=MAX_PATH||
     length!=(int)(sizeof(*decision)+decision->length)||memchr(response+sizeof(*decision),0,decision->length)) {errno=EPROTO;return -1;}
  memcpy(relative,response+sizeof(*decision),decision->length);relative[decision->length]=0;
  if(decision->error){errno=decision->error;return 1;}
  if(!relative[0]||relative[0]=='/'){errno=EPROTO;return -1;}return 0;
}
static int pin_project(const char *path,const struct decision *d,int flags,mode_t mode,int create_directory) {
  char parent_path[MAX_PATH],*name;strcpy(parent_path,path);char *slash=strrchr(parent_path,'/');
  if(slash){*slash=0;name=slash+1;}else{name=parent_path;}
  const char *parent_name=slash?parent_path:".";
  int parent=beneath(cfg.root,parent_name,O_PATH|O_DIRECTORY,0);if(parent<0)return -1;
  struct stat info;if(fstat(parent,&info)<0||info.st_dev!=d->parent_device||info.st_ino!=d->parent_inode){close(parent);errno=ESTALE;return -1;}
  int pin=beneath(parent,name,O_PATH|O_NOFOLLOW,0);
  if(pin<0&&errno!=ENOENT){close(parent);return -1;}
  if(pin>=0){
    if(fstat(pin,&info)<0||info.st_dev!=d->device||info.st_ino!=d->inode||
       (!S_ISREG(info.st_mode)&&!S_ISDIR(info.st_mode))||(S_ISREG(info.st_mode)&&info.st_nlink!=1)){
      close(pin);close(parent);errno=ESTALE;return -1;}
    if(create_directory){close(pin);close(parent);errno=EEXIST;return -1;}
  }else if(d->device||d->inode){close(parent);errno=ESTALE;return -1;}
  int result;
  if(create_directory)result=mkdirat(parent,name,mode);
  else if(flags==O_PATH)result=pin>=0?dup(pin):-1;
  else if(pin>=0){
    if((flags&O_CREAT)&&(flags&O_EXCL)){errno=EEXIST;result=-1;}
    else {char proc[80];snprintf(proc,sizeof(proc),"/proc/self/fd/%d",pin);result=open(proc,(flags&~(O_CREAT|O_EXCL|O_NOFOLLOW))|O_CLOEXEC);}
  }else result=beneath(parent,name,flags|O_EXCL,mode);
  int saved=errno;if(pin>=0)close(pin);close(parent);errno=saved;return result;
}
static int authorize_directory(int listener,const struct seccomp_notif *n,int fd,const char *path) {
  char relative[MAX_PATH];struct decision d;
  int admitted=authorize(n->id,path,"list",0,relative,&d);if(admitted)return admitted;
  if(!valid(listener,n->id)){errno=ESRCH;return 1;}
  struct stat actual;if(fstat(fd,&actual)<0)return 1;
  if(!S_ISDIR(actual.st_mode)||actual.st_dev!=d.device||actual.st_ino!=d.inode){errno=ESTALE;return 1;}
  int pin=pin_project(relative,&d,O_PATH,0,0);if(pin<0)return 1;close(pin);return 0;
}
static int acquisition(int listener,const struct seccomp_notif *n) {
  uint64_t address=0,flags=0,mode=0,output=0;int kind=0,dirfd=AT_FDCWD; /* open=0 metadata=1 mkdir=2 readlink=3 statx=4 */
  switch(n->data.nr){
    case SYS_openat:dirfd=(int)n->data.args[0];address=n->data.args[1];flags=n->data.args[2];mode=n->data.args[3];break;
    case SYS_openat2:dirfd=(int)n->data.args[0];address=n->data.args[1];break;
    case SYS_newfstatat:kind=1;dirfd=(int)n->data.args[0];address=n->data.args[1];output=n->data.args[2];flags=n->data.args[3];break;
    case SYS_statx:kind=4;dirfd=(int)n->data.args[0];address=n->data.args[1];flags=n->data.args[2];output=n->data.args[4];break;
    case SYS_mkdirat:kind=2;dirfd=(int)n->data.args[0];address=n->data.args[1];mode=n->data.args[2];break;
    case SYS_readlinkat:kind=3;dirfd=(int)n->data.args[0];address=n->data.args[1];output=n->data.args[2];mode=n->data.args[3];break;
#ifdef SYS_open
    case SYS_open:address=n->data.args[0];flags=n->data.args[1];mode=n->data.args[2];break;
    case SYS_creat:address=n->data.args[0];flags=O_CREAT|O_WRONLY|O_TRUNC;mode=n->data.args[1];break;
    case SYS_stat:kind=1;address=n->data.args[0];output=n->data.args[1];break;
    case SYS_lstat:kind=1;flags=AT_SYMLINK_NOFOLLOW;address=n->data.args[0];output=n->data.args[1];break;
    case SYS_mkdir:kind=2;address=n->data.args[0];mode=n->data.args[1];break;
    case SYS_readlink:kind=3;address=n->data.args[0];output=n->data.args[1];mode=n->data.args[2];break;
#endif
    case SYS_getdents64:{int mem=memory(listener,n);if(mem<0)return directory_setup_error(listener,n,errno);
      int result=directory_read(listener,n,mem);close(mem);return result;}
    default:return reply(listener,n->id,0,ENOSYS);
  }
  int mem=memory(listener,n);if(mem<0)return errno==ESRCH?0:reply(listener,n->id,0,errno);
  char path[MAX_PATH],native[MAX_PATH],relative[MAX_PATH];int result=-1,error=0;
  if(copy_path(mem,address,path)<0){error=errno;goto done;}
  if(kind==1||kind==4){
    uint64_t admitted=AT_EMPTY_PATH|AT_SYMLINK_NOFOLLOW|AT_NO_AUTOMOUNT;
    if(kind==4)admitted|=AT_STATX_SYNC_TYPE;
    if(flags&~admitted){error=EINVAL;goto done;}
  }
  if((kind==1||kind==4)&&dirfd>=0&&!path[0]&&(flags&AT_EMPTY_PATH)){
    int fd=pinned_worker_fd(listener,n,dirfd,0);if(fd<0){error=errno;goto done;}
    if(kind==1){struct stat st;if(fstat(fd,&st)<0)error=errno;
      else if(output>INT64_MAX||pwrite(mem,&st,sizeof(st),(off_t)output)!=sizeof(st))error=EFAULT;else result=0;}
    else{struct statx st;if(syscall(SYS_statx,fd,"",AT_EMPTY_PATH|(flags&AT_STATX_SYNC_TYPE),(unsigned)n->data.args[3],&st)<0)error=errno;
      else if(output>INT64_MAX||pwrite(mem,&st,sizeof(st),(off_t)output)!=sizeof(st))error=EFAULT;else result=0;}
    close(fd);goto done;
  }
  if(dirfd!=AT_FDCWD&&path[0]!='/'){error=EOPNOTSUPP;goto done;}
  if(actual_path(listener,n,path)<0){error=errno;goto done;}
  if(n->data.nr==SYS_openat2){
    struct open_how how;if(n->data.args[3]!=sizeof(how)||pread(mem,&how,sizeof(how),(off_t)n->data.args[2])!=sizeof(how)){error=EINVAL;goto done;}
    if(how.resolve){error=EOPNOTSUPP;goto done;}flags=how.flags;mode=how.mode;
  }
  if(!kind&&!(flags&O_CREAT))mode=0;
  if(!kind){
    uint64_t allowed=O_ACCMODE|O_APPEND|O_CLOEXEC|O_CREAT|O_DIRECTORY|O_EXCL|O_NOCTTY|O_NOFOLLOW|O_NONBLOCK|O_TRUNC|O_LARGEFILE;
    if(flags&~allowed||(flags&O_ACCMODE)==O_ACCMODE||mode&~0777ULL){error=EOPNOTSUPP;goto done;}
  }
  if(kind==3&&!strcmp(path,"/proc/self/exe")){
    if(!mode){error=EINVAL;goto done;}
    char proc[80];snprintf(proc,sizeof(proc),"/proc/%u/exe",n->pid);
    ssize_t length=readlink(proc,native,sizeof(native)-1);
    if(length<0){error=errno;goto done;}native[length]=0;
    if(!valid(listener,n->id)){close(mem);return 0;}
    char checked[MAX_PATH];if(runtime_path(native,checked)!=1){error=EACCES;goto done;}
    size_t bytes=(size_t)length;if(bytes>mode)bytes=(size_t)mode;
    if(output>INT64_MAX||pwrite(mem,native,bytes,(off_t)output)!=(ssize_t)bytes){error=EFAULT;goto done;}
    result=(int)bytes;goto done;
  }
  int nofollow=(kind==1||kind==4)?!!(flags&AT_SYMLINK_NOFOLLOW):kind==3||(!kind&&(flags&O_NOFOLLOW));
  int runtime=runtime_object(path,nofollow,native);
  if(runtime<0){error=errno;goto done;}
  int fd=-1;
  if(runtime){
    if(kind==2||(!kind&&((flags&O_ACCMODE)!=O_RDONLY||(flags&(O_CREAT|O_TRUNC))))){error=EACCES;goto done;}
    fd=open(native,O_PATH|O_CLOEXEC|(nofollow?O_NOFOLLOW:0));if(fd<0){error=errno;goto done;}
  }else{
    struct decision d;int authorized=authorize(n->id,path,kind==2?"mkdir":kind?"metadata":"open",flags,relative,&d);
    if(authorized<0){close(mem);return -1;}if(authorized){error=errno;goto done;}
    if(!valid(listener,n->id)){close(mem);return 0;}
    if(kind==2){result=pin_project(relative,&d,0,(mode_t)mode&0777,1);error=result<0?errno:0;goto done;}
    fd=pin_project(relative,&d,O_PATH,0,0);if(fd<0&&errno!=ENOENT){error=errno;goto done;}
    if(!kind){
      if(fd>=0)close(fd);
      fd=pin_project(relative,&d,(int)flags,(mode_t)mode,0);
    }
  }
  if(fd<0){error=errno;goto done;}
  if(kind==1){struct stat s;if(fstat(fd,&s)<0)error=errno;
    else if(output>INT64_MAX||pwrite(mem,&s,sizeof(s),(off_t)output)!=sizeof(s))error=EFAULT;else result=0;}
  else if(kind==4){struct statx s;if(syscall(SYS_statx,fd,"",AT_EMPTY_PATH|(flags&AT_STATX_SYNC_TYPE),(unsigned)n->data.args[3],&s)<0)error=errno;
    else if(output>INT64_MAX||pwrite(mem,&s,sizeof(s),(off_t)output)!=sizeof(s))error=EFAULT;else result=0;}
  else if(kind==3){
    ssize_t length=readlinkat(fd,"",native,sizeof(native));
    if(length<0)error=errno;
    else if(!mode)error=EINVAL;
    else{size_t size=(size_t)length;if(size>mode)size=(size_t)mode;
      if(output>INT64_MAX||pwrite(mem,native,size,(off_t)output)!=(ssize_t)size)error=EFAULT;else result=(int)size;}
  }
  else{
    if(runtime){
      struct stat pinned;if(fstat(fd,&pinned)<0){error=errno;close(fd);goto done;}
      if(S_ISLNK(pinned.st_mode)){close(fd);error=ELOOP;goto done;}
      char proc[80];snprintf(proc,sizeof(proc),"/proc/self/fd/%d",fd);
      int opened=open(proc,((int)flags&~O_NOFOLLOW)|O_CLOEXEC);int saved=errno;close(fd);fd=opened;
      if(fd<0){error=saved;goto done;}
    }
    struct seccomp_notif_addfd add={.id=n->id,.flags=SECCOMP_ADDFD_FLAG_SEND,.srcfd=(unsigned)fd,
      .newfd_flags=(flags&O_CLOEXEC)?O_CLOEXEC:0};
    int inserted=ioctl(listener,SECCOMP_IOCTL_NOTIF_ADDFD,&add);int saved=errno;close(fd);close(mem);
    if(inserted>=0){grants++;return 0;}if(saved==ENOENT)return 0;return reply(listener,n->id,0,saved);
  }
  close(fd);
done:
  close(mem);if(error)denials++;else grants++;return reply(listener,n->id,result,error);
}
static int no_worker_result(int stage,int error) {
  char message[384];int length=snprintf(message,sizeof(message),
    "{\"type\":\"result\",\"outcome\":\"%s\",\"exitCode\":-1,\"signal\":0,\"cleanupComplete\":true,\"started\":false,\"grants\":0,\"denials\":0,\"stdoutBytes\":0,\"stderrBytes\":0,\"stage\":%d,\"errno\":%d}",
    cancelled?"cancelled":"setup_error",stage,error>0?error:EPROTO);
  (void)packet(message,(size_t)length,1);return 70;
}
static int supervise(void) {
  int out[2],err[2],setup[2],transfer[2];
  if(pipe2(out,O_CLOEXEC)<0||pipe2(err,O_CLOEXEC)<0||pipe2(setup,O_CLOEXEC)<0||
     socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC,0,transfer)<0||prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0)<0)return no_worker_result(20,errno);
  rlim_t tasks;if(uid_tasks(&tasks)<0)return no_worker_result(21,errno);
  pid_t parent=getpid();leader=fork();if(!leader)child(out[1],err[1],setup[1],transfer[1],parent,tasks);
  int fork_error=errno;close(out[1]);close(err[1]);close(setup[1]);close(transfer[1]);if(leader<0)return no_worker_result(22,fork_error);
  nonblock(out[0]);nonblock(err[0]);nonblock(setup[0]);nonblock(transfer[0]);
  int listener=-1,setup_ok=0,setup_eof=0,out_eof=0,err_eof=0,observed=0,empty=0,started=0,status=0;
  int stage=0,saved_error=0,terminating=0,held=0;int64_t cleanup=0;
  const char *outcome="exited";uint64_t bytes[2]={0,0};unsigned char setup_data[16];size_t setup_size=0;
  struct seccomp_notif_sizes sizes={0};if(syscall(SYS_seccomp,SECCOMP_GET_NOTIF_SIZES,0,&sizes)<0){terminating=1;cleanup=milliseconds()+5000;outcome="setup_error";}
  struct seccomp_notif *notification=calloc(1,sizes.seccomp_notif?sizes.seccomp_notif:sizeof(struct seccomp_notif));
  if(!notification){terminating=1;cleanup=milliseconds()+5000;outcome="setup_error";}
  while(!empty||!out_eof||!err_eof||!setup_eof){
    int64_t now=milliseconds();if(commands()<0){cancelled=1;outcome="broker_error";}
    if(!terminating&&(cancelled||now>=deadline)){terminating=1;cleanup=now+5000;if(!strcmp(outcome,"exited"))outcome=cancelled?"cancelled":"timeout";}
    if(terminating&&!reaped){(void)kill(-leader,SIGKILL);(void)kill(leader,SIGKILL);}
    if(terminating&&now>=cleanup&&!held){held=1;outcome="cleanup_error";const char *event="{\"type\":\"ownership-retained\",\"cleanupComplete\":false}";(void)packet(event,strlen(event),1);}
    struct pollfd p[6]={{out_eof?-1:out[0],POLLIN,0},{err_eof?-1:err[0],POLLIN,0},
      {setup_eof?-1:setup[0],POLLIN,0},{listener<0?transfer[0]:-1,POLLIN,0},
      {listener,POLLIN,0},{cfg.command,POLLIN,0}};
    if(poll(p,6,held?1000:20)<0&&errno!=EINTR){cancelled=1;outcome="broker_error";}
    if(listener<0&&(p[3].revents&POLLIN)){listener=receive_fd(transfer[0]);if(listener<0){cancelled=1;outcome="setup_error";}else nonblock(listener);}
    if(listener>=0&&(p[4].revents&POLLIN)&&!terminating){memset(notification,0,sizes.seccomp_notif);
      if(ioctl(listener,SECCOMP_IOCTL_NOTIF_RECV,notification)<0){if(errno!=EINTR&&errno!=ENOENT&&errno!=EAGAIN){cancelled=1;outcome="broker_error";}}
      else if(acquisition(listener,notification)<0){saved_error=errno;cancelled=1;outcome="broker_error";}}
    for(int i=0;i<3;i++)if(p[i].revents&(POLLIN|POLLHUP|POLLERR)){
      char data[4096];ssize_t n=read(p[i].fd,data,sizeof(data));
      if(!n){if(i==0)out_eof=1;else if(i==1)err_eof=1;else setup_eof=1;}
      else if(n>0&&i==2){if(setup_size+(size_t)n>sizeof(setup_data)){cancelled=1;outcome="setup_error";}
        else{memcpy(setup_data+setup_size,data,(size_t)n);setup_size+=(size_t)n;}}
      else if(n>0){size_t amount=(size_t)n;uint64_t total=bytes[0]+bytes[1];
        if(total+amount>cfg.output){amount=(size_t)(cfg.output-total);cancelled=1;outcome="output_limit";}
        size_t sent=0;while(sent<amount&&!held){ssize_t x=write(i+1,data+sent,amount-sent);
          if(x>0){sent+=(size_t)x;continue;}if(x<0&&(errno==EINTR||errno==EAGAIN)){if(commands()<0||cancelled||milliseconds()>=deadline)break;struct pollfd w={i+1,POLLOUT,0};(void)poll(&w,1,20);continue;}break;}
        bytes[i]+=sent;if(sent<amount){cancelled=1;if(!strcmp(outcome,"exited"))outcome="broker_error";}}
      else if(n<0&&errno!=EAGAIN&&errno!=EINTR){cancelled=1;outcome="broker_error";}
    }
    if(setup_eof&&!started&&!terminating){
      if(setup_size==sizeof(int)){memcpy(&stage,setup_data,sizeof(int));setup_ok=stage==0;}
      if(!setup_ok||listener<0){cancelled=1;outcome="setup_error";if(setup_size>=8){memcpy(&stage,setup_data+setup_size-8,4);memcpy(&saved_error,setup_data+setup_size-4,4);}}
      else{const char *event="{\"type\":\"started\",\"profile\":\"bionic-managed-v1\",\"setupCompleted\":true}";
        if(packet(event,strlen(event),0)<0){cancelled=1;outcome="broker_error";}else started=1;}
    }
    if(!observed){siginfo_t info={0};if(waitid(P_PID,(id_t)leader,&info,WEXITED|WNOHANG|WNOWAIT)==0&&info.si_pid==leader){
      observed=1;(void)kill(-leader,SIGKILL);if(!terminating){terminating=1;cleanup=milliseconds()+5000;}}}
    if(observed&&!reaped&&waitpid(leader,&status,WNOHANG)==leader){reaped=1;
      char event[128];int count=snprintf(event,sizeof(event),"{\"type\":\"exited\",\"exitCode\":%d,\"signal\":%d}",WIFEXITED(status)?WEXITSTATUS(status):-1,WIFSIGNALED(status)?WTERMSIG(status):0);(void)packet(event,(size_t)count,1);}
    if(reaped)for(;;){int ignored;pid_t pid=waitpid(-1,&ignored,WNOHANG);if(pid>0)continue;if(pid<0&&errno==ECHILD)empty=1;break;}
  }
  free(notification);if(listener>=0)close(listener);close(transfer[0]);close(out[0]);close(err[0]);close(setup[0]);
  int code=WIFEXITED(status)?WEXITSTATUS(status):-1,sig=WIFSIGNALED(status)?WTERMSIG(status):0;
  char final[768];int length=snprintf(final,sizeof(final),"{\"type\":\"result\",\"outcome\":\"%s\",\"exitCode\":%d,\"signal\":%d,\"cleanupComplete\":%s,\"started\":%s,\"grants\":%llu,\"denials\":%llu,\"stdoutBytes\":%llu,\"stderrBytes\":%llu,\"stage\":%d,\"errno\":%d}",
    outcome,code,sig,reaped&&empty?"true":"false",started?"true":"false",(unsigned long long)grants,(unsigned long long)denials,(unsigned long long)bytes[0],(unsigned long long)bytes[1],stage,saved_error);
  (void)packet(final,(size_t)length,1);return reaped&&empty&&started?0:70;
}
int main(int argc,char **argv) {
  if(argc!=6)return 70;
  int fds[5];
  for(int i=0;i<5;i++){char *end;long value=strtol(argv[i+1],&end,10);if(!*argv[i+1]||*end||value<3||value>INT_MAX)return 70;fds[i]=(int)value;}
  cfg.root=fds[0];cfg.input=fds[1];cfg.control=fds[2];cfg.command=fds[3];
  if(keep(fds,5)<0||identity()<0||configuration(fds[4])<0||setup_paths()<0||
     syscall(SYS_landlock_create_ruleset,NULL,0,1)<6||nonblock(1)<0||nonblock(2)<0)return no_worker_result(10,errno);
  umask(0077);deadline=milliseconds()+(int64_t)cfg.wall;
  struct sigaction cancel={.sa_handler=cancelled_signal};sigemptyset(&cancel.sa_mask);
  if(sigaction(SIGTERM,&cancel,NULL)<0||sigaction(SIGINT,&cancel,NULL)<0)return no_worker_result(11,errno);
  cancel.sa_handler=SIG_IGN;if(sigaction(SIGPIPE,&cancel,NULL)<0)return no_worker_result(12,errno);
  const char *ready="{\"type\":\"ready\",\"profile\":\"bionic-managed-v1\"}";
  if(packet(ready,strlen(ready),0)<0)return no_worker_result(13,errno);
  char ack[2];if(receive(ack,sizeof(ack))!=1||ack[0]!='P')return no_worker_result(14,errno);
  return supervise();
}
