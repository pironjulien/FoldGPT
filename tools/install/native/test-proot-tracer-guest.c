/* Real memory/tracing/signal operations against test-owned processes only. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/ptrace.h>
#include <sys/syscall.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

#define ORIGINAL UINT64_C(0x1020304050607080)
#define CHANGED UINT64_C(0x8877665544332211)
static volatile uint64_t owned_marker = ORIGINAL;
static volatile sig_atomic_t owned_signals;

static void on_signal(int number) { (void)number; owned_signals++; }
static void require(int value, const char *message)
{
    if (!value) { perror(message); exit(90); }
}
static void transfer(int fd, void *data, size_t size, int writing)
{
    ssize_t n;
    do n = writing ? write(fd, data, size) : read(fd, data, size); while (n < 0 && errno == EINTR);
    require(n == (ssize_t)size, "owned test pipe");
}
static long memory(pid_t target, uintptr_t address, uint64_t *data, int writing)
{
    struct iovec local = { data, sizeof(*data) }, remote = { (void *)address, sizeof(*data) };
    return writing ? process_vm_writev(target, &local, 1, &remote, 1, 0) : process_vm_readv(target, &local, 1, &remote, 1, 0);
}
static int layer(void)
{
    struct { uint64_t fs, net, scoped; } attr = { .scoped = 3 };
    int fd = (int)syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0U);
    if (fd < 0) return -1;
    int result = prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0);
    if (!result) result = (int)syscall(SYS_landlock_restrict_self, fd, 0U);
    int saved = errno; close(fd); errno = saved; return result;
}
static int denial(long result, int error) { return result == -1 && (error == EPERM || error == EACCES); }
static int operations(pid_t target, uintptr_t address, int nested, int emulated)
{
    uint64_t data = 0;
    errno = 0; long result = memory(target, address, &data, 0); int error = errno;
    printf("memory_read result=%ld errno=%d\n", result, error);
    require(nested ? denial(result, error) : result == 8 && data == ORIGINAL, "target memory read");
    data = CHANGED; errno = 0; result = memory(target, address, &data, 1); error = errno;
    printf("memory_write result=%ld errno=%d\n", result, error);
    require(nested ? denial(result, error) : result == 8, "target memory write");
    char path[80]; snprintf(path, sizeof(path), "/proc/%d/mem", target);
    errno = 0; int fd = open(path, O_RDWR | O_CLOEXEC); error = errno;
    printf("proc_memory_open result=%d errno=%d\n", fd, error);
    if (nested) require(denial(fd, error), "target proc memory denied");
    else {
        require(fd >= 0 && pread(fd, &data, sizeof(data), (off_t)address) == 8 && data == CHANGED, "target proc memory read");
        require(pwrite(fd, &data, sizeof(data), (off_t)address) == 8, "target proc memory write");
        close(fd);
    }
    errno = 0; result = ptrace(PTRACE_ATTACH, target, NULL, NULL); error = errno;
    printf("ptrace_attach result=%ld errno=%d\n", result, error);
    if (emulated) require(result == -1 && (error == ESRCH || error == EPERM || error == EACCES), "PRoot cannot trace itself");
    else if (nested) require(denial(result, error), "target ptrace denied");
    else {
        int status;
        require(!result && waitpid(target, &status, 0) == target && WIFSTOPPED(status), "target ptrace stop");
        require(!ptrace(PTRACE_DETACH, target, NULL, NULL), "target ptrace detach");
    }
    errno = 0; result = kill(target, emulated ? SIGWINCH : SIGUSR1); error = errno;
    printf("signal result=%ld errno=%d\n", result, error);
    require(nested ? denial(result, error) : result == 0, "target signal");
    return 0;
}

static int hierarchy(int nested)
{
    int ready[2], release[2];
    require(!pipe2(ready, O_CLOEXEC) && !pipe2(release, O_CLOEXEC), "hierarchy pipes");
    struct sigaction action = { .sa_handler = on_signal };
    require(!sigaction(SIGUSR1, &action, NULL), "owned signal handler");
    require(!layer(), "outer native scope inherited by both processes");
    pid_t owner = getpid(), child = fork();
    require(child >= 0, "hierarchy fork");
    if (!child) {
        close(ready[0]); close(release[1]);
        if (nested) require(!layer(), "scope-only child domain");
        uintptr_t address = (uintptr_t)&owned_marker;
        transfer(ready[1], &address, sizeof(address), 1);
        char ack; transfer(release[0], &ack, 1, 0);
        require(owned_marker == CHANGED, "parent wrote actual child memory");
        operations(owner, (uintptr_t)&owned_marker, nested, 0);
        fflush(stdout);
        _exit(0);
    }
    close(ready[1]); close(release[0]);
    require(!prctl(PR_SET_PTRACER, child, 0, 0, 0), "explicit owned-child Yama exception");
    uintptr_t address; transfer(ready[0], &address, sizeof(address), 0);
    uint64_t data = 0;
    require(memory(child, address, &data, 0) == 8 && data == ORIGINAL, "parent reads nested child");
    data = CHANGED;
    require(memory(child, address, &data, 1) == 8, "parent writes nested child");
    require(!ptrace(PTRACE_ATTACH, child, NULL, NULL), "parent traces nested child");
    int status;
    require(waitpid(child, &status, 0) == child && WIFSTOPPED(status), "parent sees actual ptrace stop");
    require(!ptrace(PTRACE_DETACH, child, NULL, NULL), "parent detaches nested child");
    char ack = 'P'; transfer(release[1], &ack, 1, 1);
    pid_t waited;
    do waited = waitpid(child, &status, 0); while (waited < 0 && errno == EINTR);
    require(waited == child && WIFEXITED(status) && WEXITSTATUS(status) == 0, "owned child completes");
    require(owned_marker == (nested ? ORIGINAL : CHANGED), "independent parent marker");
    require(owned_signals == (nested ? 0 : 1), "independent parent signal counter");
    printf("hierarchy outer_domain=active nested=%d parent_to_child=PASS child_to_parent=%s cleanup=waitpid marker=%llu signals=%d\n",
           nested, nested ? "DENIED" : "ALLOWED", (unsigned long long)owned_marker, owned_signals);
    close(ready[0]); close(release[1]); return 0;
}

int main(int argc, char **argv)
{
    require(getuid() != 0 && argc >= 3, "nonroot test arguments");
    if (!strcmp(argv[1], "deny-bootstrap")) {
        struct sock_filter filter[] = {
            BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
            BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_landlock_restrict_self, 0, 1),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EACCES),
            BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        };
        struct sock_fprog program = { sizeof(filter) / sizeof(filter[0]), filter };
        require(!prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) &&
                !prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program), "real bootstrap refusal");
        execv(argv[2], argv + 2); perror("bootstrap exec"); return 91;
    }
    require(argc == 3, "exact test arguments");
    int nested = !strcmp(argv[2], "nested");
    if (!strcmp(argv[1], "hierarchy")) return hierarchy(nested);
    require(!strcmp(argv[1], "guest"), "known test mode");
    const char *pid = getenv("FOLDGPT_TRACER_TEST_PID"), *address = getenv("FOLDGPT_TRACER_TEST_ADDRESS");
    require(pid && address, "owned tracer identity fixture");
    operations((pid_t)strtol(pid, NULL, 10), (uintptr_t)strtoull(address, NULL, 10), nested, 1);
    printf("actual_proot_guest=%s\n", nested ? "DENIED" : "ALLOWED");
    return 0;
}
