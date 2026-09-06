/* Deterministic first-fork cancellation injection. Host regression only.
 * SIGTERM is queued before PRoot learns its first child's PID. */
#define _GNU_SOURCE
#include <dlfcn.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/types.h>
#include <unistd.h>

pid_t fork(void) {
    pid_t (*actual)(void)=dlsym(RTLD_NEXT,"fork");
    if (!actual) _exit(91);
    pid_t result=actual();
    const char *record=getenv("FOLDGPT_TEST_FORK_RECORD");
    sigset_t mask;
    if (sigprocmask(SIG_SETMASK,NULL,&mask)<0) _exit(94);
    /* PRoot also forks its short F2FS capability probe during configuration.
     * Inject specifically inside the launch window guarded by this patch. */
    if (result>0 && record && sigismember(&mask,SIGTERM)==1) {
        int fd=open(record,O_WRONLY|O_CREAT|O_EXCL,0600);
        if (fd<0 || dprintf(fd,"%ld\n",(long)result)<0 || close(fd)<0) _exit(92);
        if (kill(getpid(),SIGTERM)<0) _exit(93);
    }
    return result;
}
