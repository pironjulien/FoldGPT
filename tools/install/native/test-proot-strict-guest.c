/* Real Linux syscalls used by test-proot-strict.py. No namespace/mount is
 * created: those tests inherit an actual kernel seccomp denial. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/openat2.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

#define NS_FLAGS (CLONE_NEWNS | CLONE_NEWUTS | CLONE_NEWIPC | CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNET | CLONE_NEWCGROUP)
#define DENY(nr) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (nr), 0, 1), BPF_STMT(BPF_RET | BPF_K, action)

static void install_filter(uint32_t action, int robust_only)
{
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        DENY(SYS_unshare), DENY(SYS_setns), DENY(SYS_mount),
        DENY(SYS_umount2), DENY(SYS_pivot_root), DENY(SYS_clone3), DENY(SYS_setgroups),
        /* clone's flags are visible to BPF; ordinary fork/thread stays real. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_clone, 0, 4),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, NS_FLAGS, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, action),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_prctl, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, PR_GET_NO_NEW_PRIVS, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, action),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_filter robust[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        DENY(SYS_set_robust_list),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = robust_only ? sizeof(robust) / sizeof(robust[0]) : sizeof(instructions) / sizeof(instructions[0]),
        .filter = robust_only ? robust : instructions,
    };
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) || prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &program)) {
        perror("install real seccomp");
        exit(90);
    }
}

static void sigsys_handler(int number, siginfo_t *info, void *context)
{
    (void) context;
    int32_t record[] = {number, info->si_code, info->si_syscall};
    if (write(STDOUT_FILENO, record, sizeof(record)) != sizeof(record))
        _exit(91);
    _exit(77);
}

static void result(long value, int error)
{
    printf("result=%ld errno=%d\n", value, error);
}

static int nnp(void)
{
    errno = 0;
    long value = prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0);
    int error = errno;
    FILE *file = fopen("/proc/self/status", "r");
    if (!file) return 92;
    char line[256];
    int actual = -1;
    while (fgets(line, sizeof(line), file)) {
        if (sscanf(line, "NoNewPrivs: %d", &actual) == 1) break;
    }
    fclose(file);
    printf("result=%ld errno=%d actual=%d\n", value, error, actual);
    return actual < 0 ? 93 : 0;
}

static int mappings(const char *style, const char *operation, const char *name)
{
    char path[128];
    if (!strcmp(style, "numeric")) snprintf(path, sizeof(path), "/proc/%d/%s", getpid(), name);
    else snprintf(path, sizeof(path), "/proc/self/%s", name);
    int flags = !strcmp(operation, "read") ? O_RDONLY : O_WRONLY;
    errno = 0;
    int fd = !strcmp(style, "open") ? syscall(SYS_open, path, flags, 0) : syscall(SYS_openat, AT_FDCWD, path, flags, 0);
    if (fd < 0) { result(-1, errno); return 0; }
    char data[512] = {0};
    /* Deliberately invalid input cannot create/change a real mapping. */
    ssize_t size = flags == O_RDONLY ? read(fd, data, sizeof(data)) : write(fd, "invalid\n", 8);
    int error = errno;
    close(fd);
    result(size, error);
    if (flags == O_RDONLY && size > 0) {
        for (ssize_t i = 0; i < size; ++i) printf("%02x", (unsigned char) data[i]);
        printf("\n");
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (!getuid() || argc < 2) return 94;
    if (!strcmp(argv[1], "launch")) {
        if (argc < 4) return 95;
        if (!strcmp(argv[2], "nnp")) {
            if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) return 96;
        } else install_filter(!strcmp(argv[2], "trap") ? SECCOMP_RET_TRAP : (SECCOMP_RET_ERRNO | EACCES), 0);
        execv(argv[3], argv + 3);
        perror("execv");
        return 97;
    }
    if (!strcmp(argv[1], "nnp")) return nnp();
    if (!strcmp(argv[1], "nnp-set")) {
        if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0)) return 98;
        return nnp();
    }
    if (!strcmp(argv[1], "fork-exec")) {
        pid_t child = fork();
        if (child < 0) return 99;
        if (!child) { execv(argv[2], argv + 2); _exit(100); }
        int status;
        if (waitpid(child, &status, 0) != child) return 101;
        return WIFEXITED(status) ? WEXITSTATUS(status) : 102;
    }
    if (!strcmp(argv[1], "maps") && argc == 5) return mappings(argv[2], argv[3], argv[4]);
    if (!strcmp(argv[1], "call") && argc >= 4) {
        const char *name = argv[2];
        struct sigaction sa = {.sa_sigaction = sigsys_handler, .sa_flags = SA_SIGINFO};
        sigemptyset(&sa.sa_mask);
        if (sigaction(SIGSYS, &sa, NULL)) return 103;
        char source[4096], target[4096];
        snprintf(source, sizeof(source), "%s/source", argv[3]);
        snprintf(target, sizeof(target), "%s/target", argv[3]);
        long value;
        errno = 0;
        if (!strcmp(name, "unshare")) value = syscall(SYS_unshare, CLONE_NEWUSER | CLONE_NEWNET);
        else if (!strcmp(name, "unshare-zero")) value = syscall(SYS_unshare, 0);
        else if (!strcmp(name, "setns")) value = syscall(SYS_setns, -1, CLONE_NEWUSER);
        else if (!strcmp(name, "mount")) value = syscall(SYS_mount, source, target, NULL, MS_BIND, NULL);
        else if (!strcmp(name, "umount")) value = syscall(SYS_umount2, target, MNT_DETACH);
        else if (!strcmp(name, "pivot")) value = syscall(SYS_pivot_root, target, source);
        else if (!strcmp(name, "setgroups")) value = syscall(SYS_setgroups, 0, NULL);
        else if (!strcmp(name, "get-nnp")) value = prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0);
        else if (!strcmp(name, "invalid-nnp")) value = prctl(PR_GET_NO_NEW_PRIVS, 1, 0, 0, 0);
        else if (!strcmp(name, "dumpable")) value = prctl(PR_SET_DUMPABLE, 0, 0, 0, 0);
        else if (!strcmp(name, "clone")) {
            value = syscall(SYS_clone, CLONE_NEWUSER | CLONE_NEWNS | CLONE_NEWNET | SIGCHLD, NULL, NULL, NULL, 0);
            if (!value) _exit(0);
            int error = errno, status;
            if (value > 0) {
                if (waitpid(value, &status, 0) != value || status) return 104;
                value = 1;
            }
            result(value, error);
            return 0;
        } else if (!strcmp(name, "clone3")) {
            struct clone_args args = {.flags = CLONE_NEWUSER | CLONE_NEWNS | CLONE_NEWNET, .exit_signal = SIGCHLD};
            uint64_t original = args.flags;
            value = syscall(SYS_clone3, &args, sizeof(args));
            if (!value) _exit(0);
            int error = errno;
            if (value > 0) { int status; if (waitpid(value, &status, 0) != value || status) return 105; value = 1; }
            printf("result=%ld errno=%d flags_unchanged=%d flags=%llu\n", value, error, args.flags == original, (unsigned long long) args.flags);
            return 0;
        } else if (!strcmp(name, "robust")) {
            install_filter(SECCOMP_RET_TRAP, 1);
            errno = 0;
            value = syscall(SYS_set_robust_list, NULL, 0);
        } else if (!strcmp(name, "openat2") || !strcmp(name, "openat2-resolve")) {
            struct open_how how = {.flags = O_RDONLY, .resolve = !strcmp(name, "openat2-resolve") ? RESOLVE_NO_SYMLINKS : 0};
            value = syscall(SYS_openat2, AT_FDCWD, "/dev/null", &how, sizeof(how));
            if (value >= 0) { close(value); value = 0; }
        } else return 106;
        int error = errno;
        result(value, error);
        return 0;
    }
    return 107;
}
