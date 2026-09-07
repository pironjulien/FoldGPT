/* Host test only: expose one owned PRoot marker and relax Yama explicitly.
 * This library is never packaged and is removed from the guest environment. */
#define _GNU_SOURCE
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <unistd.h>

static volatile uint64_t marker = UINT64_C(0x1020304050607080);
static int report_fd = -1;
static pid_t owner;

__attribute__((constructor)) static void prepare(void)
{
    const char *setting = getenv("FOLDGPT_TRACER_TEST_FD");
    if (!setting) _exit(91);
    report_fd = atoi(setting);
    owner = getpid();
    if (prctl(PR_SET_DUMPABLE, 1, 0, 0, 0) || prctl(PR_SET_PTRACER, PR_SET_PTRACER_ANY, 0, 0, 0)) _exit(92);
    char value[64];
    snprintf(value, sizeof(value), "%d", owner);
    if (setenv("FOLDGPT_TRACER_TEST_PID", value, 1)) _exit(93);
    snprintf(value, sizeof(value), "%llu", (unsigned long long)(uintptr_t)&marker);
    if (setenv("FOLDGPT_TRACER_TEST_ADDRESS", value, 1) || unsetenv("LD_PRELOAD")) _exit(94);
    dprintf(report_fd, "begin pid=%d marker=%llu yama_relaxed=1\n", owner, (unsigned long long)marker);
}

__attribute__((destructor)) static void finish(void)
{
    if (getpid() == owner)
        dprintf(report_fd, "end pid=%d marker=%llu\n", owner, (unsigned long long)marker);
}
