#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <linux/seccomp.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Diagnostic only. Run outside PRoot/shims: each mutating probe is confined to
 * a disposable child, and no flags/security settings of its parent are changed. */
static void result(const char *name, long rc) {
    int error = errno;
    printf("%s result=%ld errno=%d (%s)\n", name, rc, rc < 0 ? error : 0,
           rc < 0 ? strerror(error) : "OK");
}
static void run_probe(const char *name, int kind, unsigned long argument) {
    pid_t child = fork();
    if (child == -1) { result("fork", -1); exit(1); }
    if (!child) {
        errno = 0;
        long rc;
        if (kind == 0) rc = syscall(SYS_unshare, argument);
        else if (kind == 1) rc = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
        else {
            unsigned int action = SECCOMP_RET_USER_NOTIF;
            rc = syscall(SYS_seccomp, SECCOMP_GET_ACTION_AVAIL, 0, &action);
        }
        result(name, rc);
        fflush(stdout);
        _exit(rc < 0 ? 1 : 0);
    }
    int status;
    if (waitpid(child, &status, 0) < 0) { result("waitpid", -1); exit(1); }
    if (WIFSIGNALED(status)) printf("%s terminated_by_signal=%d\n", name, WTERMSIG(status));
}
int main(void) {
    setbuf(stdout, NULL);
    printf("uid=%u euid=%u seccomp=%d no_new_privs=%d\n", getuid(), geteuid(),
           prctl(PR_GET_SECCOMP), prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0));
    const char *names[] = {"user", "pid", "mnt", "net"};
    for (int i=0; i<4; ++i) {
        char path[64], target[128];
        snprintf(path, sizeof(path), "/proc/self/ns/%s", names[i]);
        errno=0;
        ssize_t n=readlink(path,target,sizeof(target)-1);
        if (n<0) result(path,n);
        else { target[n]=0; printf("%s -> %s\n",path,target); }
    }
    run_probe("unshare_user",0,CLONE_NEWUSER);
    run_probe("unshare_mount",0,CLONE_NEWNS);
    run_probe("unshare_pid",0,CLONE_NEWPID);
    run_probe("landlock_abi",1,0);
    run_probe("seccomp_user_notification",2,0);
    return 0;
}
