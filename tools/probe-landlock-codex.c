#define _GNU_SOURCE
#include <errno.h>
#include <dirent.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/audit.h>
#include <linux/close_range.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/openat2.h>
#include <linux/seccomp.h>
#include <poll.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* FIXED OFFLINE OFFICIAL CODEX EXPERIMENT: NOT a production sandbox.
 * Native parent applies Landlock + seccomp before exec of native PRoot. PRoot
 * and every descendant inherit them. Landlock allows reads/exec globally and
 * writes only in this invocation's private scratch directory. Workspace writes
 * require a broker-passed FD. All evidence and permitted scratch mutations stay
 * in our mkdtemp tree. This does NOT implement confidentiality or Codex policy.
 *
 * PROOT_NO_SECCOMP=1 disables PRoot's optional RET_TRACE optimization only, not
 * our native filter or Android's filter. PRoot then uses PTRACE_SYSCALL entry
 * stops to translate paths before native USER_NOTIF. USER_NOTIF outranks TRACE;
 * without entry stops an accelerated open could notify before translation.
 * We accept ONLY absolute HOST paths below our fixed workspace/scratch FDs.
 * Guest paths, relative paths, metadata components, symlinks and escapes fail.
 * The notification listener is installed only in the child, then inherited:
 * its kernel notifications are provenance for this invocation's descendants.
 * We do not infer ownership from mutable /proc ancestry or accept another
 * listener. Each request uses one process_vm_readv copy, immutable arguments,
 * ID_VALID immediately before openat2, and ADDFD_FLAG_SEND. Never CONTINUE.
 *
 * PRoot needs fork, ptrace, process_vm_*, signals, waits, cwd changes, scratch
 * mkdir/unlink/rename and fd operations in addition to the loader allowlist.
 * Landlock confines its mutation syscalls, and its domain prevents tracing the
 * unrestricted parent; the latter is independently checked before exec.
 * Unknown syscalls are reported by number and fail EPERM. Anonymous AF_UNIX
 * stream pairs serve local signal handling; socket/connect/bind and network,
 * unshare, setns or mount syscalls remain denied. Clone/clone3
 * descendants inherit the real native restrictions. PRoot is NOT isolation.
 *
 * Fixed fixture command only, no user command input, model requests or account
 * profile use. Reads remain global: this is not a confidentiality boundary.
 * /etc/ld.so.preload is bound to /dev/null without changing rootfs files.
 * Parent-owned directory/listener FDs are closed before exec. Stdin is empty;
 * inherited stdout/stderr are retained for reporting only. Write access via
 * granted FDs lasts for their lifetime. Creation/truncation is not transactional
 * with ADDFD if a notification is cancelled after ID_VALID. No rollback.
 * Android usage: probe APP_DATA_DIR APK_NATIVE_DIR
 * Native Linux test usage: probe PRIVATE_PARENT_DIR PROOT_EXECUTABLE ROOTFS
 * Requires Landlock ABI >= 6, openat2, close_range(CLOEXEC), ADDFD_FLAG_SEND.
 */

#if defined(__aarch64__)
#define PROBE_AUDIT_ARCH AUDIT_ARCH_AARCH64
#elif defined(__x86_64__)
#define PROBE_AUDIT_ARCH AUDIT_ARCH_X86_64
#else
#error "This bounded probe supports aarch64 and x86_64 only"
#endif

#define PROBE_TIMEOUT_SECONDS 90
#include "probe-codex-offline.generated.h"
#ifndef LANDLOCK_ACCESS_FS_IOCTL_DEV
#define LANDLOCK_ACCESS_FS_IOCTL_DEV (1ULL << 15)
#endif
#ifndef LANDLOCK_SCOPE_SIGNAL
#define LANDLOCK_SCOPE_SIGNAL (1ULL << 1)
#endif
/* Exact Linux ABI 6 ruleset layout, also buildable with older userspace headers. */
struct probe_landlock_ruleset { uint64_t handled_access_fs, handled_access_net, scoped; };
static char workspace_path[PATH_MAX], scratch_path[PATH_MAX], outside_path[PATH_MAX];
static char proot_path[PATH_MAX], rootfs_path[PATH_MAX], library_path[PATH_MAX * 2];
static char loader_path[PATH_MAX], loader32_path[PATH_MAX];
static int scratch_directory;
static unsigned int scratch_grants, descendant_workspace_grants;
static unsigned int scratch_mode_changes;
static unsigned int null_device_grants;
static unsigned int unsupported_denials;
static unsigned char reported_syscalls[2048];
static int reported_negative_syscall;
static const char marker[] = "FoldGPT native shell write\n";
static const char appended_marker[] = "FoldGPT native shell write\nFoldGPT appended\n";
static const char protected_marker[] = "Protected metadata remains intact\n";
static const char outside_marker[] = "Outside file remains intact\n";
static unsigned int broker_grants;
static unsigned int broker_denials;

static void fail(const char *message) {
    fprintf(stderr, "%s: %s\n", message, strerror(errno));
    exit(1);
}

static void require(int condition, const char *message) {
    if (!condition) fail(message);
}

static struct timespec deadline_after_seconds(unsigned int seconds) {
    struct timespec deadline;
    require(clock_gettime(CLOCK_MONOTONIC, &deadline) == 0, "read monotonic deadline clock");
    deadline.tv_sec += seconds;
    return deadline;
}

static int milliseconds_until(const struct timespec *deadline) {
    struct timespec now;
    require(clock_gettime(CLOCK_MONOTONIC, &now) == 0, "read monotonic remaining time");
    int64_t remaining = ((int64_t)deadline->tv_sec - now.tv_sec) * 1000000000LL
                      + deadline->tv_nsec - now.tv_nsec;
    if (remaining <= 0) return 0;
    // Round up so poll cannot expire before the absolute deadline.
    int64_t milliseconds = (remaining + 999999) / 1000000;
    return milliseconds > INT_MAX ? INT_MAX : (int)milliseconds;
}

static int write_all(int fd, const void *data, size_t size) {
    const unsigned char *cursor = data;
    while (size) {
        ssize_t written = write(fd, cursor, size);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) return -1;
        cursor += written;
        size -= (size_t)written;
    }
    return 0;
}

static void make_file(int directory, const char *path, const char *content) {
    int fd = openat(directory, path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    require(fd >= 0, "create own test fixture");
    require(write_all(fd, content, strlen(content)) == 0, "write own test fixture");
    require(close(fd) == 0, "close test fixture");
}

static void verify_file(int directory, const char *path, const char *expected) {
    char data[128];
    int fd = openat(directory, path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    require(fd >= 0, "open parent verification fixture");
    ssize_t size = read(fd, data, sizeof(data));
    require(size == (ssize_t)strlen(expected) && memcmp(data, expected, (size_t)size) == 0,
            "independent fixture content verification");
    require(close(fd) == 0, "close verification fixture");
}

static void verify_absent(int directory, const char *path) {
    struct stat stat_buffer;
    errno = 0;
    require(fstatat(directory, path, &stat_buffer, AT_SYMLINK_NOFOLLOW) < 0 && errno == ENOENT,
            "forbidden test path must remain absent");
}

static int send_fd(int socket_fd, int fd) {
    char payload = 'L';
    union { struct cmsghdr alignment; char bytes[CMSG_SPACE(sizeof(int))]; } control;
    memset(&control, 0, sizeof(control));
    struct iovec vector = {.iov_base = &payload, .iov_len = 1};
    struct msghdr message = {.msg_iov = &vector, .msg_iovlen = 1,
                            .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes)};
    struct cmsghdr *header = CMSG_FIRSTHDR(&message);
    header->cmsg_level = SOL_SOCKET;
    header->cmsg_type = SCM_RIGHTS;
    header->cmsg_len = CMSG_LEN(sizeof(int));
    memcpy(CMSG_DATA(header), &fd, sizeof(fd));
    // Transfer the listener before invoking platform networking wrappers.
    // Android's libc wrapper can initialize netd support via openat, which
    // would wait on the listener that the parent has not received yet.
    return syscall(SYS_sendmsg, socket_fd, &message, MSG_NOSIGNAL) == 1 ? 0 : -1;
}

static int receive_fd(int socket_fd, const struct timespec *deadline) {
    char payload;
    union { struct cmsghdr alignment; char bytes[CMSG_SPACE(sizeof(int))]; } control;
    memset(&control, 0, sizeof(control));
    struct iovec vector = {.iov_base = &payload, .iov_len = 1};
    struct msghdr message = {.msg_iov = &vector, .msg_iovlen = 1,
                            .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes)};
    ssize_t received;
    for (;;) {
        int remaining = milliseconds_until(deadline);
        if (!remaining) { errno = ETIMEDOUT; return -1; }
        struct pollfd event = {.fd = socket_fd, .events = POLLIN};
        int ready = poll(&event, 1, remaining);
        if (ready < 0) {
            if (errno == EINTR) continue;
            return -1;
        }
        if (!ready) continue;
        if (event.revents & POLLNVAL) { errno = EBADF; return -1; }
        message.msg_controllen = sizeof(control.bytes);
        message.msg_flags = 0;
        // Never block between readiness notification and receipt. A signal or
        // transient readiness change must not restart the absolute deadline.
        received = recvmsg(socket_fd, &message, MSG_CMSG_CLOEXEC | MSG_DONTWAIT);
        if (received < 0) {
            if (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK) continue;
            return -1;
        }
        break;
    }
    if (received != 1 || payload != 'L' || (message.msg_flags & (MSG_CTRUNC | MSG_TRUNC))) {
        errno = EPROTO;
        return -1;
    }
    struct cmsghdr *header = CMSG_FIRSTHDR(&message);
    if (!header || header->cmsg_level != SOL_SOCKET || header->cmsg_type != SCM_RIGHTS
            || header->cmsg_len != CMSG_LEN(sizeof(int))) {
        errno = EPROTO;
        return -1;
    }
    int fd;
    memcpy(&fd, CMSG_DATA(header), sizeof(fd));
    return fd;
}

static void landlock_read_only(void) {
    const uint64_t reads = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE
                         | LANDLOCK_ACCESS_FS_READ_DIR;
    const uint64_t writes = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR
        | LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR
        | LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG
        | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO
        | LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM
        | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_IOCTL_DEV;
    struct probe_landlock_ruleset attributes = {
        .handled_access_fs = reads | writes, .scoped = LANDLOCK_SCOPE_SIGNAL};
    int ruleset = (int)syscall(SYS_landlock_create_ruleset, &attributes, sizeof(attributes), 0);
    require(ruleset >= 0, "create read-only Landlock ruleset");
    int root = open("/", O_PATH | O_DIRECTORY | O_CLOEXEC);
    require(root >= 0, "open Landlock read root");
    struct landlock_path_beneath_attr rule = {.allowed_access = reads, .parent_fd = root};
    require(syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) == 0,
            "allow read-only filesystem");
    int scratch = open(scratch_path, O_PATH | O_DIRECTORY | O_CLOEXEC);
    require(scratch >= 0, "open own scratch grant");
    struct landlock_path_beneath_attr scratch_rule = {
        .allowed_access = reads | writes, .parent_fd = scratch};
    require(syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH,
                    &scratch_rule, 0) == 0, "allow own scratch mutations");
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "set no_new_privs");
    require(syscall(SYS_landlock_restrict_self, ruleset, 0) == 0, "enforce Landlock");
    close(root);
    close(scratch);
    close(ruleset);
}

#define ALLOW_SYSCALL(number) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (number), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)

static int notification_filter(void) {
    /* Read-only opens stay kernel-enforced; writing opens must reach the broker.
     * No notification is ever continued against mutable tracee arguments. */
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, PROBE_AUDIT_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Standard descriptor queries and nonblocking mode used by Rust pipes.
         * FIONBIO changes only an existing FD's mode, like allowed fcntl;
         * all device-specific ioctls still go to a refusal, never CONTINUE. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_ioctl, 0, 11),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        ALLOW_SYSCALL(TCGETS),
        ALLOW_SYSCALL(FIONREAD),
        ALLOW_SYSCALL(FIONBIO),
        ALLOW_SYSCALL(TIOCGWINSZ),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Tokio's signal self-pipe is an unnamed Unix socket pair. It cannot
         * connect to a host service; socket/connect/bind remain refused. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_socketpair, 0, 9),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_UNIX, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K, ~(SOCK_CLOEXEC | SOCK_NONBLOCK)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SOCK_STREAM, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Only the calling process's limits; never another PID's limits. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_prlimit64, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_fchmodat, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
#ifdef SYS_chmod
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_chmod, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
#endif
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_openat, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K,
                 O_ACCMODE | O_CREAT | O_TRUNC | O_APPEND | (O_TMPFILE & ~O_DIRECTORY)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#ifdef SYS_open
        /* The x86 PRoot loader uses raw open(O_RDONLY). Writable legacy open
         * remains denied; this experiment brokers openat only. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_open, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K,
                 O_ACCMODE | O_CREAT | O_TRUNC | O_APPEND | (O_TMPFILE & ~O_DIRECTORY)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#endif
        ALLOW_SYSCALL(SYS_read),
        ALLOW_SYSCALL(SYS_pread64),
        /* SQLite positional writes use the same actually granted descriptors
         * as write(); no new path or writable capability is introduced. */
        ALLOW_SYSCALL(SYS_pwrite64),
        ALLOW_SYSCALL(SYS_write),
        ALLOW_SYSCALL(SYS_writev),
        ALLOW_SYSCALL(SYS_close),
        ALLOW_SYSCALL(SYS_sendmsg),
        ALLOW_SYSCALL(SYS_recvfrom),
        ALLOW_SYSCALL(SYS_execve),
        ALLOW_SYSCALL(SYS_exit),
        ALLOW_SYSCALL(SYS_exit_group),
        ALLOW_SYSCALL(SYS_rt_sigaction),
        ALLOW_SYSCALL(SYS_rt_sigreturn),
        ALLOW_SYSCALL(SYS_rt_sigprocmask),
        ALLOW_SYSCALL(SYS_sigaltstack),
        ALLOW_SYSCALL(SYS_futex),
        ALLOW_SYSCALL(SYS_mmap),
        ALLOW_SYSCALL(SYS_munmap),
        ALLOW_SYSCALL(SYS_mprotect),
        ALLOW_SYSCALL(SYS_brk),
        ALLOW_SYSCALL(SYS_madvise),
        ALLOW_SYSCALL(SYS_mremap),
        ALLOW_SYSCALL(SYS_getuid),
        ALLOW_SYSCALL(SYS_geteuid),
        ALLOW_SYSCALL(SYS_getgid),
        ALLOW_SYSCALL(SYS_getegid),
        ALLOW_SYSCALL(SYS_getpid),
        ALLOW_SYSCALL(SYS_getppid),
        ALLOW_SYSCALL(SYS_gettid),
        ALLOW_SYSCALL(SYS_getpgid),
        ALLOW_SYSCALL(SYS_getcwd),
        ALLOW_SYSCALL(SYS_uname),
        ALLOW_SYSCALL(SYS_clock_gettime),
        ALLOW_SYSCALL(SYS_gettimeofday),
        ALLOW_SYSCALL(SYS_getrandom),
        ALLOW_SYSCALL(SYS_set_tid_address),
        ALLOW_SYSCALL(SYS_set_robust_list),
        ALLOW_SYSCALL(SYS_prctl),
        ALLOW_SYSCALL(SYS_fstat),
        ALLOW_SYSCALL(SYS_fstatfs),
        ALLOW_SYSCALL(SYS_sched_getscheduler),
        ALLOW_SYSCALL(SYS_sched_getparam),
        ALLOW_SYSCALL(SYS_newfstatat),
        ALLOW_SYSCALL(SYS_statx),
        ALLOW_SYSCALL(SYS_faccessat),
        ALLOW_SYSCALL(SYS_faccessat2),
        ALLOW_SYSCALL(SYS_readlinkat),
        ALLOW_SYSCALL(SYS_getdents64),
        ALLOW_SYSCALL(SYS_lseek),
        ALLOW_SYSCALL(SYS_dup),
        ALLOW_SYSCALL(SYS_dup3),
        ALLOW_SYSCALL(SYS_fcntl),
        /* PRoot tracer and descendants. Landlock prevents access to our parent;
         * mutation rights below cover only the private scratch grant. */
        ALLOW_SYSCALL(SYS_clone),
#ifdef SYS_clone3
        ALLOW_SYSCALL(SYS_clone3),
#endif
        ALLOW_SYSCALL(SYS_setsid),
        ALLOW_SYSCALL(SYS_setpgid),
        ALLOW_SYSCALL(SYS_readv),
        ALLOW_SYSCALL(SYS_fsync),
        ALLOW_SYSCALL(SYS_fdatasync),
        ALLOW_SYSCALL(SYS_epoll_create1),
        ALLOW_SYSCALL(SYS_epoll_ctl),
        ALLOW_SYSCALL(SYS_epoll_pwait),
        ALLOW_SYSCALL(SYS_eventfd2),
        ALLOW_SYSCALL(SYS_ppoll),
        ALLOW_SYSCALL(SYS_pselect6),
        ALLOW_SYSCALL(SYS_clock_nanosleep),
        ALLOW_SYSCALL(SYS_nanosleep),
        ALLOW_SYSCALL(SYS_restart_syscall),
        ALLOW_SYSCALL(SYS_capget),
        ALLOW_SYSCALL(SYS_sched_yield),
        ALLOW_SYSCALL(SYS_sched_getaffinity),
        ALLOW_SYSCALL(SYS_getrusage),
        ALLOW_SYSCALL(SYS_sysinfo),
        ALLOW_SYSCALL(SYS_statfs),
        ALLOW_SYSCALL(SYS_flock),
        ALLOW_SYSCALL(SYS_getresuid),
        ALLOW_SYSCALL(SYS_getresgid),
        ALLOW_SYSCALL(SYS_close_range),
#ifdef SYS_epoll_wait
        ALLOW_SYSCALL(SYS_epoll_wait),
#endif
#ifdef SYS_poll
        ALLOW_SYSCALL(SYS_poll),
#endif
#ifdef SYS_select
        ALLOW_SYSCALL(SYS_select),
#endif
        ALLOW_SYSCALL(SYS_ptrace),
        ALLOW_SYSCALL(SYS_process_vm_readv),
        ALLOW_SYSCALL(SYS_process_vm_writev),
        ALLOW_SYSCALL(SYS_wait4),
        ALLOW_SYSCALL(SYS_waitid),
        ALLOW_SYSCALL(SYS_kill),
        ALLOW_SYSCALL(SYS_tgkill),
        ALLOW_SYSCALL(SYS_rt_sigsuspend),
        ALLOW_SYSCALL(SYS_setitimer),
        ALLOW_SYSCALL(SYS_chdir),
        ALLOW_SYSCALL(SYS_fchdir),
        ALLOW_SYSCALL(SYS_pipe2),
        ALLOW_SYSCALL(SYS_umask),
        ALLOW_SYSCALL(SYS_ftruncate),
        ALLOW_SYSCALL(SYS_unlinkat),
        ALLOW_SYSCALL(SYS_mkdirat),
        ALLOW_SYSCALL(SYS_renameat),
        ALLOW_SYSCALL(SYS_renameat2),
        ALLOW_SYSCALL(SYS_linkat),
        ALLOW_SYSCALL(SYS_symlinkat),
#ifdef SYS_fork
        ALLOW_SYSCALL(SYS_fork),
#endif
#ifdef SYS_vfork
        ALLOW_SYSCALL(SYS_vfork),
#endif
#ifdef SYS_unlink
        ALLOW_SYSCALL(SYS_unlink),
#endif
#ifdef SYS_rmdir
        ALLOW_SYSCALL(SYS_rmdir),
#endif
#ifdef SYS_mkdir
        ALLOW_SYSCALL(SYS_mkdir),
#endif
#ifdef SYS_rename
        ALLOW_SYSCALL(SYS_rename),
#endif
#ifdef SYS_link
        ALLOW_SYSCALL(SYS_link),
#endif
#ifdef SYS_symlink
        ALLOW_SYSCALL(SYS_symlink),
#endif
#ifdef SYS_alarm
        ALLOW_SYSCALL(SYS_alarm),
#endif
#ifdef SYS_dup2
        ALLOW_SYSCALL(SYS_dup2),
#endif
#ifdef SYS_getpgrp
        ALLOW_SYSCALL(SYS_getpgrp),
#endif
#ifdef SYS_getrlimit
        ALLOW_SYSCALL(SYS_getrlimit),
#endif
#ifdef SYS_access
        ALLOW_SYSCALL(SYS_access),
#endif
#ifdef SYS_readlink
        ALLOW_SYSCALL(SYS_readlink),
#endif
#ifdef SYS_arch_prctl
        ALLOW_SYSCALL(SYS_arch_prctl),
#endif
#ifdef SYS_rseq
        ALLOW_SYSCALL(SYS_rseq),
#endif
        /* Report unsupported syscall numbers and actually refuse them. */
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
    };
    struct sock_fprog program = {.len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
                                .filter = filter};
    return (int)syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                       SECCOMP_FILTER_FLAG_NEW_LISTENER, &program);
}

static void worker_check(const char *name, int okay, int observed_errno) {
    char output[256];
    int size = snprintf(output, sizeof(output), "worker %s=%s errno=%d\n", name,
                        okay ? "PASS" : "FAIL", observed_errno);
    if (size < 0 || size >= (int)sizeof(output)
            || write_all(STDOUT_FILENO, output, (size_t)size) < 0) _exit(1);
    if (!okay) _exit(1);
}

static void child_probe(int channel, int workspace, int base, int outside, pid_t owner) {
    /* PRoot handles SIGQUIT by killing all its tracees. If the diagnostic
     * supervisor disappears (for example ADB disconnect), ask the kernel to
     * deliver that signal, including when commands have detached sessions.
     * Check parent identity after installing it to close the fork/death race. */
    require(prctl(PR_SET_PDEATHSIG, SIGQUIT, 0, 0, 0) == 0 && getppid() == owner,
            "bind native tracer lifetime to this probe supervisor");
    require(setpgid(0, 0) == 0, "set own bounded process group");
    require(syscall(SYS_close_range, 3u, ~0u, CLOSE_RANGE_CLOEXEC) == 0,
            "prevent inherited descriptor access after exec");
    int null_input = open("/dev/null", O_RDONLY | O_CLOEXEC);
    require(null_input >= 0, "open fixed empty stdin");
    if (null_input != STDIN_FILENO) {
        require(dup2(null_input, STDIN_FILENO) == STDIN_FILENO, "set fixed empty stdin");
        close(null_input);
    } else {
        require(fcntl(STDIN_FILENO, F_SETFD, 0) == 0, "retain fixed empty stdin");
    }
    require(fchdir(workspace) == 0, "set test child workspace");
    close(workspace);
    close(base);
    close(outside);
    close(scratch_directory);
    char scratch_bind[PATH_MAX + 32], workspace_bind[PATH_MAX + 32], outside_bind[PATH_MAX + 32];
    snprintf(scratch_bind, sizeof(scratch_bind), "%s:/tmp", scratch_path);
    snprintf(workspace_bind, sizeof(workspace_bind), "%s:/foldgpt-fixture", workspace_path);
    snprintf(outside_bind, sizeof(outside_bind), "%s:/outside", outside_path);
    require(clearenv() == 0 && setenv("LD_LIBRARY_PATH", library_path, 1) == 0
            && setenv("PROOT_TMP_DIR", scratch_path, 1) == 0
            && setenv("PROOT_NO_SECCOMP", "1", 1) == 0, "set fixed PRoot environment");
    require(setenv("PROOT_LOADER", loader_path, 1) == 0
            && setenv("PROOT_LOADER_32", loader32_path, 1) == 0, "set existing native loaders");
    /* process_vm_readv uses ptrace access checks. The only attempted read is a
     * fixed public marker at the parent's same pre-fork address, never secrets.
     * Report the baseline: Yama/SELinux may already block this before Landlock. */
    char parent_marker[sizeof(marker)] = {0};
    struct iovec local = {.iov_base = parent_marker, .iov_len = sizeof(parent_marker)};
    struct iovec remote = {.iov_base = (void *)marker, .iov_len = sizeof(marker)};
    errno = 0;
    ssize_t baseline_read = syscall(SYS_process_vm_readv, getppid(), &local, 1, &remote, 1, 0);
    printf("worker parent_ptrace_baseline_read=%s errno=%d\n",
           baseline_read == (ssize_t)sizeof(marker) ? "ALLOWED" : "DENIED", errno);
    landlock_read_only();
    errno = 0;
    ssize_t parent_read = syscall(SYS_process_vm_readv, getppid(), &local, 1, &remote, 1, 0);
    worker_check("parent_ptrace_access_denied", parent_read < 0 && errno == EPERM, errno);

    struct open_how direct = {.flags = O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC,
                              .mode = 0600,
                              .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV};
    errno = 0;
    int denied = (int)syscall(SYS_openat2, AT_FDCWD, "unbrokered.txt", &direct, sizeof(direct));
    int denied_errno = errno;
    if (denied >= 0) close(denied);
    worker_check("landlock_direct_write_denied", denied < 0 && denied_errno == EACCES, denied_errno);

    int listener = notification_filter();
    worker_check("notification_filter_installed", listener >= 0, listener < 0 ? errno : 0);
    int transferred = send_fd(channel, listener);
    worker_check("notification_listener_sent", transferred == 0, transferred < 0 ? errno : 0);
    close(listener);
    close(channel);

    char protected_mode_path[PATH_MAX];
    int mode_path_length = snprintf(protected_mode_path, sizeof(protected_mode_path),
                                    "%s/.git/config", workspace_path);
    if (mode_path_length < 0 || mode_path_length >= (int)sizeof(protected_mode_path)) _exit(1);
    errno = 0;
    int mode_result = syscall(SYS_fchmodat, AT_FDCWD, protected_mode_path, 0777);
    worker_check("workspace_chmod_denied", mode_result < 0 && errno == EPERM, errno);
    mode_path_length = snprintf(protected_mode_path, sizeof(protected_mode_path),
                                "%s/victim.txt", outside_path);
    if (mode_path_length < 0 || mode_path_length >= (int)sizeof(protected_mode_path)) _exit(1);
    errno = 0;
    mode_result = syscall(SYS_fchmodat, AT_FDCWD, protected_mode_path, 0777);
    worker_check("outside_chmod_denied", mode_result < 0 && errno == EPERM, errno);

    errno = 0;
    denied = (int)syscall(SYS_openat2, AT_FDCWD, "unbrokered.txt", &direct, sizeof(direct));
    denied_errno = errno;
    if (denied >= 0) close(denied);
    worker_check("direct_openat2_filtered", denied < 0 && denied_errno == EPERM, denied_errno);
    execl(proot_path, proot_path,
#ifdef __ANDROID__
          "--kill-on-exit",
#endif
          "-r", rootfs_path, "-w", "/foldgpt-fixture", "-b", "/dev", "-b", "/proc",
#ifdef __ANDROID__
          "-b", "/system", "-b", "/apex",
#endif
          "-b", scratch_bind, "-b", workspace_bind, "-b", outside_bind,
          "-b", "/dev/null:/etc/ld.so.preload", "/usr/bin/env", "-i",
          "PATH=/usr/bin:/bin", "HOME=/tmp/home", "CODEX_HOME=/tmp/codexhome",
          "LC_ALL=C", "TMPDIR=/tmp/run", "FOLDGPT_NATIVE_OFFLINE_PROBE=1",
          "/usr/bin/python3", "-I", "-B", "-c", codex_offline_script, (char *)NULL);
    worker_check("native_proot_execve", 0, errno);
    _exit(1);
}

static int valid_relative_path(const char *path) {
    if (!path[0] || path[0] == '/') return 0;
    const char *component = path;
    for (;;) {
        const char *slash = strchr(component, '/');
        size_t length = slash ? (size_t)(slash - component) : strlen(component);
        if (!length || (length == 1 && component[0] == '.')
                || (length == 2 && memcmp(component, "..", 2) == 0)
                || (length == 4 && memcmp(component, ".git", 4) == 0)
                || (length == 6 && memcmp(component, ".codex", 6) == 0)
                || (length == 7 && memcmp(component, ".agents", 7) == 0)) return 0;
        if (!slash) return 1;
        component = slash + 1;
    }
}

static int copy_request_path(pid_t pid, uint64_t pointer, char path[PATH_MAX]) {
    struct iovec local = {.iov_base = path, .iov_len = PATH_MAX};
    struct iovec remote = {.iov_base = (void *)(uintptr_t)pointer, .iov_len = PATH_MAX};
    ssize_t count = process_vm_readv(pid, &local, 1, &remote, 1, 0);
    if (count <= 0) return EFAULT;
    if (!memchr(path, '\0', (size_t)count)) return ENAMETOOLONG;
    return 0;
}

static int notification_valid(int listener, uint64_t id) {
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_ID_VALID, &id) == 0) return 1;
    if (errno == ENOENT) return 0;
    fail("validate notification ID");
    return 0;
}

static const char *below_root(const char *path, const char *root) {
    size_t root_length = strlen(root);
    if (strncmp(path, root, root_length) || path[root_length] != '/') return NULL;
    return path + root_length + 1;
}

static void deny_request(int listener, uint64_t id, int error) {
    struct seccomp_notif_resp response = {.id = id, .val = 0, .error = -error, .flags = 0};
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 && errno != ENOENT) {
        fail("return broker denial");
    }
    ++broker_denials;
}

static void scratch_chmod(int listener, const struct seccomp_notif *request) {
    int path_arg = 1;
#ifdef SYS_chmod
    if (request->data.nr == SYS_chmod) path_arg = 0;
#endif
    uint64_t mode = request->data.args[path_arg + 1];
    char path[PATH_MAX];
    if (!notification_valid(listener, request->id)) return;
    int error = copy_request_path(request->pid, request->data.args[path_arg], path);
    const char *relative = error ? NULL : below_root(path, scratch_path);
    if (error || !relative || !valid_relative_path(relative) || (mode & ~0777ULL)) {
        deny_request(listener, request->id, error ? error : EPERM);
        return;
    }
    // Landlock does not mediate chmod. Perform only this validated scratch
    // operation ourselves; never permit the child's arbitrary chmod syscall.
    struct open_how how = {.flags = O_RDONLY | O_CLOEXEC | O_NONBLOCK,
                          .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV};
    int fd = syscall(SYS_openat2, scratch_directory, relative, &how, sizeof(how));
    if (fd < 0) { deny_request(listener, request->id, errno); return; }
    struct stat value;
    if (fstat(fd, &value) < 0 || !(S_ISREG(value.st_mode) || S_ISDIR(value.st_mode))) {
        close(fd);
        deny_request(listener, request->id, EPERM);
        return;
    }
    if (!notification_valid(listener, request->id)) { close(fd); return; }
    int result = fchmod(fd, (mode_t)mode);
    error = result < 0 ? errno : 0;
    close(fd);
    struct seccomp_notif_resp response = {.id = request->id, .val = 0, .error = -error};
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 && errno != ENOENT)
        fail("return bounded scratch chmod result");
    if (!error) ++scratch_mode_changes;
    else ++broker_denials;
}

static void handle_notification(int listener, int workspace, pid_t child,
                                const struct seccomp_notif *request) {
    /* Copy scalar arguments from the received kernel snapshot, never from
     * tracee memory. The only tracee-memory read copies the path below. */
    const uint64_t id = request->id;
    const pid_t requester = (pid_t)request->pid;
    const uint64_t pathname = request->data.args[1];
    const uint64_t flags = request->data.args[2];
    const uint64_t mode = (flags & O_CREAT) ? request->data.args[3] : 0;
    const uint64_t allowed_flags = O_WRONLY | O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC
                                 | O_TRUNC | O_APPEND | O_NOFOLLOW | O_NOCTTY | O_LARGEFILE;
    /* Only the original child inherited this listener/filter. Kernel-provided
     * TIDs include PRoot's descendants, not merely the native tracer PID. */
    if (requester <= 0 || requester == getpid() || request->data.arch != PROBE_AUDIT_ARCH
            || request->flags != 0) {
        deny_request(listener, id, EPERM);
        return;
    }
    if (request->data.nr == SYS_fchmodat
#ifdef SYS_chmod
            || request->data.nr == SYS_chmod
#endif
    ) {
        scratch_chmod(listener, request);
        return;
    }
    if (request->data.nr != SYS_openat) {
        int number = request->data.nr;
        if ((number < 0 && !reported_negative_syscall)
                || (number >= 0 && number < (int)sizeof(reported_syscalls)
                    && !reported_syscalls[number]))
            fprintf(stderr, "unsupported_syscall_denied=%d\n", request->data.nr);
        if (number < 0) reported_negative_syscall = 1;
        else if (number < (int)sizeof(reported_syscalls)) reported_syscalls[number] = 1;
        ++unsupported_denials;
        deny_request(listener, id, EPERM);
        return;
    }
    if ((flags & ~allowed_flags)
            || ((flags & O_ACCMODE) != O_WRONLY && (flags & O_ACCMODE) != O_RDWR)
            || ((flags & O_EXCL) && !(flags & O_CREAT))
            || (mode & ~0777ULL)) {
        deny_request(listener, id, EOPNOTSUPP);
        return;
    }
    char path[PATH_MAX];
    if (!notification_valid(listener, id)) return;
    int error = copy_request_path(requester, pathname, path);
    if (error) {
        deny_request(listener, id, error);
        return;
    }
    /* Python and Codex use /dev/null with O_RDWR for subprocess plumbing.
     * Grant an actual FD to only this verified kernel null device, never a
     * general writable /dev rule and never a synthetic successful open. */
    if (!strcmp(path, "/dev/null") && !(flags & ~(O_RDWR | O_WRONLY | O_CLOEXEC | O_LARGEFILE))) {
        int null_fd = open("/dev/null", (int)flags | O_CLOEXEC | O_NOFOLLOW);
        struct stat null_stat;
        if (null_fd < 0 || fstat(null_fd, &null_stat) < 0 || !S_ISCHR(null_stat.st_mode)
                || major(null_stat.st_rdev) != 1 || minor(null_stat.st_rdev) != 3) {
            if (null_fd >= 0) close(null_fd);
            deny_request(listener, id, EPERM);
            return;
        }
        if (!notification_valid(listener, id)) { close(null_fd); return; }
        struct seccomp_notif_addfd transfer = {
            .id = id, .flags = SECCOMP_ADDFD_FLAG_SEND, .srcfd = (uint32_t)null_fd,
            .newfd_flags = (uint32_t)(flags & O_CLOEXEC)};
        int installed = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &transfer);
        int saved = errno;
        close(null_fd);
        if (installed >= 0) ++null_device_grants;
        else if (saved != ENOENT) deny_request(listener, id, saved);
        return;
    }
    const char *relative = below_root(path, workspace_path);
    int directory = workspace;
    int is_scratch = 0;
    if (!relative) {
        relative = below_root(path, scratch_path);
        directory = scratch_directory;
        is_scratch = 1;
    }
    if (!relative || !valid_relative_path(relative)) {
        deny_request(listener, id, error ? error : EPERM);
        return;
    }
    struct open_how how = {.flags = flags | O_CLOEXEC, .mode = mode,
                          .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV};
    /* Validate again immediately before opening/creating. openat2 resolves our
     * private copy, using a fixed directory FD; the child cannot rewrite either. */
    if (!notification_valid(listener, id)) return;
    int source = (int)syscall(SYS_openat2, directory, relative, &how, sizeof(how));
    if (source < 0) {
        deny_request(listener, id, errno);
        return;
    }
    struct seccomp_notif_addfd add = {.id = id, .flags = SECCOMP_ADDFD_FLAG_SEND,
                                     .srcfd = (uint32_t)source, .newfd = 0,
                                     .newfd_flags = (uint32_t)(flags & O_CLOEXEC)};
    int installed = ioctl(listener, SECCOMP_IOCTL_NOTIF_ADDFD, &add);
    int saved = errno;
    close(source);
    if (installed < 0) {
        if (saved == ENOENT) return;
        /* No fallback to CONTINUE or an unvalidated direct open. */
        fprintf(stderr, "atomic notification FD transfer failed: %s\n", strerror(saved));
        deny_request(listener, id, saved);
        return;
    }
    if (is_scratch) ++scratch_grants;
    else {
        ++broker_grants;
        if (requester != child) ++descendant_workspace_grants;
    }
}

static int broker_loop(int listener, int workspace, pid_t child,
                       const struct timespec *deadline) {
    struct seccomp_notif_sizes sizes;
    require(syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sizes) == 0,
            "read seccomp notification sizes");
    require(sizes.seccomp_notif >= sizeof(struct seccomp_notif), "notification ABI size");
    struct seccomp_notif *request = calloc(1, sizes.seccomp_notif);
    require(request != NULL, "allocate notification");
    int status = 0;
    for (;;) {
        pid_t waited = waitpid(child, &status, WNOHANG);
        if (waited == child) break;
        if (waited < 0 && errno != EINTR) fail("wait for probe worker");
        int remaining = milliseconds_until(deadline);
        if (!remaining) {
            kill(-child, SIGKILL);
            kill(child, SIGKILL);
            while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
            fprintf(stderr, "broker probe exceeded its bounded deadline\n");
            free(request);
            return 1;
        }
        struct pollfd event = {.fd = listener, .events = POLLIN};
        int ready = poll(&event, 1, remaining < 250 ? remaining : 250);
        if (ready < 0 && errno == EINTR) continue;
        require(ready >= 0, "poll broker listener");
        if (!ready || !(event.revents & POLLIN)) continue;
        memset(request, 0, sizes.seccomp_notif);
        if (ioctl(listener, SECCOMP_IOCTL_NOTIF_RECV, request) < 0) {
            if (errno == EINTR || errno == ENOENT) continue;
            fail("receive seccomp notification");
        }
        handle_notification(listener, workspace, child, request);
    }
    free(request);
    return !WIFEXITED(status) || WEXITSTATUS(status) != 0;
}

/* Codex detaches command children into new sessions. A group kill is not
 * sufficient. This single-threaded parent is a subreaper with no other children.
 * Android omits /proc/PID/task/TID/children. If children remain, numeric /proc
 * entries are candidates only: waitid(P_PID, WNOWAIT) must confirm actual kernel
 * parenthood before any signal. An unreaped confirmed child's PID cannot be
 * reused, and no other thread/signal handler here can reap it between the check
 * and signal. Never trust mutable /proc ancestry to authorize a kill. */
static int reap_owned_descendants(void) {
    const struct timespec deadline = deadline_after_seconds(5);
    unsigned int terminated = 0;
    for (;;) {
        int status;
        pid_t waited;
        do { waited = waitpid(-1, &status, WNOHANG); }
        while (waited > 0 || (waited < 0 && errno == EINTR));
        if (waited < 0 && errno == ECHILD) {
            printf("owned_descendant_cleanup=PASS terminated=%u\n", terminated);
            return 0;
        }
        require(waited == 0, "inspect own remaining children");
        DIR *processes = opendir("/proc");
        require(processes != NULL, "enumerate child candidates");
        struct dirent *entry;
        while ((entry = readdir(processes)) != NULL) {
            char *end;
            long candidate = strtol(entry->d_name, &end, 10);
            if (*end || candidate <= 0 || candidate > INT_MAX) continue;
            siginfo_t information = {0};
            if (waitid(P_PID, (id_t)candidate, &information, WEXITED | WNOHANG | WNOWAIT) < 0) {
                require(errno == ECHILD || errno == ESRCH || errno == EINTR,
                        "confirm candidate kernel parenthood");
                continue;
            }
            if (information.si_pid != 0) continue; // Reap this exited child below.
            if (kill((pid_t)candidate, SIGKILL) == 0) ++terminated;
            else require(errno == ESRCH, "terminate owned probe descendant");
        }
        closedir(processes);
        if (!milliseconds_until(&deadline)) {
            fprintf(stderr, "owned descendant cleanup timed out\n");
            return 1;
        }
        struct timespec interval = {.tv_sec = 0, .tv_nsec = 10000000};
        nanosleep(&interval, NULL);
    }
}

static void path_join(char out[PATH_MAX], const char *base, const char *suffix) {
    int length = snprintf(out, PATH_MAX, "%s/%s", base, suffix);
    require(length > 0 && length < PATH_MAX, "diagnostic path length");
}

int main(int argc, char **argv) {
    setbuf(stdout, NULL);
    // Startup/listener receipt and broker execution share one native budget.
    const struct timespec deadline = deadline_after_seconds(PROBE_TIMEOUT_SECONDS);
#ifdef __ANDROID__
    const int expected_args = 3;
    const char *usage = "APP_DATA_DIR APK_NATIVE_DIR";
#else
    const int expected_args = 4;
    const char *usage = "PRIVATE_PARENT_DIR PROOT_EXECUTABLE ROOTFS";
#endif
    if (argc != expected_args) {
        fprintf(stderr, "usage: %s %s (all paths absolute)\n", argv[0], usage);
        return 2;
    }
    for (int i = 1; i < argc; ++i) require(argv[i][0] == '/', "absolute argument required");
    long abi = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    unsigned int action = SECCOMP_RET_USER_NOTIF;
    printf("uid=%u landlock_abi=%ld inherited_seccomp=%d\n", getuid(), abi,
           prctl(PR_GET_SECCOMP, 0, 0, 0, 0));
    require(abi >= 6, "Landlock ABI 6 required including signal scope");
    require(syscall(SYS_seccomp, SECCOMP_GET_ACTION_AVAIL, 0, &action) == 0,
            "seccomp user notification required");
    char evidence[PATH_MAX];
    char parent_path[PATH_MAX];
    require(realpath(argv[1], parent_path) != NULL, "canonical parent directory");
#ifdef __ANDROID__
    int length = snprintf(evidence, sizeof(evidence), "%s/cache/foldgpt-codex-offline-XXXXXX", parent_path);
    path_join(proot_path, argv[2], "libproot.so");
    path_join(loader_path, argv[2], "libproot-loader.so");
    path_join(loader32_path, argv[2], "libproot-loader32.so");
    path_join(rootfs_path, parent_path, "files/debian");
#else
    int length = snprintf(evidence, sizeof(evidence), "%s/foldgpt-codex-offline-XXXXXX", parent_path);
    require(realpath(argv[2], proot_path) != NULL && realpath(argv[3], rootfs_path) != NULL,
            "canonical native Linux test paths");
#endif
    require(length > 0 && length < (int)sizeof(evidence), "evidence path length");
    require(mkdtemp(evidence) != NULL, "create private evidence tree");
    int base = open(evidence, O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    require(base >= 0, "open own evidence directory");
    require(mkdirat(base, "workspace", 0700) == 0 && mkdirat(base, "outside", 0700) == 0
            && mkdirat(base, "scratch", 0700) == 0,
            "create own workspace and outside fixtures");
    int workspace = openat(base, "workspace", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    int outside = openat(base, "outside", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    scratch_directory = openat(base, "scratch", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    require(workspace >= 0 && outside >= 0 && scratch_directory >= 0, "open fixture directories");
    /* Codex deliberately separates CODEX_HOME from its system temp root. */
    const char *profile_dirs[] = {"home", "codexhome", "config", "cache", "state", "run"};
    for (unsigned int i = 0; i < sizeof(profile_dirs) / sizeof(profile_dirs[0]); ++i)
        require(mkdirat(scratch_directory, profile_dirs[i], 0700) == 0,
                "create empty isolated experiment profile directory");
    path_join(workspace_path, evidence, "workspace");
    path_join(scratch_path, evidence, "scratch");
    path_join(outside_path, evidence, "outside");
#ifdef __ANDROID__
    char talloc_path[PATH_MAX];
    path_join(talloc_path, argv[2], "libtalloc.so");
    require(symlinkat(talloc_path, scratch_directory, "libtalloc.so.2") == 0,
            "create own native versioned library alias");
    length = snprintf(library_path, sizeof(library_path), "%s:%s", scratch_path, argv[2]);
#else
    char *last_slash = strrchr(proot_path, '/');
    require(last_slash != NULL, "native proot directory");
    length = snprintf(library_path, sizeof(library_path), "%.*s", (int)(last_slash - proot_path), proot_path);
    require(length > 0 && length < PATH_MAX, "native PRoot build directory length");
    path_join(loader_path, library_path, "loader/loader");
    path_join(loader32_path, library_path, "loader/loader-m32");
#endif
    require(length > 0 && length < (int)sizeof(library_path), "library search path length");
    require(mkdirat(workspace, ".git", 0700) == 0 && mkdirat(workspace, "src", 0700) == 0
            && mkdirat(workspace, "src/.git", 0700) == 0
            && mkdirat(workspace, ".codex", 0700) == 0
            && mkdirat(workspace, ".agents", 0700) == 0, "create metadata fixtures");
    make_file(workspace, ".git/config", protected_marker);
    make_file(workspace, "src/.git/config", protected_marker);
    make_file(outside, "victim.txt", outside_marker);
    require(symlinkat("../outside", workspace, "outside-link") == 0, "create own symlink fixture");
    int channels[2];
    require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, channels) == 0,
            "create private FD-transfer channel");
    require(prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0,
            "adopt only this probe's detached descendants for cleanup");
    const pid_t supervising_pid = getpid();
    pid_t child = fork();
    require(child >= 0, "fork bounded worker");
    if (!child) {
        close(channels[0]);
        child_probe(channels[1], workspace, base, outside, supervising_pid);
        _exit(1);
    }
    close(channels[1]);
    int listener = receive_fd(channels[0], &deadline);
    close(channels[0]);
    if (listener < 0) {
        int saved = errno;
        kill(-child, SIGKILL);
        kill(child, SIGKILL);
        while (waitpid(child, NULL, 0) < 0 && errno == EINTR) {}
        reap_owned_descendants();
        errno = saved;
        fail("receive worker notification listener");
    }
    int failed = broker_loop(listener, workspace, child, &deadline);
    close(listener);
    failed |= reap_owned_descendants();
    printf("workspace_grants=%u descendant_workspace_grants=%u scratch_grants=%u broker_denials=%u\n",
           broker_grants, descendant_workspace_grants, scratch_grants, broker_denials);
    printf("scratch_mode_changes=%u\n", scratch_mode_changes);
    printf("verified_null_device_grants=%u\n", null_device_grants);
    printf("unsupported_syscall_denials=%u path_denials=%u\n",
           unsupported_denials, broker_denials - unsupported_denials);
    if (failed) {
        fprintf(stderr, "bounded worker failed; evidence_directory=%s\n", evidence);
        return 1;
    }
    verify_file(workspace, "normal.txt", appended_marker);
    verify_file(workspace, "src/normal.txt", marker);
    verify_file(workspace, ".gitignore", marker);
    verify_file(workspace, ".git/config", protected_marker);
    verify_file(workspace, "src/.git/config", protected_marker);
    verify_file(outside, "victim.txt", outside_marker);
    verify_absent(workspace, "unbrokered.txt");
    verify_absent(workspace, ".git/new-file");
    verify_absent(workspace, ".codex/config.toml");
    verify_absent(workspace, ".agents/settings");
    struct stat protected_mode, outside_mode;
    require(fstatat(workspace, ".git/config", &protected_mode, AT_SYMLINK_NOFOLLOW) == 0
            && fstatat(outside, "victim.txt", &outside_mode, AT_SYMLINK_NOFOLLOW) == 0
            && (protected_mode.st_mode & 0777) == 0600 && (outside_mode.st_mode & 0777) == 0600,
            "independent protected mode verification");
    require(broker_grants == 4 && descendant_workspace_grants == 4
            && broker_denials - unsupported_denials >= 11,
            "expected official Codex fixture grants and path denial lower bound");
    verify_absent(scratch_directory, "codexhome/auth.json");
    close(workspace);
    close(outside);
    close(scratch_directory);
    close(base);
    printf("independent_parent_verification=PASS evidence_directory=%s\n", evidence);
    puts("scope=fixed offline official Codex command/exec via PRoot; not complete Codex policy");
    return 0;
}
