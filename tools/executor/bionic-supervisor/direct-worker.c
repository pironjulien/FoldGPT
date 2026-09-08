/* Real bounded process topologies for direct-runner host qualification. */
#define _GNU_SOURCE
#include <errno.h>
#include <pthread.h>
#include <sched.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static int write_complete(int fd,const void *data,size_t length) {
    const char *cursor=data;
    while(length){
        ssize_t count=write(fd,cursor,length);
        if(count>0){cursor+=(size_t)count;length-=(size_t)count;continue;}
        if(count<0&&errno==EINTR)continue;
        if(!count)errno=EIO;
        return -1;
    }
    return 0;
}
static void report(const char *kind) {
    char text[256];
    int length=snprintf(text,sizeof(text),"{\"worker\":\"%s\",\"pid\":%ld,\"ppid\":%ld,\"sid\":%ld,\"pgrp\":%ld}\n",
        kind,(long)getpid(),(long)getppid(),(long)getsid(0),(long)getpgrp());
    if(length<0||(size_t)length>=sizeof(text)||write_complete(1,text,(size_t)length)<0)_exit(81);
}
static void stay(void) {for(;;)pause();}
static int clone_child(void *data) {report(data);stay();return 0;}
static void *thread_fork(void *unused) {
    (void)unused;
    pid_t child=fork();
    if(child<0)_exit(82);
    if(!child){if(setsid()<0)_exit(83);report("thread-fork-child");stay();}
    return NULL;
}
int main(int argc,char **argv) {
    if(argc!=2)return 80;
    if(!strcmp(argv[1],"tree")){
        if(setsid()<0)return 84;
        report("leader");
        pid_t child=fork();if(child<0)return 85;
        if(!child){
            if(setpgid(0,0)<0)_exit(86);
            report("changed-group");
            pid_t grandchild=fork();if(grandchild<0)_exit(87);
            if(!grandchild){
                if(setsid()<0||prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0)<0)_exit(88);
                report("nested-subreaper");
                pid_t last=fork();if(last<0)_exit(89);
                if(!last){report("fourth-generation");stay();}
            }
            stay();
        }
        stay();
    }
    if(!strcmp(argv[1],"orphan")){
        int ready[2];if(pipe(ready)<0)return 90;
        pid_t child=fork();if(child<0)return 91;
        if(!child){
            close(ready[0]);
            if(setsid()<0)_exit(92);
            pid_t grandchild=fork();if(grandchild<0)_exit(93);
            if(!grandchild){
                report("double-orphan");
                if(write_complete(ready[1],"R",1)<0)_exit(104);
                stay();
            }
            _exit(0);
        }
        close(ready[1]);char byte;
        if(read(ready[0],&byte,1)!=1)return 94;
        report("orphan-leader-exiting");return 23;
    }
    if(!strcmp(argv[1],"clone")){
        void *a=malloc(1024*1024),*b=malloc(1024*1024);if(!a||!b)return 95;
        if(clone(clone_child,(char *)a+1024*1024,CLONE_PARENT|SIGCHLD,"clone-parent")<0)return 96;
        if(clone(clone_child,(char *)b+1024*1024,0,"clone-zero-signal")<0)return 97;
        pthread_t thread;if(pthread_create(&thread,NULL,thread_fork,NULL))return 98;
        if(pthread_join(thread,NULL))return 99;
        report("clone-leader");stay();
    }
    if(!strcmp(argv[1],"churn")){
        report("churn-leader");
        /* Finite stress; this cannot become an unbounded host fork bomb. */
        for(unsigned i=0;i<64;i++){
            pid_t child=fork();if(child<0){if(errno==EAGAIN)continue;return 100;}
            if(!child){
                (void)setsid();
                pid_t grandchild=fork();
                if(!grandchild){report("churn-grandchild");usleep(20000);_exit(0);}
                _exit(0);
            }
            usleep(1000);
        }
        return 0;
    }
    if(!strcmp(argv[1],"owner-loss")){
        pid_t owner=getppid();
        pid_t child=fork();if(child<0)return 101;
        if(!child){report("owner-loss-descendant");stay();}
        report("owner-loss-leader");
        char byte;if(read(0,&byte,1)!=1||byte!='K')return 102;
        if(kill(owner,SIGKILL)<0)return 103;
        stay();
    }
    return 80;
}
