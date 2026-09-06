/* Actual native guest tree: background descendants also leave the session.
 * This is a test fixture only, never included in the Android runtime. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#include <time.h>
#include <unistd.h>

static void require(int ok) { if (!ok) { perror("guest fixture"); _exit(90); } }
static void report(const char *role) {
    char name[64];
    snprintf(name,sizeof(name),"pid-%ld",(long)getpid());
    int fd=open(name,O_WRONLY|O_CREAT|O_EXCL,0600); require(fd>=0);
    sigset_t mask; require(sigprocmask(SIG_SETMASK,NULL,&mask)==0);
    require(dprintf(fd,"%s %ld %ld %ld %d\n",role,(long)getpid(),(long)getppid(),
        (long)getsid(0),sigismember(&mask,SIGTERM))>0);
    require(close(fd)==0);
}
static void run(const char *role,int ready) {
    report(role);
    if (ready>=0) { require(write(ready,"r",1)==1); close(ready); }
    char name[64]; snprintf(name,sizeof(name),"beat-%ld",(long)getpid());
    int fd=open(name,O_WRONLY|O_CREAT|O_APPEND,0600); require(fd>=0);
    struct timespec delay={.tv_sec=0,.tv_nsec=10000000};
    for (;;) { require(write(fd,"x",1)==1); nanosleep(&delay,NULL); }
}
int main(int argc,char **argv) {
    require(argc==3 && chdir(argv[2])==0);
    signal(SIGTERM,SIG_IGN);
    report("main");
    int ready[2]; require(pipe(ready)==0);
    pid_t child=fork(); require(child>=0);
    if (!child) {
        close(ready[0]);
        pid_t grandchild=fork(); require(grandchild>=0);
        if (!grandchild) {
            require(setsid()>0);
            pid_t greatgrandchild=fork(); require(greatgrandchild>=0);
            if (!greatgrandchild) run("greatgrandchild",ready[1]);
            run("detached-grandchild",ready[1]);
        }
        run("child",ready[1]);
    }
    close(ready[1]);
    for(int i=0;i<3;i++) { char value; require(read(ready[0],&value,1)==1); }
    close(ready[0]);
    int fd=open("ready",O_WRONLY|O_CREAT|O_EXCL,0600); require(fd>=0); close(fd);
    if (!strcmp(argv[1],"exit")) _exit(23);
    if (!strcmp(argv[1],"storm")) {
        struct timespec delay={.tv_sec=0,.tv_nsec=2000000};
        for(int i=0;i<32;i++) {
            pid_t extra=fork(); require(extra>=0);
            if (!extra) run("racing-child",-1);
            nanosleep(&delay,NULL);
        }
    }
    for (;;) pause();
}
