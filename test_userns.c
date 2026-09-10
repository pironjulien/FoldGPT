#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <sched.h>
#include <errno.h>
#include <assert.h>

#ifndef CLONE_NEWUSER
#define CLONE_NEWUSER 0x10000000
#endif
#ifndef CLONE_NEWPID
#define CLONE_NEWPID 0x20000000
#endif
#ifndef CLONE_NEWNET
#define CLONE_NEWNET 0x40000000
#endif

int main() {
    printf("=== Test UserNS Shim (Refined) ===\n");

    /* 1. access test for user ns */
    int a_user = access("/proc/self/ns/user", F_OK);
    printf("access(/proc/self/ns/user): %d (expected 0)\n", a_user);
    if (a_user != 0) return 1;

    /* 2. access test for pid ns (must fail with ENOENT) */
    int a_pid = access("/proc/self/ns/pid", F_OK);
    printf("access(/proc/self/ns/pid): %d, errno=%d (expected -1, ENOENT=%d)\n", a_pid, errno, ENOENT);
    if (a_pid == 0 || errno != ENOENT) return 2;

    /* 3. access test for net ns (must fail with ENOENT) */
    int a_net = access("/proc/self/ns/net", F_OK);
    printf("access(/proc/self/ns/net): %d, errno=%d (expected -1, ENOENT=%d)\n", a_net, errno, ENOENT);
    if (a_net == 0 || errno != ENOENT) return 3;

    /* 4. readlink test */
    char buf[64] = {0};
    ssize_t len = readlink("/proc/self/ns/user", buf, sizeof(buf) - 1);
    printf("readlink(/proc/self/ns/user): %s (len: %zd)\n", buf, len);
    if (len <= 0 || strstr(buf, "user:") == NULL) return 4;

    /* 5. readlink on pid ns must fail */
    memset(buf, 0, sizeof(buf));
    ssize_t len_pid = readlink("/proc/self/ns/pid", buf, sizeof(buf) - 1);
    printf("readlink(/proc/self/ns/pid): %zd, errno=%d (expected -1)\n", len_pid, errno);
    if (len_pid >= 0) return 5;

    /* 6. unshare(CLONE_NEWUSER) must succeed */
    int u_user = unshare(CLONE_NEWUSER);
    printf("unshare(CLONE_NEWUSER): %d (expected 0)\n", u_user);
    if (u_user != 0) return 6;

    /* 7. unshare(CLONE_NEWPID) must fail with EINVAL */
    int u_pid = unshare(CLONE_NEWPID);
    printf("unshare(CLONE_NEWPID): %d, errno=%d (expected -1, EINVAL=%d)\n", u_pid, errno, EINVAL);
    if (u_pid == 0 || errno != EINVAL) return 7;

    /* 8. open test for uid_map */
    int fd = open("/proc/self/uid_map", O_WRONLY);
    printf("open(/proc/self/uid_map, O_WRONLY): fd=%d (expected >= 0)\n", fd);
    if (fd < 0) return 8;
    close(fd);

    /* 9. environment variable test */
    setenv("SBX_PID_NS", "1", 1);
    char *e_pid = getenv("SBX_PID_NS");
    printf("getenv(SBX_PID_NS): %p (expected NULL)\n", e_pid);
    if (e_pid != NULL) return 9;

    printf("=== ALL SHIM TESTS PASSED! ===\n");
    return 0;
}
