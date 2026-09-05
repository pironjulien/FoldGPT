#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
#include <dlfcn.h>
#include <sched.h>
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <sys/syscall.h>
#include <sys/prctl.h>
#include <sys/wait.h>
#include <errno.h>
#include <stdarg.h>
#include <signal.h>
#include <ucontext.h>
#include <execinfo.h>
#include <dirent.h>
#include <sys/statfs.h>
#include <sys/statvfs.h>

#ifndef CLONE_NEWNS
#define CLONE_NEWNS 0x00020000
#endif
#ifndef CLONE_NEWCGROUP
#define CLONE_NEWCGROUP 0x08000000
#endif
#ifndef CLONE_NEWUTS
#define CLONE_NEWUTS 0x04000000
#endif
#ifndef CLONE_NEWIPC
#define CLONE_NEWIPC 0x02000000
#endif
#ifndef CLONE_NEWUSER
#define CLONE_NEWUSER 0x10000000
#endif
#ifndef CLONE_NEWPID
#define CLONE_NEWPID 0x20000000
#endif
#ifndef CLONE_NEWNET
#define CLONE_NEWNET 0x40000000
#endif

#ifndef SYS_clone3
#define SYS_clone3 435
#endif

#ifndef SYS_newfstatat
#define SYS_newfstatat 79
#endif

#ifndef SYS_statx
#define SYS_statx 291
#endif

#ifndef SYS_openat
#define SYS_openat 56
#endif

#ifndef SYS_openat2
#define SYS_openat2 437
#endif

#define FORBIDDEN_CLONE_FLAGS ((uint64_t)(CLONE_NEWUSER | CLONE_NEWPID | CLONE_NEWNET | CLONE_NEWNS | CLONE_NEWIPC | CLONE_NEWUTS | CLONE_NEWCGROUP))

static volatile int is_chrooted = 0;

static void shim_log(const char *msg) {
#ifdef SHIM_DEBUG
    int fd = open("/tmp/shim.log", O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd >= 0) {
        write(fd, msg, strlen(msg));
        close(fd);
    }
#else
    (void)msg;
#endif
}

static void sig_handler(int sig, siginfo_t *info, void *ucontext) {
    ucontext_t *uc = (ucontext_t *)ucontext;
    char buf[512];
    #if defined(__aarch64__)
    uintptr_t pc = (uintptr_t)uc->uc_mcontext.pc;
    Dl_info dlinfo;
    if (dladdr((void *)pc, &dlinfo) && dlinfo.dli_fname) {
        snprintf(buf, sizeof(buf), 
            "\n*** CRASH: caught signal %d at pc=0x%lx (%s + 0x%lx, symbol: %s) ***\n", 
            sig, pc, dlinfo.dli_fname, pc - (uintptr_t)dlinfo.dli_fbase,
            dlinfo.dli_sname ? dlinfo.dli_sname : "unknown");
    } else {
        snprintf(buf, sizeof(buf), "\n*** CRASH: caught signal %d at pc=0x%lx ***\n", sig, pc);
    }
    #else
    snprintf(buf, sizeof(buf), "\n*** CRASH: caught signal %d ***\n", sig);
    #endif
    shim_log(buf);

    int fd = open("/tmp/shim.log", O_WRONLY | O_CREAT | O_APPEND, 0666);
    if (fd >= 0) {
        void *array[32];
        int size = backtrace(array, 32);
        backtrace_symbols_fd(array, size, fd);
        write(fd, "\n", 1);
        close(fd);
    }
    _exit(128 + sig);
}

typedef int (*orig_sigaction_t)(int, const struct sigaction *, struct sigaction *);
static orig_sigaction_t orig_sigaction = NULL;

static void install_crash_handlers(void) {
    if (!orig_sigaction) orig_sigaction = (orig_sigaction_t)dlsym(RTLD_NEXT, "sigaction");
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = sig_handler;
    sa.sa_flags = SA_SIGINFO | SA_NODEFER;
    if (orig_sigaction) {
        orig_sigaction(SIGTRAP, &sa, NULL);
        orig_sigaction(SIGSEGV, &sa, NULL);
    }
}

int sigaction(int signum, const struct sigaction *act, struct sigaction *oldact) {
    if (!orig_sigaction) orig_sigaction = (orig_sigaction_t)dlsym(RTLD_NEXT, "sigaction");
    if (signum == SIGTRAP && act && act->sa_sigaction != sig_handler) {
        shim_log("sigaction(SIGTRAP) from Chromium intercepted: preserving diagnostic handler\n");
        if (oldact) {
            memset(oldact, 0, sizeof(*oldact));
            oldact->sa_sigaction = sig_handler;
            oldact->sa_flags = SA_SIGINFO;
        }
        return 0;
    }
    return orig_sigaction ? orig_sigaction(signum, act, oldact) : 0;
}

__attribute__((constructor)) static void init_shim(void) {
    install_crash_handlers();
    char buf[128];
    snprintf(buf, sizeof(buf), "PID %d (ppid %d): libfake_userns initialized\n", getpid(), getppid());
    shim_log(buf);
}

static int is_ns_path(const char *path, const char *ns_type) {
    if (!path) return 0;
    if (strstr(path, "/ns/") && strstr(path, ns_type)) return 1;
    return 0;
}

static int is_map_path(const char *path) {
    if (!path) return 0;
    if (strstr(path, "/uid_map") || strstr(path, "/gid_map") || strstr(path, "/setgroups")) return 1;
    return 0;
}

static int is_proc_path(const char *path) {
    if (!path) return 0;
    if (strcmp(path, "/proc") == 0 || strcmp(path, "/proc/") == 0) return 1;
    if (strncmp(path, "/proc/", 6) == 0) return 1;
    if (strcmp(path, "proc") == 0 || strcmp(path, "proc/") == 0) return 1;
    if (strncmp(path, "proc/", 5) == 0) return 1;
    return 0;
}

static int check_chrooted_proc(const char *pathname) {
    if (is_chrooted && is_proc_path(pathname)) {
        shim_log("BLOCKED /proc access after chroot -> ENOENT\n");
        errno = ENOENT;
        return 1;
    }
    return 0;
}

/* getpid */
typedef pid_t (*orig_getpid_t)(void);
pid_t getpid(void) {
    const char *is_zygote = getenv("SBX_PID_NS");
    if (is_zygote) {
        return 1;
    }
    static orig_getpid_t orig_getpid = NULL;
    if (!orig_getpid) orig_getpid = (orig_getpid_t)dlsym(RTLD_NEXT, "getpid");
    return orig_getpid ? orig_getpid() : 1;
}

/* chroot intercept */
int chroot(const char *path) {
    char buf[128];
    snprintf(buf, sizeof(buf), "chroot(%s) -> 0\n", path ? path : "null");
    shim_log(buf);
    is_chrooted = 1;
    return 0;
}

/* waitpid intercept */
typedef pid_t (*orig_waitpid_t)(pid_t, int *, int);
pid_t waitpid(pid_t pid, int *status, int options) {
    static orig_waitpid_t orig_waitpid = NULL;
    if (!orig_waitpid) orig_waitpid = (orig_waitpid_t)dlsym(RTLD_NEXT, "waitpid");
    pid_t res = orig_waitpid ? orig_waitpid(pid, status, options) : -1;
    char buf[128];
    snprintf(buf, sizeof(buf), "PID %d: waitpid(%d) -> %d errno=%d\n", getpid(), (int)pid, (int)res, errno);
    shim_log(buf);
    if (res == -1 && errno == ECHILD && pid > 0) {
        shim_log("waitpid ECHILD simulated success\n");
        if (status) *status = 0;
        return pid;
    }
    return res;
}

/* capset / capget */
int capset(void *hdrp, const void *datap) {
    shim_log("capset() intercepted -> 0\n");
    return 0;
}

int capget(void *hdrp, void *datap) {
    shim_log("capget() intercepted -> 0\n");
    return 0;
}

/* prctl */
int prctl(int option, ...) {
    va_list args;
    va_start(args, option);
    unsigned long a2 = va_arg(args, unsigned long);
    unsigned long a3 = va_arg(args, unsigned long);
    unsigned long a4 = va_arg(args, unsigned long);
    unsigned long a5 = va_arg(args, unsigned long);
    va_end(args);

    #ifdef PR_CAP_AMBIENT
    if (option == PR_CAP_AMBIENT) {
        shim_log("prctl(PR_CAP_AMBIENT) -> 0\n");
        return 0;
    }
    #endif
    static int (*orig_prctl)(int, ...) = NULL;
    if (!orig_prctl) orig_prctl = (int (*)(int, ...))dlsym(RTLD_NEXT, "prctl");
    return orig_prctl ? orig_prctl(option, a2, a3, a4, a5) : 0;
}

/* setns */
int setns(int fd, int nstype) {
    shim_log("setns intercepted -> 0\n");
    return 0;
}

/* unshare */
typedef int (*orig_unshare_t)(int flags);
int unshare(int flags) {
    char buf[128];
    snprintf(buf, sizeof(buf), "PID %d: unshare(0x%x)\n", getpid(), flags);
    shim_log(buf);
    static orig_unshare_t orig_unshare = NULL;
    if (!orig_unshare) orig_unshare = (orig_unshare_t)dlsym(RTLD_NEXT, "unshare");
    int filtered = flags & ~FORBIDDEN_CLONE_FLAGS;
    if (filtered == 0) return 0;
    return orig_unshare ? orig_unshare(filtered) : 0;
}

struct clone_hook_arg {
    int (*fn)(void *);
    void *arg;
};

static int clone_hook_fn(void *arg) {
    struct clone_hook_arg *h = (struct clone_hook_arg *)arg;
    install_crash_handlers();

    char buf[128];
    snprintf(buf, sizeof(buf), "CHILD PID %d (real_pid=%d): entered clone_hook_fn!\n", getpid(), (int)syscall(SYS_getpid));
    shim_log(buf);
    int (*real_fn)(void *) = h->fn;
    void *real_arg = h->arg;
    free(h);
    int ret = real_fn(real_arg);
    snprintf(buf, sizeof(buf), "CHILD PID %d: real_fn returned %d\n", getpid(), ret);
    shim_log(buf);
    return ret;
}

/* clone */
typedef int (*orig_clone_t)(int (*fn)(void *), void *stack, int flags, void *arg, ...);
int clone(int (*fn)(void *), void *stack, int flags, void *arg, ...) {
    static orig_clone_t orig_clone = NULL;
    if (!orig_clone) orig_clone = (orig_clone_t)dlsym(RTLD_NEXT, "clone");
    if (!orig_clone) {
        errno = ENOSYS;
        return -1;
    }
    
    va_list args;
    va_start(args, arg);
    pid_t *parent_tid = va_arg(args, pid_t *);
    void *tls = va_arg(args, void *);
    pid_t *child_tid = va_arg(args, pid_t *);
    va_end(args);

    if ((flags & FORBIDDEN_CLONE_FLAGS) == 0) {
        return orig_clone(fn, stack, flags, arg, parent_tid, tls, child_tid);
    }

    char buf[128];
    snprintf(buf, sizeof(buf), "PID %d: clone(flags=0x%x, stack=%p) -> stripping forbidden ns flags\n", getpid(), flags, stack);
    shim_log(buf);

    int filtered = flags & ~FORBIDDEN_CLONE_FLAGS;

    struct clone_hook_arg *h = malloc(sizeof(struct clone_hook_arg));
    h->fn = fn;
    h->arg = arg;

    int res = orig_clone(clone_hook_fn, stack, filtered, h, parent_tid, tls, child_tid);
    snprintf(buf, sizeof(buf), "PID %d: clone result=%d errno=%d\n", getpid(), res, errno);
    shim_log(buf);
    return res;
}

/* stat variants */
typedef int (*orig_stat_t)(const char *, struct stat *);
int stat(const char *pathname, struct stat *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static orig_stat_t orig_stat = NULL;
    if (!orig_stat) orig_stat = (orig_stat_t)dlsym(RTLD_NEXT, "stat");
    return orig_stat ? orig_stat(pathname, statbuf) : -1;
}

int stat64(const char *pathname, struct stat64 *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static int (*orig_stat64)(const char *, struct stat64 *) = NULL;
    if (!orig_stat64) orig_stat64 = (int (*)(const char *, struct stat64 *))dlsym(RTLD_NEXT, "stat64");
    return orig_stat64 ? orig_stat64(pathname, statbuf) : -1;
}

int lstat(const char *pathname, struct stat *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static orig_stat_t orig_lstat = NULL;
    if (!orig_lstat) orig_lstat = (orig_stat_t)dlsym(RTLD_NEXT, "lstat");
    return orig_lstat ? orig_lstat(pathname, statbuf) : -1;
}

int lstat64(const char *pathname, struct stat64 *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static int (*orig_lstat64)(const char *, struct stat64 *) = NULL;
    if (!orig_lstat64) orig_lstat64 = (int (*)(const char *, struct stat64 *))dlsym(RTLD_NEXT, "lstat64");
    return orig_lstat64 ? orig_lstat64(pathname, statbuf) : -1;
}

typedef int (*orig_fstatat_t)(int, const char *, struct stat *, int);
int fstatat(int dirfd, const char *pathname, struct stat *statbuf, int flags) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    static orig_fstatat_t orig_fstatat = NULL;
    if (!orig_fstatat) orig_fstatat = (orig_fstatat_t)dlsym(RTLD_NEXT, "fstatat");
    return orig_fstatat ? orig_fstatat(dirfd, pathname, statbuf, flags) : -1;
}

int fstatat64(int dirfd, const char *pathname, struct stat64 *statbuf, int flags) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    static int (*orig_fstatat64)(int, const char *, struct stat64 *, int) = NULL;
    if (!orig_fstatat64) orig_fstatat64 = (int (*)(int, const char *, struct stat64 *, int))dlsym(RTLD_NEXT, "fstatat64");
    return orig_fstatat64 ? orig_fstatat64(dirfd, pathname, statbuf, flags) : -1;
}

int __fstatat64(int dirfd, const char *pathname, struct stat64 *statbuf, int flags) {
    return fstatat64(dirfd, pathname, statbuf, flags);
}

int __xstat(int ver, const char *pathname, struct stat *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static int (*orig)(int, const char *, struct stat *) = NULL;
    if (!orig) orig = (int (*)(int, const char *, struct stat *))dlsym(RTLD_NEXT, "__xstat");
    return orig ? orig(ver, pathname, statbuf) : -1;
}

int __xstat64(int ver, const char *pathname, struct stat64 *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static int (*orig)(int, const char *, struct stat64 *) = NULL;
    if (!orig) orig = (int (*)(int, const char *, struct stat64 *))dlsym(RTLD_NEXT, "__xstat64");
    return orig ? orig(ver, pathname, statbuf) : -1;
}

int __lxstat(int ver, const char *pathname, struct stat *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static int (*orig)(int, const char *, struct stat *) = NULL;
    if (!orig) orig = (int (*)(int, const char *, struct stat *))dlsym(RTLD_NEXT, "__lxstat");
    return orig ? orig(ver, pathname, statbuf) : -1;
}

int __lxstat64(int ver, const char *pathname, struct stat64 *statbuf) {
    if (check_chrooted_proc(pathname)) return -1;
    static int (*orig)(int, const char *, struct stat64 *) = NULL;
    if (!orig) orig = (int (*)(int, const char *, struct stat64 *))dlsym(RTLD_NEXT, "__lxstat64");
    return orig ? orig(ver, pathname, statbuf) : -1;
}

int __fxstat(int ver, int fd, struct stat *statbuf) {
    static int (*orig)(int, int, struct stat *) = NULL;
    if (!orig) orig = (int (*)(int, int, struct stat *))dlsym(RTLD_NEXT, "__fxstat");
    return orig ? orig(ver, fd, statbuf) : -1;
}

int __fxstat64(int ver, int fd, struct stat64 *statbuf) {
    static int (*orig)(int, int, struct stat64 *) = NULL;
    if (!orig) orig = (int (*)(int, int, struct stat64 *))dlsym(RTLD_NEXT, "__fxstat64");
    return orig ? orig(ver, fd, statbuf) : -1;
}

int __fxstatat(int ver, int dirfd, const char *pathname, struct stat *statbuf, int flags) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    static int (*orig)(int, int, const char *, struct stat *, int) = NULL;
    if (!orig) orig = (int (*)(int, int, const char *, struct stat *, int))dlsym(RTLD_NEXT, "__fxstatat");
    return orig ? orig(ver, dirfd, pathname, statbuf, flags) : -1;
}

int __fxstatat64(int ver, int dirfd, const char *pathname, struct stat64 *statbuf, int flags) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    static int (*orig)(int, int, const char *, struct stat64 *, int) = NULL;
    if (!orig) orig = (int (*)(int, int, const char *, struct stat64 *, int))dlsym(RTLD_NEXT, "__fxstatat64");
    return orig ? orig(ver, dirfd, pathname, statbuf, flags) : -1;
}

int statx(int dirfd, const char *pathname, int flags, unsigned int mask, struct statx *statxbuf) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    static int (*orig)(int, const char *, int, unsigned int, struct statx *) = NULL;
    if (!orig) orig = (int (*)(int, const char *, int, unsigned int, struct statx *))dlsym(RTLD_NEXT, "statx");
    return orig ? orig(dirfd, pathname, flags, mask, statxbuf) : -1;
}

int statfs(const char *path, struct statfs *buf) {
    if (check_chrooted_proc(path)) return -1;
    static int (*orig)(const char *, struct statfs *) = NULL;
    if (!orig) orig = (int (*)(const char *, struct statfs *))dlsym(RTLD_NEXT, "statfs");
    return orig ? orig(path, buf) : -1;
}

int statfs64(const char *path, struct statfs64 *buf) {
    if (check_chrooted_proc(path)) return -1;
    static int (*orig)(const char *, struct statfs64 *) = NULL;
    if (!orig) orig = (int (*)(const char *, struct statfs64 *))dlsym(RTLD_NEXT, "statfs64");
    return orig ? orig(path, buf) : -1;
}

int statvfs(const char *path, struct statvfs *buf) {
    if (check_chrooted_proc(path)) return -1;
    static int (*orig)(const char *, struct statvfs *) = NULL;
    if (!orig) orig = (int (*)(const char *, struct statvfs *))dlsym(RTLD_NEXT, "statvfs");
    return orig ? orig(path, buf) : -1;
}

int statvfs64(const char *path, struct statvfs64 *buf) {
    if (check_chrooted_proc(path)) return -1;
    static int (*orig)(const char *, struct statvfs64 *) = NULL;
    if (!orig) orig = (int (*)(const char *, struct statvfs64 *))dlsym(RTLD_NEXT, "statvfs64");
    return orig ? orig(path, buf) : -1;
}

/* access / faccessat */
typedef int (*orig_access_t)(const char *pathname, int mode);
int access(const char *pathname, int mode) {
    if (check_chrooted_proc(pathname)) return -1;
    if (is_ns_path(pathname, "user") || is_ns_path(pathname, "pid") || is_map_path(pathname)) {
        return 0;
    }
    static orig_access_t orig_access = NULL;
    if (!orig_access) orig_access = (orig_access_t)dlsym(RTLD_NEXT, "access");
    return orig_access ? orig_access(pathname, mode) : 0;
}

typedef int (*orig_faccessat_t)(int dirfd, const char *pathname, int mode, int flags);
int faccessat(int dirfd, const char *pathname, int mode, int flags) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    if (is_ns_path(pathname, "user") || is_ns_path(pathname, "pid") || is_map_path(pathname)) {
        return 0;
    }
    static orig_faccessat_t orig_faccessat = NULL;
    if (!orig_faccessat) orig_faccessat = (orig_faccessat_t)dlsym(RTLD_NEXT, "faccessat");
    return orig_faccessat ? orig_faccessat(dirfd, pathname, mode, flags) : 0;
}

/* readlink / readlinkat */
typedef ssize_t (*orig_readlink_t)(const char *pathname, char *buf, size_t bufsiz);
ssize_t readlink(const char *pathname, char *buf, size_t bufsiz) {
    if (is_ns_path(pathname, "user")) {
        const char *val = "user:[4026531837]";
        size_t len = strlen(val);
        size_t copy_len = bufsiz < len ? bufsiz : len;
        memcpy(buf, val, copy_len);
        return copy_len;
    }
    if (is_ns_path(pathname, "pid")) {
        const char *val = "pid:[4026531836]";
        size_t len = strlen(val);
        size_t copy_len = bufsiz < len ? bufsiz : len;
        memcpy(buf, val, copy_len);
        return copy_len;
    }
    static orig_readlink_t orig_readlink = NULL;
    if (!orig_readlink) orig_readlink = (orig_readlink_t)dlsym(RTLD_NEXT, "readlink");
    return orig_readlink ? orig_readlink(pathname, buf, bufsiz) : -1;
}

/* open / openat / dir variants */
typedef int (*orig_open_t)(const char *pathname, int flags, ...);
int open(const char *pathname, int flags, ...) {
    if (check_chrooted_proc(pathname)) return -1;
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, mode_t);
        va_end(args);
    }
    if (is_ns_path(pathname, "user") || is_ns_path(pathname, "pid") || is_map_path(pathname)) {
        static orig_open_t o_open = NULL;
        if (!o_open) o_open = (orig_open_t)dlsym(RTLD_NEXT, "open");
        return o_open ? o_open("/dev/null", flags, mode) : -1;
    }
    static orig_open_t orig_open = NULL;
    if (!orig_open) orig_open = (orig_open_t)dlsym(RTLD_NEXT, "open");
    return orig_open ? orig_open(pathname, flags, mode) : -1;
}

int open64(const char *pathname, int flags, ...) {
    if (check_chrooted_proc(pathname)) return -1;
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, mode_t);
        va_end(args);
    }
    if (is_ns_path(pathname, "user") || is_ns_path(pathname, "pid") || is_map_path(pathname)) {
        static int (*o_open64)(const char *, int, ...) = NULL;
        if (!o_open64) o_open64 = (int (*)(const char *, int, ...))dlsym(RTLD_NEXT, "open64");
        return o_open64 ? o_open64("/dev/null", flags, mode) : -1;
    }
    static int (*orig_open64)(const char *, int, ...) = NULL;
    if (!orig_open64) orig_open64 = (int (*)(const char *, int, ...))dlsym(RTLD_NEXT, "open64");
    return orig_open64 ? orig_open64(pathname, flags, mode) : -1;
}

typedef int (*orig_openat_t)(int dirfd, const char *pathname, int flags, ...);
int openat(int dirfd, const char *pathname, int flags, ...) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, mode_t);
        va_end(args);
    }
    if (is_ns_path(pathname, "user") || is_ns_path(pathname, "pid") || is_map_path(pathname)) {
        static orig_openat_t o_openat = NULL;
        if (!o_openat) o_openat = (orig_openat_t)dlsym(RTLD_NEXT, "openat");
        return o_openat ? o_openat(AT_FDCWD, "/dev/null", flags, mode) : -1;
    }
    static orig_openat_t orig_openat = NULL;
    if (!orig_openat) orig_openat = (orig_openat_t)dlsym(RTLD_NEXT, "openat");
    return orig_openat ? orig_openat(dirfd, pathname, flags, mode) : -1;
}

int openat64(int dirfd, const char *pathname, int flags, ...) {
    if (dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) {
        if (check_chrooted_proc(pathname)) return -1;
    }
    mode_t mode = 0;
    if (flags & O_CREAT) {
        va_list args;
        va_start(args, flags);
        mode = va_arg(args, mode_t);
        va_end(args);
    }
    if (is_ns_path(pathname, "user") || is_ns_path(pathname, "pid") || is_map_path(pathname)) {
        static int (*o_openat64)(int, const char *, int, ...) = NULL;
        if (!o_openat64) o_openat64 = (int (*)(int, const char *, int, ...))dlsym(RTLD_NEXT, "openat64");
        return o_openat64 ? o_openat64(AT_FDCWD, "/dev/null", flags, mode) : -1;
    }
    static int (*orig_openat64)(int, const char *, int, ...) = NULL;
    if (!orig_openat64) orig_openat64 = (int (*)(int, const char *, int, ...))dlsym(RTLD_NEXT, "openat64");
    return orig_openat64 ? orig_openat64(dirfd, pathname, flags, mode) : -1;
}

DIR *opendir(const char *name) {
    if (check_chrooted_proc(name)) return NULL;
    static DIR *(*orig_opendir)(const char *) = NULL;
    if (!orig_opendir) orig_opendir = (DIR *(*)(const char *))dlsym(RTLD_NEXT, "opendir");
    return orig_opendir ? orig_opendir(name) : NULL;
}

int scandir(const char *dirp, struct dirent ***namelist,
            int (*filter)(const struct dirent *),
            int (*compar)(const struct dirent **, const struct dirent **)) {
    if (check_chrooted_proc(dirp)) return -1;
    static int (*orig)(const char *, struct dirent ***,
                       int (*)(const struct dirent *),
                       int (*)(const struct dirent **, const struct dirent **)) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "scandir");
    return orig ? orig(dirp, namelist, filter, compar) : -1;
}

int scandir64(const char *dirp, struct dirent64 ***namelist,
              int (*filter)(const struct dirent64 *),
              int (*compar)(const struct dirent64 **, const struct dirent64 **)) {
    if (check_chrooted_proc(dirp)) return -1;
    static int (*orig)(const char *, struct dirent64 ***,
                       int (*)(const struct dirent64 *),
                       int (*)(const struct dirent64 **, const struct dirent64 **)) = NULL;
    if (!orig) orig = dlsym(RTLD_NEXT, "scandir64");
    return orig ? orig(dirp, namelist, filter, compar) : -1;
}

/* syscall wrapper */
long syscall(long number, ...) {
    static long (*orig_syscall)(long number, ...) = NULL;
    if (!orig_syscall) orig_syscall = (long (*)(long, ...))dlsym(RTLD_NEXT, "syscall");

    va_list args;
    va_start(args, number);
    long a1 = va_arg(args, long);
    long a2 = va_arg(args, long);
    long a3 = va_arg(args, long);
    long a4 = va_arg(args, long);
    long a5 = va_arg(args, long);
    long a6 = va_arg(args, long);
    va_end(args);

    if (number == SYS_chroot) {
        shim_log("syscall(SYS_chroot) -> 0\n");
        is_chrooted = 1;
        return 0;
    }
    if (number == SYS_newfstatat && is_chrooted) {
        int dirfd = (int)a1;
        const char *pathname = (const char *)a2;
        if ((dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) && is_proc_path(pathname)) {
            shim_log("SYS_newfstatat(/proc) after chroot -> ENOENT\n");
            errno = ENOENT;
            return -1;
        }
    }
    if (number == SYS_statx && is_chrooted) {
        int dirfd = (int)a1;
        const char *pathname = (const char *)a2;
        if ((dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) && is_proc_path(pathname)) {
            shim_log("SYS_statx(/proc) after chroot -> ENOENT\n");
            errno = ENOENT;
            return -1;
        }
    }
    if ((number == SYS_openat || number == SYS_openat2) && is_chrooted) {
        int dirfd = (int)a1;
        const char *pathname = (const char *)a2;
        if ((dirfd == AT_FDCWD || (pathname && pathname[0] == '/')) && is_proc_path(pathname)) {
            shim_log("SYS_openat(/proc) after chroot -> ENOENT\n");
            errno = ENOENT;
            return -1;
        }
    }
    if (number == SYS_capset || number == SYS_capget) {
        shim_log("syscall(SYS_capset/capget) -> 0\n");
        return 0;
    }
    if (number == SYS_unshare) {
        char buf[128];
        snprintf(buf, sizeof(buf), "PID %d: syscall(SYS_unshare, 0x%lx)\n", getpid(), a1);
        shim_log(buf);
        long filtered = a1 & ~FORBIDDEN_CLONE_FLAGS;
        if (filtered == 0) return 0;
        return orig_syscall ? orig_syscall(SYS_unshare, filtered) : 0;
    }
    if (number == SYS_clone) {
        if ((a1 & FORBIDDEN_CLONE_FLAGS) == 0) {
            return orig_syscall ? orig_syscall(SYS_clone, a1, a2, a3, a4, a5) : -1;
        }
        char buf[128];
        snprintf(buf, sizeof(buf), "PID %d: syscall(SYS_clone, flags=0x%lx, stack=0x%lx)\n", getpid(), a1, a2);
        shim_log(buf);
        long filtered = a1 & ~FORBIDDEN_CLONE_FLAGS;
        long res = orig_syscall ? orig_syscall(SYS_clone, filtered, a2, a3, a4, a5) : -1;
        snprintf(buf, sizeof(buf), "PID %d: syscall(SYS_clone) result=%ld errno=%d\n", getpid(), res, errno);
        shim_log(buf);
        return res;
    }
    if (number == SYS_clone3) {
        shim_log("syscall(SYS_clone3)\n");
        uint64_t *cl = (uint64_t *)a1;
        if (cl) {
            cl[0] &= ~FORBIDDEN_CLONE_FLAGS;
        }
        return orig_syscall ? orig_syscall(SYS_clone3, a1, a2) : -1;
    }
    if (number == __NR_setns) {
        shim_log("syscall(SYS_setns) -> 0\n");
        return 0;
    }

    return orig_syscall ? orig_syscall(number, a1, a2, a3, a4, a5, a6) : -1;
}
