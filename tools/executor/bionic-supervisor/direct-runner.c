/* SPDX-License-Identifier: GPL-3.0-only
 * Ordinary-UID process owner. No added filesystem, syscall or network sandbox.
 * See direct-design.md: discovery never establishes cleanup; ECHILD does.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/capability.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "This private envelope is little endian"
#endif
#ifndef __WALL
#define __WALL 0x40000000
#endif

#define MAX_FRAME 196608
#define PROFILE "bionic-direct-v1"
struct configuration {
    uint64_t wall,data,file,output,tasks,cpu,descriptors,grace;
    uint32_t argc,envc;
    char *cwd,*executable,*argv[257],*env[129];
    int input,control,command,cwd_fd;
};
struct output_stream {
    int fd,destination,eof,broken;
    unsigned char data[65536];
    size_t begin,end;
    uint64_t read_bytes,sent_bytes;
};
static struct configuration cfg;
static volatile sig_atomic_t cancellation;
static int control_broken,leader=-1,leader_pidfd=-1,leader_reaped;
static int exit_code=-1,exit_signal,setup_error,setup_stage;
static int64_t deadline;
static uint64_t reaped_count,signal_count,forwarded_total;

static int64_t now_ms(void) {
    struct timespec time;
    if(clock_gettime(CLOCK_MONOTONIC,&time)<0)return -1;
    return (int64_t)time.tv_sec*1000+time.tv_nsec/1000000;
}
static int nonblock(int fd) {
    int flags=fcntl(fd,F_GETFL);
    return flags<0?-1:fcntl(fd,F_SETFL,flags|O_NONBLOCK);
}
static int write_complete(int fd,const void *data,size_t length) {
    const unsigned char *cursor=data;
    while(length){
        ssize_t count=write(fd,cursor,length);
        if(count>0){cursor+=(size_t)count;length-=(size_t)count;continue;}
        if(count<0&&errno==EINTR)continue;
        if(!count)errno=EIO;
        return -1;
    }
    return 0;
}
static int identity(void) {
    uid_t a,b,c;gid_t d,e,f;
    struct __user_cap_header_struct header={.version=_LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct caps[2]={{0},{0}};
    if(getresuid(&a,&b,&c)<0||getresgid(&d,&e,&f)<0||!a||a!=b||a!=c||d!=e||d!=f||
       syscall(SYS_capget,&header,caps)<0||caps[0].effective||caps[1].effective||
       caps[0].permitted||caps[1].permitted||caps[0].inheritable||caps[1].inheritable){errno=EPERM;return -1;}
    for(unsigned bit=0;bit<64;bit++){
        int value=prctl(PR_CAP_AMBIENT,PR_CAP_AMBIENT_IS_SET,bit,0,0);
        if(value==0)continue;
        if(value<0&&errno==EINVAL)break;
        errno=EPERM;return -1;
    }
    return 0;
}
static int keep(const int *fds,size_t count) {
    int ordered[8];
    if(count>8){errno=EINVAL;return -1;}
    memcpy(ordered,fds,count*sizeof(int));
    for(size_t i=0;i<count;i++)for(size_t j=i+1;j<count;j++)if(ordered[j]<ordered[i]){
        int t=ordered[i];ordered[i]=ordered[j];ordered[j]=t;
    }
    unsigned first=3;
    for(size_t i=0;i<count;i++){
        if(ordered[i]<3||(i&&ordered[i]==ordered[i-1])){errno=EINVAL;return -1;}
        if(first<(unsigned)ordered[i]&&syscall(SYS_close_range,first,(unsigned)ordered[i]-1,0)<0)return -1;
        first=(unsigned)ordered[i]+1;
    }
    return (int)syscall(SYS_close_range,first,UINT_MAX,0);
}
static char *string(unsigned char **cursor,const unsigned char *end) {
    if(end-*cursor<4){errno=EPROTO;return NULL;}
    uint32_t length;memcpy(&length,*cursor,4);*cursor+=4;
    if(length>65536||end-*cursor<(ptrdiff_t)length||memchr(*cursor,0,length)){errno=EPROTO;return NULL;}
    char *value=malloc((size_t)length+1);if(!value)return NULL;
    memcpy(value,*cursor,length);value[length]=0;*cursor+=length;return value;
}
static int configuration(int fd) {
    struct stat st;
    int required=F_SEAL_SEAL|F_SEAL_GROW|F_SEAL_SHRINK|F_SEAL_WRITE;
    int seals=fcntl(fd,F_GET_SEALS);
    if(fstat(fd,&st)<0||st.st_size<80||st.st_size>MAX_FRAME||seals<0||(seals&required)!=required){errno=EPROTO;return -1;}
    unsigned char *data=malloc((size_t)st.st_size);if(!data)return -1;
    if(pread(fd,data,(size_t)st.st_size,0)!=st.st_size){free(data);errno=EPROTO;return -1;}
    unsigned char *cursor=data;const unsigned char *end=data+st.st_size;
    if(memcmp(cursor,"FGBD0001",8)){free(data);errno=EPROTO;return -1;}cursor+=8;
    uint64_t limits[8];memcpy(limits,cursor,sizeof(limits));cursor+=sizeof(limits);
    for(unsigned i=0;i<8;i++)if(limits[i]>9007199254740991ULL){free(data);errno=EINVAL;return -1;}
    cfg.wall=limits[0];cfg.data=limits[1];cfg.file=limits[2];cfg.output=limits[3];
    cfg.tasks=limits[4];cfg.cpu=limits[5];cfg.descriptors=limits[6];cfg.grace=limits[7];
    uint32_t counts[2];memcpy(counts,cursor,sizeof(counts));cursor+=sizeof(counts);
    cfg.argc=counts[0];cfg.envc=counts[1];
    if(!cfg.grace||!cfg.argc||cfg.argc>256||cfg.envc>128||(cfg.descriptors&&cfg.descriptors<8)){free(data);errno=EINVAL;return -1;}
    cfg.cwd=string(&cursor,end);cfg.executable=string(&cursor,end);
    if(!cfg.cwd||!cfg.executable||cfg.cwd[0]!='/'||cfg.executable[0]!='/'){free(data);errno=EINVAL;return -1;}
    for(unsigned i=0;i<cfg.argc;i++)if(!(cfg.argv[i]=string(&cursor,end))){free(data);return -1;}
    for(unsigned i=0;i<cfg.envc;i++){
        cfg.env[i]=string(&cursor,end);
        char *equals=cfg.env[i]?strchr(cfg.env[i],'='):NULL;
        if(!equals||equals==cfg.env[i]){free(data);errno=EINVAL;return -1;}
        size_t length=(size_t)(equals-cfg.env[i])+1;
        for(unsigned j=0;j<i;j++)if(!strncmp(cfg.env[j],cfg.env[i],length)){free(data);errno=EINVAL;return -1;}
    }
    int exact=cursor==end;free(data);
    if(!exact){errno=EPROTO;return -1;}
    cfg.cwd_fd=open(cfg.cwd,O_PATH|O_DIRECTORY|O_CLOEXEC);
    return cfg.cwd_fd<0?-1:0;
}
static void cancelled_signal(int sig) {(void)sig;cancellation=1;}
static int signal_pidfd(int fd,int sig) {
    if(syscall(SYS_pidfd_send_signal,fd,sig,NULL,0)==0){signal_count++;return 0;}
    return errno==ESRCH?0:-1;
}
static int commands(void) {
    for(unsigned i=0;i<32;i++){
        char data[2];ssize_t size=recv(cfg.command,data,sizeof(data),MSG_DONTWAIT);
        if(size==0){cancellation=1;return 0;}
        if(size<0){if(errno==EINTR)continue;if(errno==EAGAIN||errno==EWOULDBLOCK)return 0;return -1;}
        if(size!=1||(data[0]!='T'&&data[0]!='I')){errno=EPROTO;return -1;}
        if(data[0]=='T')cancellation=1;
        else if(leader_pidfd>=0&&!leader_reaped&&signal_pidfd(leader_pidfd,SIGINT)<0)return -1;
    }
    return 0;
}
static int packet(const char *data,int cleanup) {
    if(control_broken){errno=EPIPE;return -1;}
    int64_t until=cleanup?now_ms()+500:deadline;
    size_t length=strlen(data);
    for(;;){
        if(commands()<0)return -1;
        if((!cleanup&&cancellation)||now_ms()>=until){errno=ECANCELED;return -1;}
        ssize_t size=send(cfg.control,data,length,MSG_NOSIGNAL|MSG_DONTWAIT);
        if(size==(ssize_t)length)return 0;
        if(size>=0){errno=EIO;return -1;}
        if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK){control_broken=1;return -1;}
        struct pollfd wait={cfg.control,POLLOUT,0};(void)poll(&wait,1,20);
    }
}
static int acknowledgement(void) {
    for(;;){
        if(commands()<0)return -1;
        if(cancellation||now_ms()>=deadline){errno=ECANCELED;return -1;}
        char data[2];ssize_t size=recv(cfg.control,data,sizeof(data),MSG_DONTWAIT);
        if(size>0){if(size!=1||data[0]!='P'){errno=EPROTO;return -1;}return 0;}
        if(!size){errno=EPIPE;return -1;}
        if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK)return -1;
        struct pollfd wait[2]={{cfg.control,POLLIN,0},{cfg.command,POLLIN,0}};(void)poll(wait,2,20);
    }
}
static int limit(int resource,uint64_t value) {
    if(!value)return 0;
    struct rlimit old;
    if(getrlimit(resource,&old)<0)return -1;
    rlim_t actual=(rlim_t)value;
    if(actual!=value){errno=EOVERFLOW;return -1;}
    if(actual>old.rlim_cur)actual=old.rlim_cur;
    if(actual>old.rlim_max)actual=old.rlim_max;
    struct rlimit bounds={actual,actual};return setrlimit(resource,&bounds);
}
static int uid_task_ceiling(uint64_t *ceiling) {
    *ceiling=0;if(!cfg.tasks)return 0;
    DIR *directory=opendir("/proc");if(!directory)return -1;
    uint64_t total=0;int failed=0;struct dirent *entry;
    while((entry=readdir(directory))){
        char *end;long pid=strtol(entry->d_name,&end,10);
        if(!*entry->d_name||*end||pid<=0||pid>INT_MAX)continue;
        char path[80];struct stat st;snprintf(path,sizeof(path),"/proc/%ld",pid);
        if(stat(path,&st)<0||st.st_uid!=getuid())continue;
        snprintf(path,sizeof(path),"/proc/%ld/status",pid);FILE *stream=fopen(path,"re");
        if(!stream){if(errno!=ENOENT&&errno!=ESRCH)failed=1;continue;}
        unsigned long count=0;char line[512];
        while(fgets(line,sizeof(line),stream))if(sscanf(line,"Threads: %lu",&count)==1)break;
        fclose(stream);
        if(!count||UINT64_MAX-total<count){failed=1;break;}total+=count;
    }
    closedir(directory);
    if(failed||!total||UINT64_MAX-total<cfg.tasks){errno=EACCES;return -1;}
    *ceiling=total+cfg.tasks;return 0;
}
static void child(int output,int error,int setup,int gate,pid_t parent,uint64_t tasks) {
    int stage=1;
    if(prctl(PR_SET_PDEATHSIG,SIGKILL,0,0,0)<0||getppid()!=parent||identity()<0||
       dup2(cfg.input,0)<0||dup2(output,1)<0||dup2(error,2)<0)goto failed;
    stage=2;
    if(fchdir(cfg.cwd_fd)<0||limit(RLIMIT_DATA,cfg.data)<0||limit(RLIMIT_FSIZE,cfg.file)<0||
       limit(RLIMIT_NOFILE,cfg.descriptors)<0||limit(RLIMIT_CPU,cfg.cpu)<0||limit(RLIMIT_NPROC,tasks)<0)goto failed;
    struct sigaction normal={.sa_handler=SIG_DFL};sigemptyset(&normal.sa_mask);
    if(sigaction(SIGCHLD,&normal,NULL)<0||sigaction(SIGINT,&normal,NULL)<0||
       sigaction(SIGTERM,&normal,NULL)<0||sigaction(SIGPIPE,&normal,NULL)<0)goto failed;
    sigset_t empty;sigemptyset(&empty);
    if(sigprocmask(SIG_SETMASK,&empty,NULL)<0)goto failed;
    stage=3;
    {int fds[]={setup,gate};if(keep(fds,2)<0)goto failed;}
    /* The owner gets a pidfd and verifies child ownership before allowing exec. */
    char permission;ssize_t got;
    do {got=read(gate,&permission,1);} while(got<0&&errno==EINTR);
    if(got!=1||permission!='X'){errno=ECANCELED;goto failed;}close(gate);
    stage=4;
    if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)<0)goto failed;
    execve(cfg.executable,cfg.argv,cfg.env);
    stage=5;
failed:;
    int report[2]={stage,errno};
    if(write_complete(setup,report,sizeof(report))<0)_exit(71);
    _exit(70);
}
static int reap(void) {
    for(;;){
        siginfo_t info={0};
        if(waitid(P_ALL,0,&info,WEXITED|WNOHANG|__WALL)<0){
            if(errno==EINTR)continue;
            return errno==ECHILD?1:-1;
        }
        if(!info.si_pid)return 0;
        reaped_count++;
        if(info.si_pid==leader){
            leader_reaped=1;
            exit_code=info.si_code==CLD_EXITED?info.si_status:-1;
            exit_signal=info.si_code==CLD_EXITED?0:info.si_status;
        }
    }
}
static int maybe_direct_child(pid_t pid) {
    char path[80];snprintf(path,sizeof(path),"/proc/%d/stat",pid);
    int fd=open(path,O_RDONLY|O_CLOEXEC);if(fd<0)return 0;
    char data[4096];ssize_t count=read(fd,data,sizeof(data)-1);close(fd);
    if(count<=0)return 0;
    data[count]=0;
    char *end=strrchr(data,')');if(!end)return 0;
    char state;long parent;
    return sscanf(end+1," %c %ld",&state,&parent)==2&&parent==getpid();
}
static int terminate_children(void) {
    /* /proc is only candidate discovery. A kernel wait on the stable pidfd
     * authorizes a signal, and a separate ECHILD is the completion witness. */
    DIR *directory=opendir("/proc");if(!directory)return -1;
    int failed=0;struct dirent *entry;
    while((entry=readdir(directory))){
        char *end;long number=strtol(entry->d_name,&end,10);
        if(!*entry->d_name||*end||number<=0||number>INT_MAX||!maybe_direct_child((pid_t)number))continue;
        int fd=(int)syscall(SYS_pidfd_open,(pid_t)number,0);
        if(fd<0){if(errno!=ESRCH&&errno!=ENOENT)failed=errno;continue;}
        siginfo_t info={0};
        int result=waitid(P_PIDFD,(id_t)fd,&info,WEXITED|WNOHANG|WNOWAIT|__WALL);
        if(result==0){
            if(!info.si_pid&&signal_pidfd(fd,SIGKILL)<0)failed=errno;
        }else if(errno!=ECHILD&&errno!=ESRCH)failed=errno;
        close(fd);
    }
    closedir(directory);
    if(failed){errno=failed;return -1;}return 0;
}
static int pump(struct output_stream *stream,int cancelling) {
    if(stream->begin<stream->end&&!stream->broken){
        size_t amount=stream->end-stream->begin;
        if(cfg.output&&amount>cfg.output-forwarded_total)amount=(size_t)(cfg.output-forwarded_total);
        ssize_t count=amount?write(stream->destination,stream->data+stream->begin,amount):0;
        if(count>0){stream->begin+=(size_t)count;stream->sent_bytes+=(uint64_t)count;forwarded_total+=(uint64_t)count;}
        else if(count<0&&errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK){stream->broken=1;return -1;}
    }
    /* On cancellation do not retain children behind an unconsumed output pipe.
     * Count both actual reads and actual forwarded bytes. No truncation is hidden. */
    if(cancelling&&stream->begin<stream->end)stream->begin=stream->end;
    if(stream->begin==stream->end)stream->begin=stream->end=0;
    if(!stream->eof&&stream->end<sizeof(stream->data)){
        ssize_t count=read(stream->fd,stream->data+stream->end,sizeof(stream->data)-stream->end);
        if(count>0){stream->end+=(size_t)count;stream->read_bytes+=(uint64_t)count;}
        else if(!count)stream->eof=1;
        else if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK)return -1;
    }
    return 0;
}
static int no_worker_result(int stage,int error) {
    char result[512];
    const char *outcome=cancellation?"cancelled":now_ms()>=deadline?"timeout":"setup_error";
    snprintf(result,sizeof(result),"{\"type\":\"result\",\"profile\":\"" PROFILE "\",\"outcome\":\"%s\","
        "\"started\":false,\"cleanupComplete\":true,\"exitCode\":-1,\"signal\":0,"
        "\"reaped\":0,\"signalsSent\":0,\"stdoutReadBytes\":0,\"stderrReadBytes\":0,"
        "\"stdoutBytes\":0,\"stderrBytes\":0,\"stage\":%d,\"errno\":%d}",
        outcome,stage,error>0?error:EPROTO);
    (void)packet(result,1);return 70;
}
static int supervise(void) {
    int out[2],err[2],setup[2],gate[2];uint64_t tasks;
    if(pipe2(out,O_CLOEXEC)<0||pipe2(err,O_CLOEXEC)<0||pipe2(setup,O_CLOEXEC)<0||
       pipe2(gate,O_CLOEXEC)<0||uid_task_ceiling(&tasks)<0)return no_worker_result(10,errno);
    pid_t parent=getpid();leader=fork();
    if(!leader)child(out[1],err[1],setup[1],gate[0],parent,tasks);
    int fork_error=errno;
    close(out[1]);close(err[1]);close(setup[1]);close(gate[0]);
    if(leader<0){close(gate[1]);return no_worker_result(11,fork_error);}
    leader_pidfd=(int)syscall(SYS_pidfd_open,leader,0);
    int launch_error=leader_pidfd<0?errno:0;
    if(!launch_error){
        siginfo_t info={0};
        if(waitid(P_PIDFD,(id_t)leader_pidfd,&info,WEXITED|WNOHANG|WNOWAIT|__WALL)<0)launch_error=errno;
    }
    if(!launch_error&&!cancellation&&write_complete(gate[1],"X",1)<0)launch_error=errno;
    close(gate[1]);
    struct output_stream streams[2]={{.fd=out[0],.destination=1},{.fd=err[0],.destination=2}};
    if(nonblock(out[0])<0||nonblock(err[0])<0||nonblock(setup[0])<0){if(!launch_error)launch_error=errno;}
    int started=0,setup_eof=0,empty=0,terminating=launch_error!=0,retained=0,exit_reported=0;
    int64_t cleanup_start=terminating?now_ms():0;
    const char *outcome=launch_error?"setup_error":"exited";
    if(launch_error){setup_stage=12;setup_error=launch_error;}
    int setup_report[2];size_t setup_bytes=0;
    for(;;){
        int64_t time=now_ms();
        if(commands()<0){cancellation=1;if(!terminating)outcome="broker_error";}
        char unexpected;ssize_t incoming=recv(cfg.control,&unexpected,1,MSG_DONTWAIT|MSG_PEEK);
        if(incoming==0||(incoming<0&&errno!=EAGAIN&&errno!=EWOULDBLOCK&&errno!=EINTR)){
            control_broken=1;cancellation=1;if(!terminating)outcome="broker_error";
        }else if(incoming>0){cancellation=1;if(!terminating)outcome="broker_error";}
        if(!terminating&&(cancellation||time>=deadline)){
            terminating=1;cleanup_start=time;
            if(!strcmp(outcome,"exited"))outcome=cancellation?"cancelled":"timeout";
        }
        if(terminating&&!strcmp(outcome,"exited")&&(cancellation||time>=deadline))
            outcome=cancellation?"cancelled":"timeout";
        if(terminating&&!empty){
            if(leader_pidfd>=0&&!leader_reaped&&signal_pidfd(leader_pidfd,SIGKILL)<0)setup_error=errno;
            if(terminate_children()<0)setup_error=errno;
        }
        int previous_leader=leader_reaped;
        int observed=reap();
        if(observed<0){if(!terminating){outcome="cleanup_error";cleanup_start=time;}terminating=1;setup_error=errno;}
        else empty=observed;
        if(!previous_leader&&leader_reaped&&!terminating){terminating=1;cleanup_start=time;}
        if(!setup_eof){
            unsigned char buffer[32];ssize_t count=read(setup[0],buffer,sizeof(buffer));
            if(count>0){
                if(setup_bytes+(size_t)count>sizeof(setup_report)){
                    setup_stage=13;setup_error=EPROTO;outcome="setup_error";cancellation=1;
                }else{memcpy((unsigned char *)setup_report+setup_bytes,buffer,(size_t)count);setup_bytes+=(size_t)count;}
            }else if(!count){
                setup_eof=1;
                if(setup_bytes){
                    setup_stage=setup_bytes==sizeof(setup_report)?setup_report[0]:13;
                    setup_error=setup_bytes==sizeof(setup_report)?setup_report[1]:EPROTO;
                    outcome="setup_error";cancellation=1;
                }else if(!launch_error&&!cancellation&&!(leader_reaped&&exit_signal)){
                    /* CLOEXEC EOF after the launch gate is the actual exec acknowledgement. */
                    started=1;
                    (void)packet("{\"type\":\"started\",\"profile\":\"" PROFILE "\",\"setupCompleted\":true,\"sandboxType\":\"none\"}",1);
                }
            }else if(errno!=EINTR&&errno!=EAGAIN&&errno!=EWOULDBLOCK){
                setup_error=errno;outcome="setup_error";cancellation=1;
            }
        }
        if(leader_reaped&&setup_eof&&!exit_reported){
            char event[160];snprintf(event,sizeof(event),"{\"type\":\"exited\",\"exitCode\":%d,\"signal\":%d}",exit_code,exit_signal);
            (void)packet(event,1);exit_reported=1;
        }
        /* A successful initial exit still forwards every byte. Other outcomes
         * drain after cancellation and disclose exactly what was not forwarded. */
        int discard=terminating&&strcmp(outcome,"exited")!=0;
        for(unsigned i=0;i<2;i++)if(pump(&streams[i],discard)<0){
            if(!terminating||!strcmp(outcome,"exited"))outcome="output_error";
            cancellation=1;
        }
        if(cfg.output&&streams[0].read_bytes+streams[1].read_bytes>cfg.output){outcome="output_limit";cancellation=1;}
        if(terminating&&!retained&&time-cleanup_start>=(int64_t)cfg.grace){
            retained=1;
            (void)packet("{\"type\":\"ownership-retained\",\"cleanupComplete\":false}",1);
        }
        if(empty&&setup_eof&&streams[0].eof&&streams[1].eof&&
           streams[0].begin==streams[0].end&&streams[1].begin==streams[1].end)break;
        struct pollfd wait[6]={{!streams[0].eof&&streams[0].end<sizeof(streams[0].data)?streams[0].fd:-1,POLLIN,0},
            {!streams[1].eof&&streams[1].end<sizeof(streams[1].data)?streams[1].fd:-1,POLLIN,0},
            {setup_eof?-1:setup[0],POLLIN,0},{cfg.command,POLLIN,0},
            {streams[0].begin<streams[0].end?1:-1,POLLOUT,0},
            {streams[1].begin<streams[1].end?2:-1,POLLOUT,0}};
        (void)poll(wait,6,20);
    }
    /* No cleanupComplete is inferred from discovery, a timer or a leader exit. */
    char result[768];
    snprintf(result,sizeof(result),"{\"type\":\"result\",\"profile\":\"" PROFILE "\",\"outcome\":\"%s\","
        "\"started\":%s,\"cleanupComplete\":true,\"exitCode\":%d,\"signal\":%d,"
        "\"reaped\":%llu,\"signalsSent\":%llu,\"stdoutReadBytes\":%llu,\"stderrReadBytes\":%llu,"
        "\"stdoutBytes\":%llu,\"stderrBytes\":%llu,\"stage\":%d,\"errno\":%d}",
        outcome,started?"true":"false",exit_code,exit_signal,(unsigned long long)reaped_count,
        (unsigned long long)signal_count,(unsigned long long)streams[0].read_bytes,
        (unsigned long long)streams[1].read_bytes,(unsigned long long)streams[0].sent_bytes,
        (unsigned long long)streams[1].sent_bytes,setup_stage,setup_error);
    /* No further inbound record is useful. Avoid unread-data reset at close. */
    (void)shutdown(cfg.control,SHUT_RD);
    (void)packet(result,1);
    close(out[0]);close(err[0]);close(setup[0]);
    if(leader_pidfd>=0)close(leader_pidfd);
    return started?0:70;
}
int main(int argc,char **argv) {
    if(argc!=5)return 70;
    int fds[4];
    for(unsigned i=0;i<4;i++){
        char *end;long value=strtol(argv[i+1],&end,10);
        if(!*argv[i+1]||*end||value<3||value>INT_MAX)return 70;
        fds[i]=(int)value;
    }
    cfg.input=fds[1];cfg.control=fds[2];cfg.command=fds[3];
    if(keep(fds,4)<0||identity()<0)return 70;
    struct sigaction normal={.sa_handler=SIG_DFL};sigemptyset(&normal.sa_mask);
    if(sigaction(SIGCHLD,&normal,NULL)<0||prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0)<0||
       prctl(PR_SET_DUMPABLE,0,0,0,0)<0)return 70;
    struct sigaction stop={.sa_handler=cancelled_signal};sigemptyset(&stop.sa_mask);
    if(sigaction(SIGINT,&stop,NULL)<0||sigaction(SIGTERM,&stop,NULL)<0)return 70;
    stop.sa_handler=SIG_IGN;if(sigaction(SIGPIPE,&stop,NULL)<0)return 70;
    sigset_t empty;sigemptyset(&empty);if(sigprocmask(SIG_SETMASK,&empty,NULL)<0)return 70;
    deadline=INT64_MAX;
    if(configuration(fds[0])<0)return no_worker_result(1,errno);
    close(fds[0]);
    if(nonblock(1)<0||nonblock(2)<0)return no_worker_result(2,errno);
    if(cfg.wall)deadline=now_ms()+(int64_t)cfg.wall;
    if(packet("{\"type\":\"ready\",\"profile\":\"" PROFILE "\"}",0)<0)return no_worker_result(3,errno);
    if(acknowledgement()<0)return no_worker_result(4,errno);
    return supervise();
}
