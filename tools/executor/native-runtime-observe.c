/* SPDX-License-Identifier: GPL-3.0-only
 * Debug-only signal observer. Executes a supervisor-owned argv, reports SIGSYS
 * siginfo, and forwards the original signal without emulation or suppression.
 * Never install this tracer in a production executor or count it as untraced
 * native-runtime proof. The observed program retains its inherited seccomp.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define CHILD_LIMIT 256
#define EVENT_LIMIT 256
static pid_t children[CHILD_LIMIT];
static size_t count;
static volatile sig_atomic_t cancelled;
static unsigned events;
static int diagnostic_fd=-1,diagnostic_lost;

static void record(const char *format,...) {
    char buffer[512];va_list args;va_start(args,format);
    int length=vsnprintf(buffer,sizeof(buffer),format,args);va_end(args);
    if(length<0 || (size_t)length>=sizeof(buffer)) {diagnostic_lost=1;return;}
    ssize_t written;
    do {written=write(diagnostic_fd,buffer,(size_t)length);} while(written<0 && errno==EINTR);
    if(written!=length) diagnostic_lost=1;
}

static void on_signal(int number) { cancelled = number; }
static int64_t millis(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now)) return -1;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
static void diagnostic(const char *stage, int error) {
    if (events++ < EVENT_LIMIT)
        record("{\"observer\":\"error\",\"stage\":\"%s\",\"errno\":%d}\n",stage,error);
}
static int add(pid_t child) {
    for (size_t i=0;i<count;i++) if(children[i]==child) return 0;
    if(count==CHILD_LIMIT) return -1;
    children[count++]=child; return 0;
}
static void drop(pid_t child) {
    for(size_t i=0;i<count;i++) if(children[i]==child) {children[i]=children[--count];return;}
}
static void terminate_owned(void) {
    /* PIDs remain ours until reaped; only this single-threaded supervisor waits.
     * No mutable /proc PPid search or unrelated process-group signaling. */
    for(size_t i=0;i<count;i++) if(kill(children[i],SIGKILL) && errno!=ESRCH) diagnostic("kill",errno);
}
static int close_extra_fds(void) {
    DIR *dir=opendir("/proc/self/fd");
    if(!dir) return -1;
    int own=dirfd(dir),result=0; struct dirent *entry;
    while((entry=readdir(dir))) {
        char *end; long fd=strtol(entry->d_name,&end,10);
        if(*end || fd<3 || fd>INT_MAX || fd==own || fd==diagnostic_fd) continue;
        if(close((int)fd) && errno!=EBADF) result=-1;
    }
    if(closedir(dir)) result=-1;
    return result;
}
static long options(void) {
    return PTRACE_O_EXITKILL|PTRACE_O_TRACEEXEC|PTRACE_O_TRACEFORK|PTRACE_O_TRACEVFORK|PTRACE_O_TRACECLONE;
}
int main(int argc,char **argv) {
    /* A fresh file description keeps observer diagnostics nonblocking without
     * changing flags on the tracee's inherited stderr. CLOEXEC removes it from
     * the actual supplied program. Lost evidence makes observation fail. */
    diagnostic_fd=open("/proc/self/fd/2",O_WRONLY|O_CLOEXEC|O_NONBLOCK);
    if(diagnostic_fd<0) return 125;
    if(argc<5 || strcmp(argv[1],"--timeout-ms") || strcmp(argv[3],"--") || argv[4][0]!='/') {
        diagnostic("usage-timeout-ms-then-absolute-command",EINVAL); return 125;
    }
    char *end; errno=0; long timeout=strtol(argv[2],&end,10);
    if(errno || *end || timeout<1 || timeout>120000 || argc>260) {diagnostic("bounds",EINVAL);return 125;}
    size_t bytes=0;
    for(int i=4;i<argc;i++) {bytes+=strlen(argv[i])+1;if(bytes>131072){diagnostic("argv-bound",E2BIG);return 125;}}
    if(geteuid()==0) {diagnostic("root-refused",EPERM);return 125;}
    if(close_extra_fds()) {diagnostic("close-fds",errno);return 125;}
    if(prctl(PR_SET_CHILD_SUBREAPER,1,0,0,0)) {diagnostic("subreaper",errno);return 125;}
    struct sigaction action={0}; action.sa_handler=on_signal; sigemptyset(&action.sa_mask);
    if(sigaction(SIGTERM,&action,NULL)||sigaction(SIGINT,&action,NULL)||sigaction(SIGHUP,&action,NULL)) {
        diagnostic("signal-handler",errno);return 125;
    }
    int64_t now=millis(); if(now<0){diagnostic("clock",errno);return 125;}
    int64_t deadline=now+timeout,cleanup_deadline=0;
    pid_t root=fork();
    if(root<0){diagnostic("fork",errno);return 125;}
    if(!root) {
        /* Keep inherited environment and seccomp; only observer signal handlers
         * and inherited nonstandard descriptors are removed before exec. */
        struct sigaction normal={0};normal.sa_handler=SIG_DFL;sigemptyset(&normal.sa_mask);
        sigaction(SIGTERM,&normal,NULL);sigaction(SIGINT,&normal,NULL);sigaction(SIGHUP,&normal,NULL);
        if(setpgid(0,0)) {_exit(125);}
        if(ptrace(PTRACE_TRACEME,0,NULL,NULL)) {diagnostic("traceme",errno);_exit(125);}
        if(raise(SIGSTOP)) {_exit(125);}
        execv(argv[4],&argv[4]); diagnostic("exec",errno);_exit(125);
    }
    add(root);
    int root_status=125,root_done=0,failed=0,stopping=0,initial=1;
    /* Child does the authoritative setpgid before its first stop. */
    if(setpgid(root,root) && errno!=EACCES && errno!=ESRCH) {diagnostic("parent-setpgid",errno);failed=1;}
    for(;;) {
        now=millis();
        if(!stopping && (failed || cancelled || now<0 || now>=deadline || root_done)) {
            stopping=1;cleanup_deadline=(now<0?deadline:now)+5000;
            if(!root_done) root_status=cancelled?128+cancelled:failed?125:124;
            terminate_owned();
        }
        int status;pid_t child=waitpid(-1,&status,__WALL|WNOHANG);
        if(child<0 && errno==EINTR) continue;
        if(child<0 && errno==ECHILD) break;
        if(child<0) {diagnostic("waitpid",errno);terminate_owned();return 125;}
        if(!child) {
            if(stopping && (now<0 || now>=cleanup_deadline)) {
                diagnostic("bounded-cleanup-incomplete",ETIMEDOUT);
                /* EXITKILL remains set for every traced descendant; exiting
                 * never detaches a surviving task back into ordinary execution. */
                return 125;
            }
            struct timespec delay={.tv_nsec=1000000};nanosleep(&delay,NULL);continue;
        }
        if(WIFEXITED(status)||WIFSIGNALED(status)) {
            if(child==root && !root_done) {
                if(!stopping) root_status=WIFEXITED(status)?WEXITSTATUS(status):128+WTERMSIG(status);
                root_done=1;
                record("{\"observer\":\"root-exit\",\"pid\":%d,\"exitCode\":%d,\"signal\":%d}\n",
                    child,WIFEXITED(status)?WEXITSTATUS(status):-1,WIFSIGNALED(status)?WTERMSIG(status):0);
            }
            drop(child);continue;
        }
        if(!WIFSTOPPED(status)) {diagnostic("wait-state",EINVAL);failed=1;continue;}
        if(add(child)) {kill(child,SIGKILL);diagnostic("child-limit",E2BIG);failed=1;continue;}
        unsigned event=(unsigned)status>>16;int signal=WSTOPSIG(status),forward=signal;
        if(initial && child==root) {
            initial=0;
            if(signal!=SIGSTOP || event || ptrace(PTRACE_SETOPTIONS,child,NULL,(void *)(uintptr_t)options())) {
                diagnostic("initial-trace-options",errno);failed=1;kill(child,SIGKILL);continue;
            }
            forward=0;
        } else if(event==PTRACE_EVENT_FORK || event==PTRACE_EVENT_VFORK || event==PTRACE_EVENT_CLONE) {
            unsigned long newborn=0;
            if(ptrace(PTRACE_GETEVENTMSG,child,NULL,&newborn) || !newborn || newborn>INT_MAX) {diagnostic("fork-event",errno);failed=1;}
            else if(add((pid_t)newborn)) {kill((pid_t)newborn,SIGKILL);diagnostic("child-limit",E2BIG);failed=1;}
            forward=0;
        } else if(event==PTRACE_EVENT_EXEC) {
            unsigned long old_tid=0;
            if(ptrace(PTRACE_GETEVENTMSG,child,NULL,&old_tid)) {diagnostic("exec-event",errno);failed=1;}
            else if(old_tid && (pid_t)old_tid!=child) drop((pid_t)old_tid);
            forward=0;
        } else if(event) {
            diagnostic("unexpected-ptrace-event",EINVAL);failed=1;forward=0;
        } else {
            siginfo_t info={0};
            if(ptrace(PTRACE_GETSIGINFO,child,NULL,&info)) {
                /* Group stops are not signal delivery; don't inject a second
                 * signal. Initial auto-attached descendants stop with SIGSTOP. */
                if(errno==EINVAL) forward=0;
                else {diagnostic("siginfo",errno);failed=1;}
            } else if(signal==SIGSYS) {
                if(events++<EVENT_LIMIT)
                    record("{\"observer\":\"sigsys\",\"pid\":%d,\"signo\":%d,\"code\":%d,\"errno\":%d,\"syscall\":%d,\"arch\":%u,\"syscallKnown\":%s}\n",
                        child,info.si_signo,info.si_code,info.si_errno,info.si_code==1?info.si_syscall:-1,
                        info.si_code==1?info.si_arch:0,info.si_code==1?"true":"false");
                else {diagnostic("event-bound",E2BIG);failed=1;}
                /* PTRACE_CONT injects the unchanged signal and kernel siginfo. */
            } else if(signal==SIGSTOP && info.si_pid==0) forward=0;
        }
        if(stopping || failed) {kill(child,SIGKILL);forward=SIGKILL;}
        if(ptrace(PTRACE_CONT,child,NULL,(void *)(uintptr_t)forward) && errno!=ESRCH) {diagnostic("continue",errno);failed=1;}
    }
    if(count) {diagnostic("unreaped-records",ECHILD);return 125;}
    record("{\"observer\":\"cleanup\",\"reaped\":true,\"diagnosticOnly\":true}\n");
    close(diagnostic_fd);
    return failed||diagnostic_lost?125:root_status;
}
