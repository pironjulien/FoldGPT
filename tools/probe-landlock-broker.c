#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/audit.h>
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
#include <sys/uio.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* CAPABILITY FEASIBILITY PROBE ONLY. This is not a Linux or Codex sandbox.
 *
 * The only workload is the built-in, single-threaded test child. Landlock
 * denies filesystem writes; seccomp notifies the parent about openat only.
 * The parent copies path/scalars, validates relative workspace components,
 * opens through a fixed root FD using openat2, then atomically installs and
 * returns that FD with NOTIF_ADDFD|SEND. No USER_NOTIF_FLAG_CONTINUE is used.
 * Other syscalls outside the narrow worker allowlist fail with EPERM.
 *
 * This does NOT implement arbitrary commands, filesystem policy updates,
 * rename/link semantics, ptrace emulation, Android isolatedProcess, or a
 * production broker. The parent has normal app privileges. ID_VALID stops
 * already-cancelled requests before openat2, but creation is not transactional
 * with ADDFD: cancellation after validation can leave an empty test file in
 * this invocation's private evidence directory. No broad rollback is attempted.
 * Every path written or created belongs to our own mkdtemp tree.
 *
 * Usage: probe-landlock-broker PRIVATE_PARENT_DIRECTORY
 * Build: cc -O2 -Wall -Wextra -Werror probe-landlock-broker.c -o probe
 * Supports native Linux x86_64 and Android/Linux aarch64, Landlock ABI >= 3,
 * openat2 and seccomp notification ADDFD_FLAG_SEND (Linux >= 5.14).
 */

#if defined(__aarch64__)
#define PROBE_AUDIT_ARCH AUDIT_ARCH_AARCH64
#elif defined(__x86_64__)
#define PROBE_AUDIT_ARCH AUDIT_ARCH_X86_64
#else
#error "This bounded probe supports aarch64 and x86_64 only"
#endif

#define PROBE_TIMEOUT_SECONDS 20
static const char marker[] = "FoldGPT broker granted write FD\n";
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

static int receive_fd(int socket_fd) {
    char payload;
    union { struct cmsghdr alignment; char bytes[CMSG_SPACE(sizeof(int))]; } control;
    memset(&control, 0, sizeof(control));
    struct iovec vector = {.iov_base = &payload, .iov_len = 1};
    struct msghdr message = {.msg_iov = &vector, .msg_iovlen = 1,
                            .msg_control = control.bytes, .msg_controllen = sizeof(control.bytes)};
    ssize_t received;
    do { received = recvmsg(socket_fd, &message, MSG_CMSG_CLOEXEC); }
    while (received < 0 && errno == EINTR);
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
        | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE;
    struct landlock_ruleset_attr attributes = {.handled_access_fs = reads | writes};
    int ruleset = (int)syscall(SYS_landlock_create_ruleset, &attributes, sizeof(attributes), 0);
    require(ruleset >= 0, "create read-only Landlock ruleset");
    int root = open("/", O_PATH | O_DIRECTORY | O_CLOEXEC);
    require(root >= 0, "open Landlock read root");
    struct landlock_path_beneath_attr rule = {.allowed_access = reads, .parent_fd = root};
    require(syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) == 0,
            "allow read-only filesystem");
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "set no_new_privs");
    require(syscall(SYS_landlock_restrict_self, ruleset, 0) == 0, "enforce Landlock");
    close(root);
    close(ruleset);
}

#define ALLOW_SYSCALL(number) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (number), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)

static int notification_filter(void) {
    /* This is deliberately NOT an arbitrary-command allowlist. No exec, fork,
     * network socket, direct openat2, ioctl, link, rename or file mutation API. */
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, PROBE_AUDIT_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_openat, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        ALLOW_SYSCALL(SYS_write),
        ALLOW_SYSCALL(SYS_close),
        ALLOW_SYSCALL(SYS_sendmsg),
        ALLOW_SYSCALL(SYS_exit),
        ALLOW_SYSCALL(SYS_exit_group),
        ALLOW_SYSCALL(SYS_rt_sigreturn),
        ALLOW_SYSCALL(SYS_rt_sigprocmask),
        ALLOW_SYSCALL(SYS_futex),
        ALLOW_SYSCALL(SYS_mmap),
        ALLOW_SYSCALL(SYS_munmap),
        ALLOW_SYSCALL(SYS_mprotect),
        ALLOW_SYSCALL(SYS_brk),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
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

static void worker_open(const char *name, const char *path, int flags, int expected_error) {
    /* Full fixed buffer lets the parent perform exactly one bounded read.
     * The parent must still copy and resolve it rather than continuing openat. */
    char copied_path[PATH_MAX] = {0};
    size_t length = strlen(path);
    if (length >= sizeof(copied_path)) _exit(1);
    memcpy(copied_path, path, length + 1);
    errno = 0;
    int fd = (int)syscall(SYS_openat, (long)AT_FDCWD, copied_path, (long)flags,
                         (long)((flags & O_CREAT) ? 0600 : 0));
    int observed_error = errno;
    if (expected_error) {
        if (fd >= 0) close(fd);
        worker_check(name, fd < 0 && observed_error == expected_error, observed_error);
        return;
    }
    worker_check(name, fd >= 0, observed_error);
    if (write_all(fd, marker, sizeof(marker) - 1) < 0) {
        worker_check("granted_fd_write", 0, errno);
    }
    if (close(fd) < 0) worker_check("granted_fd_close", 0, errno);
}

static void child_probe(int channel, int workspace, int base, int outside, const char *absolute_outside) {
    alarm(PROBE_TIMEOUT_SECONDS);
    require(fchdir(workspace) == 0, "set test child workspace");
    close(workspace);
    close(base);
    close(outside);
    landlock_read_only();

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

    const int create = O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC;
    worker_open("normal_create", "normal.txt", create, 0);
    worker_open("normal_reopen", "normal.txt", O_WRONLY | O_CLOEXEC, 0);
    worker_open("nested_create", "src/normal.txt", create, 0);
    worker_open("similar_name_allowed", ".gitignore", create, 0);
    worker_open("existing_metadata_denied", ".git/config", O_WRONLY | O_CLOEXEC, EPERM);
    worker_open("nested_metadata_denied", "src/.git/config", O_WRONLY | O_CLOEXEC, EPERM);
    worker_open("metadata_child_create_denied", ".git/new-file", create, EPERM);
    worker_open("missing_codex_denied", ".codex/config.toml", create, EPERM);
    worker_open("missing_agents_denied", ".agents/settings", create, EPERM);
    worker_open("outside_parent_denied", "../outside/victim.txt", O_WRONLY | O_CLOEXEC, EPERM);
    worker_open("outside_absolute_denied", absolute_outside, O_WRONLY | O_CLOEXEC, EPERM);
    worker_open("symlink_denied", "outside-link/victim.txt", O_WRONLY | O_CLOEXEC, ELOOP);
    worker_open("unsupported_truncate_denied", "normal.txt", O_WRONLY | O_TRUNC | O_CLOEXEC, EOPNOTSUPP);
    errno = 0;
    denied = (int)syscall(SYS_openat2, AT_FDCWD, "unbrokered.txt", &direct, sizeof(direct));
    denied_errno = errno;
    if (denied >= 0) close(denied);
    worker_check("direct_openat2_filtered", denied < 0 && denied_errno == EPERM, denied_errno);
    _exit(0);
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

static void deny_request(int listener, uint64_t id, int error) {
    struct seccomp_notif_resp response = {.id = id, .val = 0, .error = -error, .flags = 0};
    if (ioctl(listener, SECCOMP_IOCTL_NOTIF_SEND, &response) < 0 && errno != ENOENT) {
        fail("return broker denial");
    }
    ++broker_denials;
}

static void handle_notification(int listener, int workspace, pid_t child,
                                const struct seccomp_notif *request) {
    /* Copy scalar arguments from the received kernel snapshot, never from
     * tracee memory. The only tracee-memory read copies the path below. */
    const uint64_t id = request->id;
    const pid_t requester = (pid_t)request->pid;
    const int64_t directory = (int64_t)request->data.args[0];
    const uint64_t pathname = request->data.args[1];
    const uint64_t flags = request->data.args[2];
    const uint64_t mode = request->data.args[3];
    const uint64_t allowed_flags = O_WRONLY | O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC;
    if (requester != child || request->data.arch != PROBE_AUDIT_ARCH
            || request->data.nr != SYS_openat || request->flags != 0) {
        deny_request(listener, id, EPERM);
        return;
    }
    if (directory != AT_FDCWD || (flags & ~allowed_flags)
            || ((flags & O_ACCMODE) != O_WRONLY && (flags & O_ACCMODE) != O_RDWR)
            || !(flags & O_CLOEXEC)
            || (!!(flags & O_CREAT) != !!(flags & O_EXCL))
            || (mode & ~0777ULL) || (!(flags & O_CREAT) && mode != 0)) {
        deny_request(listener, id, EOPNOTSUPP);
        return;
    }
    char path[PATH_MAX];
    if (!notification_valid(listener, id)) return;
    int error = copy_request_path(requester, pathname, path);
    if (error || !valid_relative_path(path)) {
        deny_request(listener, id, error ? error : EPERM);
        return;
    }
    struct open_how how = {.flags = flags, .mode = mode,
                          .resolve = RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV};
    /* Validate again immediately before opening/creating. openat2 resolves our
     * private copy, using a fixed directory FD; the child cannot rewrite either. */
    if (!notification_valid(listener, id)) return;
    int source = (int)syscall(SYS_openat2, workspace, path, &how, sizeof(how));
    if (source < 0) {
        deny_request(listener, id, errno);
        return;
    }
    struct seccomp_notif_addfd add = {.id = id, .flags = SECCOMP_ADDFD_FLAG_SEND,
                                     .srcfd = (uint32_t)source, .newfd = 0,
                                     .newfd_flags = O_CLOEXEC};
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
    ++broker_grants;
}

static int broker_loop(int listener, int workspace, pid_t child) {
    struct seccomp_notif_sizes sizes;
    require(syscall(SYS_seccomp, SECCOMP_GET_NOTIF_SIZES, 0, &sizes) == 0,
            "read seccomp notification sizes");
    require(sizes.seccomp_notif >= sizeof(struct seccomp_notif), "notification ABI size");
    struct seccomp_notif *request = calloc(1, sizes.seccomp_notif);
    require(request != NULL, "allocate notification");
    const time_t deadline = time(NULL) + PROBE_TIMEOUT_SECONDS;
    int status = 0;
    for (;;) {
        pid_t waited = waitpid(child, &status, WNOHANG);
        if (waited == child) break;
        if (waited < 0 && errno != EINTR) fail("wait for probe worker");
        if (time(NULL) >= deadline) {
            kill(child, SIGKILL);
            while (waitpid(child, &status, 0) < 0 && errno == EINTR) {}
            fprintf(stderr, "broker probe exceeded its bounded deadline\n");
            free(request);
            return 1;
        }
        struct pollfd event = {.fd = listener, .events = POLLIN};
        int ready = poll(&event, 1, 250);
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

int main(int argc, char **argv) {
    setbuf(stdout, NULL);
    if (argc != 2 || argv[1][0] != '/') {
        fprintf(stderr, "usage: %s PRIVATE_PARENT_DIRECTORY\n", argv[0]);
        fprintf(stderr, "PRIVATE_PARENT_DIRECTORY must be an absolute path\n");
        return 2;
    }
    long abi = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    unsigned int action = SECCOMP_RET_USER_NOTIF;
    printf("uid=%u landlock_abi=%ld inherited_seccomp=%d\n", getuid(), abi,
           prctl(PR_GET_SECCOMP, 0, 0, 0, 0));
    require(abi >= 3, "Landlock ABI 3 required");
    require(syscall(SYS_seccomp, SECCOMP_GET_ACTION_AVAIL, 0, &action) == 0,
            "seccomp user notification required");
    char evidence[PATH_MAX];
    int length = snprintf(evidence, sizeof(evidence), "%s/foldgpt-broker-XXXXXX", argv[1]);
    require(length > 0 && length < (int)sizeof(evidence), "evidence path length");
    require(mkdtemp(evidence) != NULL, "create private evidence tree");
    int base = open(evidence, O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    require(base >= 0, "open own evidence directory");
    require(mkdirat(base, "workspace", 0700) == 0 && mkdirat(base, "outside", 0700) == 0,
            "create own workspace and outside fixtures");
    int workspace = openat(base, "workspace", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    int outside = openat(base, "outside", O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    require(workspace >= 0 && outside >= 0, "open fixture directories");
    require(mkdirat(workspace, ".git", 0700) == 0 && mkdirat(workspace, "src", 0700) == 0
            && mkdirat(workspace, "src/.git", 0700) == 0, "create metadata fixtures");
    make_file(workspace, ".git/config", protected_marker);
    make_file(workspace, "src/.git/config", protected_marker);
    make_file(outside, "victim.txt", outside_marker);
    require(symlinkat("../outside", workspace, "outside-link") == 0, "create own symlink fixture");
    char absolute_outside[PATH_MAX];
    length = snprintf(absolute_outside, sizeof(absolute_outside), "%s/outside/victim.txt", evidence);
    require(length > 0 && length < (int)sizeof(absolute_outside), "outside fixture path length");
    int channels[2];
    require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, channels) == 0,
            "create private FD-transfer channel");
    pid_t child = fork();
    require(child >= 0, "fork bounded worker");
    if (!child) {
        close(channels[0]);
        child_probe(channels[1], workspace, base, outside, absolute_outside);
        _exit(1);
    }
    close(channels[1]);
    int listener = receive_fd(channels[0]);
    close(channels[0]);
    if (listener < 0) {
        int saved = errno;
        kill(child, SIGKILL);
        while (waitpid(child, NULL, 0) < 0 && errno == EINTR) {}
        errno = saved;
        fail("receive worker notification listener");
    }
    int failed = broker_loop(listener, workspace, child);
    close(listener);
    printf("broker_grants=%u broker_denials=%u\n", broker_grants, broker_denials);
    if (failed) {
        fprintf(stderr, "bounded worker failed; evidence_directory=%s\n", evidence);
        return 1;
    }
    verify_file(workspace, "normal.txt", marker);
    verify_file(workspace, "src/normal.txt", marker);
    verify_file(workspace, ".gitignore", marker);
    verify_file(workspace, ".git/config", protected_marker);
    verify_file(workspace, "src/.git/config", protected_marker);
    verify_file(outside, "victim.txt", outside_marker);
    verify_absent(workspace, "unbrokered.txt");
    verify_absent(workspace, ".git/new-file");
    verify_absent(workspace, ".codex");
    verify_absent(workspace, ".agents");
    require(broker_grants == 4 && broker_denials == 9, "expected broker request counts");
    close(workspace);
    close(outside);
    close(base);
    printf("independent_parent_verification=PASS evidence_directory=%s\n", evidence);
    puts("scope=bounded capability probe; not an arbitrary-command or production sandbox");
    return 0;
}
