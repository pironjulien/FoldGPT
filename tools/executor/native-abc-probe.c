/* SPDX-License-Identifier: GPL-3.0-only
 * Fixed native Landlock experiment, not a general command executor.
 * No PRoot, exec(), shell, model call, or account data is used.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Private names allow compilation with NDK and older userspace headers.
 * These are the public Linux Landlock ABI values, not emulated enforcement.
 */
#define LL_VERSION 1U
#define LL_PATH_BENEATH 1
#define LL_WRITE_FILE (1ULL << 1)
#define LL_READ_FILE (1ULL << 2)
#define LL_TRUNCATE (1ULL << 14)
#define LL_FS_THROUGH_ABI5 ((1ULL << 16) - 1)
#define LL_SCOPE_SIGNAL (1ULL << 1)
#define REPORT_MAGIC UINT32_C(0x41424336)
#define BUFFER_SIZE 128
#define WORKER_TIMEOUT_MS 5000
#define REAP_TIMEOUT_MS 5000

struct ll_ruleset {
    uint64_t handled_access_fs;
    uint64_t handled_access_net;
    uint64_t scoped;
};
struct ll_path {
    uint64_t allowed_access;
    int32_t parent_fd;
} __attribute__((packed));

struct attempt {
    int32_t opened;
    int32_t error;
    int32_t transferred;
    char bytes[BUFFER_SIZE];
};
struct report {
    uint32_t magic;
    int32_t policy;
    int32_t stage;
    int32_t setup_errno;
    int32_t abi;
    struct attempt target_read;
    struct attempt target_write;
    struct attempt control_read;
    struct attempt excluded_read;
    struct attempt excluded_write;
};
struct fixture_file {
    const char *name;
    const char *initial;
    char path[PATH_MAX];
    struct stat identity;
    int created;
};

static const char control_bytes[] = "unrelated permitted read\n";
static const char excluded_bytes[] = "excluded sibling stays private\n";
static const char violation_bytes[] = "UNEXPECTED WRITE AUTHORITY\n";

static int write_all(int fd, const void *data, size_t size)
{
    const unsigned char *cursor = data;
    while (size) {
        ssize_t n = write(fd, cursor, size);
        if (n < 0 && errno == EINTR)
            continue;
        if (n <= 0) {
            if (n == 0)
                errno = EIO;
            return -1;
        }
        cursor += (size_t)n;
        size -= (size_t)n;
    }
    return 0;
}

static int64_t monotonic_ms(void)
{
    struct timespec now;
    if (clock_gettime(CLOCK_MONOTONIC, &now) < 0)
        return -1;
    return (int64_t)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}

static int add_exact_file(int ruleset, const char *path, uint64_t rights)
{
    int fd = open(path, O_PATH | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0)
        return -1;
    struct ll_path attr = {.allowed_access = rights, .parent_fd = fd};
    int result = (int)syscall(SYS_landlock_add_rule, ruleset,
                              LL_PATH_BENEATH, &attr, 0);
    int saved = errno;
    close(fd);
    errno = saved;
    return result;
}

static int restrict_worker(int policy, const char *target, const char *control)
{
    struct ll_ruleset attr = {
        .handled_access_fs = LL_FS_THROUGH_ABI5,
        .scoped = LL_SCOPE_SIGNAL,
    };
    int fd = (int)syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0);
    if (fd < 0)
        return -1;
    uint64_t target_rights = policy == 0
        ? LL_READ_FILE | LL_WRITE_FILE | LL_TRUNCATE : LL_READ_FILE;
    int result = 0;
    if (add_exact_file(fd, control, LL_READ_FILE) < 0 ||
        (policy != 2 && add_exact_file(fd, target, target_rights) < 0) ||
        prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
        syscall(SYS_landlock_restrict_self, fd, 0) < 0)
        result = -1;
    int saved = errno;
    close(fd);
    errno = saved;
    return result;
}

/* Direct openat system calls ensure no mocked path API decides the result. */
static struct attempt attempt_read(const char *path)
{
    struct attempt result = {0};
    int fd = (int)syscall(SYS_openat, AT_FDCWD, path,
                          O_RDONLY | O_CLOEXEC | O_NOFOLLOW, 0);
    if (fd < 0) {
        result.error = errno;
        return result;
    }
    result.opened = 1;
    while ((size_t)result.transferred < sizeof(result.bytes)) {
        ssize_t n = read(fd, result.bytes + result.transferred,
                         sizeof(result.bytes) - (size_t)result.transferred);
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0) {
            result.error = errno;
            break;
        }
        if (!n)
            break;
        result.transferred += (int32_t)n;
    }
    if (close(fd) < 0 && !result.error)
        result.error = errno;
    return result;
}

static struct attempt attempt_write(const char *path, const char *bytes)
{
    struct attempt result = {0};
    int fd = (int)syscall(SYS_openat, AT_FDCWD, path,
                          O_WRONLY | O_TRUNC | O_CLOEXEC | O_NOFOLLOW, 0);
    if (fd < 0) {
        result.error = errno;
        return result;
    }
    result.opened = 1;
    if (write_all(fd, bytes, strlen(bytes)) < 0)
        result.error = errno;
    else {
        result.transferred = (int32_t)strlen(bytes);
        if (fsync(fd) < 0)
            result.error = errno;
    }
    if (close(fd) < 0 && !result.error)
        result.error = errno;
    return result;
}

static void child_worker(int output, int policy, int abi,
                         struct fixture_file files[3], const char *new_bytes)
{
    struct report report = {.magic = REPORT_MAGIC, .policy = policy, .abi = abi};
    if (dup2(output, STDOUT_FILENO) < 0)
        _exit(120);
    close(STDIN_FILENO);
    close(STDERR_FILENO);
    /* Remove inherited authority, including the parent's directory handle.
     * stdout is a pipe, never an inherited log or target file descriptor.
     */
    report.stage = 1;
    if (syscall(SYS_close_range, 3U, UINT_MAX, 0U) < 0)
        goto failed;
    report.stage = 2;
    if (restrict_worker(policy, files[0].path, files[1].path) < 0)
        goto failed;
    report.stage = 3;
    report.control_read = attempt_read(files[1].path);
    report.target_read = attempt_read(files[0].path);
    report.target_write = attempt_write(files[0].path, new_bytes);
    report.excluded_read = attempt_read(files[2].path);
    report.excluded_write = attempt_write(files[2].path, violation_bytes);
    report.stage = 4;
    _exit(write_all(STDOUT_FILENO, &report, sizeof(report)) == 0 ? 0 : 121);
failed:
    report.setup_errno = errno;
    (void)write_all(STDOUT_FILENO, &report, sizeof(report));
    _exit(122);
}

static int run_worker(int policy, int abi, struct fixture_file files[3],
                      const char *new_bytes, struct report *report)
{
    int pipefd[2];
    if (pipe2(pipefd, O_CLOEXEC) < 0)
        return -1;
    int64_t started = monotonic_ms();
    if (started < 0) {
        close(pipefd[0]);
        close(pipefd[1]);
        return -1;
    }
    fflush(NULL);
    pid_t child = fork();
    if (child == 0)
        child_worker(pipefd[1], policy, abi, files, new_bytes);
    close(pipefd[1]);
    if (child < 0) {
        close(pipefd[0]);
        return -1;
    }
    size_t received = 0;
    int status = 0, reaped = 0, failure = 0, eof = 0;
    if (fcntl(pipefd[0], F_SETFL, O_NONBLOCK) < 0)
        failure = errno;
    while (!failure && (!reaped || !eof)) {
        int64_t now = monotonic_ms();
        if (now < 0 || now - started >= WORKER_TIMEOUT_MS) {
            failure = now < 0 ? errno : ETIMEDOUT;
            break;
        }
        if (!eof) {
            unsigned char extra;
            void *destination = received < sizeof(*report)
                ? (void *)((unsigned char *)report + received) : &extra;
            size_t capacity = received < sizeof(*report)
                ? sizeof(*report) - received : 1;
            ssize_t n = read(pipefd[0], destination, capacity);
            if (n > 0) {
                received += (size_t)n;
                if (received > sizeof(*report))
                    failure = EPROTO;
            } else if (!n)
                eof = 1;
            else if (errno != EAGAIN && errno != EINTR)
                failure = errno;
        }
        if (!reaped) {
            pid_t result = waitpid(child, &status, WNOHANG);
            if (result == child)
                reaped = 1;
            else if (result < 0 && errno != EINTR)
                failure = errno;
        }
        if (!failure && (!eof || !reaped)) {
            struct pollfd event = {.fd = eof ? -1 : pipefd[0], .events = POLLIN};
            int remaining = (int)(WORKER_TIMEOUT_MS - (now - started));
            /* Once EOF is seen, waitpid still shares the same deadline. */
            int delay = remaining < 10 ? remaining : 10;
            if (poll(&event, 1, delay) < 0 && errno != EINTR)
                failure = errno;
        }
    }
    close(pipefd[0]);
    if (!reaped) {
        /* Only this unreaped direct child is killed: no reused numeric PID. */
        (void)kill(child, SIGKILL);
        int64_t cleanup_started = monotonic_ms();
        while (cleanup_started >= 0) {
            pid_t waited = waitpid(child, &status, WNOHANG);
            if (waited == child) {
                reaped = 1;
                break;
            }
            if (waited < 0 && errno != EINTR)
                break;
            int64_t now = monotonic_ms();
            if (now < 0 || now - cleanup_started >= REAP_TIMEOUT_MS)
                break;
            (void)poll(NULL, 0, 10);
        }
        if (!reaped) {
            fprintf(stderr, "FAIL: killed worker could not be reaped within cleanup deadline\n");
            failure = ETIMEDOUT;
        }
    }
    if (!failure && (received != sizeof(*report) || !WIFEXITED(status) ||
                     WEXITSTATUS(status) != 0))
        failure = EPROTO;
    if (failure) {
        fprintf(stderr, "worker failure: policy=%d stage=%d setup_errno=%d errno=%d\n",
                policy, report->stage, report->setup_errno, failure);
        errno = failure;
        return -1;
    }
    return 0;
}

static int read_matches(struct attempt result, const char *expected)
{
    size_t length = strlen(expected);
    return result.opened == 1 && !result.error &&
        result.transferred == (int32_t)length &&
        !memcmp(result.bytes, expected, length);
}

static int denied(struct attempt result)
{
    return !result.opened && !result.transferred &&
        (result.error == EACCES || result.error == EPERM);
}

static int same_object(const struct stat *before, const struct stat *after)
{
    return before->st_dev == after->st_dev && before->st_ino == after->st_ino &&
        before->st_mode == after->st_mode && before->st_nlink == after->st_nlink &&
        before->st_uid == after->st_uid && before->st_gid == after->st_gid;
}

/* Independent unrestricted parent read; never trusts worker data for disk state. */
static int verify_file(int directory, struct fixture_file *file, const char *bytes)
{
    int fd = openat(directory, file->name, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0)
        return -1;
    struct stat current;
    char actual[BUFFER_SIZE] = {0};
    size_t length = 0;
    int ok = fstat(fd, &current) == 0 && same_object(&file->identity, &current);
    while (ok && length < sizeof(actual)) {
        ssize_t n = read(fd, actual + length, sizeof(actual) - length);
        if (n < 0 && errno == EINTR)
            continue;
        if (n < 0) {
            ok = 0;
            break;
        }
        if (!n)
            break;
        length += (size_t)n;
    }
    if (length != strlen(bytes) || memcmp(actual, bytes, length))
        ok = 0;
    close(fd);
    if (!ok) {
        fprintf(stderr, "parent verification failed: %s\n", file->name);
        errno = EIO;
        return -1;
    }
    return 0;
}

int main(int argc, char **argv)
{
    if (argc != 2 || argv[1][0] != '/') {
        fprintf(stderr, "Usage: %s /absolute/native/fixture/parent\n", argv[0]);
        return 2;
    }
    int abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0, LL_VERSION);
    if (abi < 6) {
        fprintf(stderr, "FAIL: Landlock ABI >= 6 required; got %d (errno=%d)\n", abi, errno);
        return 1;
    }
    char parent[PATH_MAX], directory_path[PATH_MAX];
    if (!realpath(argv[1], parent)) {
        perror("fixture parent");
        return 1;
    }
    int n = snprintf(directory_path, sizeof(directory_path), "%s/foldgpt-native-abc-XXXXXX", parent);
    if (n < 0 || (size_t)n >= sizeof(directory_path) || !mkdtemp(directory_path)) {
        perror("mkdtemp");
        return 1;
    }
    int directory = open(directory_path, O_DIRECTORY | O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (directory < 0) {
        perror("open fixture directory");
        (void)rmdir(directory_path);
        return 1;
    }
    struct fixture_file files[3] = {
        {.name = "value.txt", .initial = "initial target bytes\n"},
        {.name = "permitted-control.txt", .initial = control_bytes},
        {.name = "excluded-sibling.txt", .initial = excluded_bytes},
    };
    int result = 1;
    for (int i = 0; i < 3; i++) {
        n = snprintf(files[i].path, sizeof(files[i].path), "%s/%s", directory_path, files[i].name);
        if (n < 0 || (size_t)n >= sizeof(files[i].path))
            goto cleanup;
        int fd = openat(directory, files[i].name,
                        O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (fd < 0)
            goto cleanup;
        files[i].created = 1;
        int ok = write_all(fd, files[i].initial, strlen(files[i].initial)) == 0 &&
            fsync(fd) == 0 && fstat(fd, &files[i].identity) == 0 &&
            S_ISREG(files[i].identity.st_mode) && files[i].identity.st_nlink == 1;
        close(fd); /* No target data descriptor exists when workers fork. */
        if (!ok)
            goto cleanup;
        printf("fixture name=%s dev=%llu inode=%llu mode=%o links=%llu\n",
               files[i].name, (unsigned long long)files[i].identity.st_dev,
               (unsigned long long)files[i].identity.st_ino,
               (unsigned int)(files[i].identity.st_mode & 07777),
               (unsigned long long)files[i].identity.st_nlink);
    }
    printf("Landlock ABI=%d; exact-file grants; supervisor deadline=%dms per worker\n",
           abi, WORKER_TIMEOUT_MS);
    const int policies[] = {0, 1, 2, 0};
    const char *labels[] = {"A1", "B", "C", "A2"};
    const char *expected = files[0].initial;
    for (int i = 0; i < 4; i++) {
        int policy = policies[i];
        const char *next = policy == 0
            ? (i == 0 ? "policy A first write\n" : "policy A final write\n")
            : violation_bytes;
        struct report report = {0};
        if (run_worker(policy, abi, files, next, &report) < 0)
            goto cleanup;
        int ok = report.magic == REPORT_MAGIC && report.policy == policy &&
            report.abi == abi && report.stage == 4 && !report.setup_errno &&
            read_matches(report.control_read, control_bytes) &&
            denied(report.excluded_read) && denied(report.excluded_write);
        if (policy == 2)
            ok = ok && denied(report.target_read);
        else
            ok = ok && read_matches(report.target_read, expected);
        if (policy == 0) {
            ok = ok && report.target_write.opened == 1 && !report.target_write.error &&
                report.target_write.transferred == (int32_t)strlen(next);
            expected = next;
        } else
            ok = ok && denied(report.target_write);
        /* Check disk state even when a worker reports an unexpected success. */
        int disk_ok = 1;
        for (int j = 0; j < 3; j++) {
            if (verify_file(directory, &files[j], j == 0 ? expected : files[j].initial) < 0)
                disk_ok = 0;
        }
        printf("%s: read_open=%d read_errno=%d write_open=%d write_errno=%d "
               "permitted_control=%s excluded_read_errno=%d excluded_write_errno=%d "
               "parent_bytes_and_identity=%s result=%s\n", labels[i],
               report.target_read.opened, report.target_read.error,
               report.target_write.opened, report.target_write.error,
               read_matches(report.control_read, control_bytes) ? "PASS" : "FAIL",
               report.excluded_read.error, report.excluded_write.error,
               disk_ok ? "PASS" : "FAIL", ok && disk_ok ? "PASS" : "FAIL");
        if (!ok || !disk_ok)
            goto cleanup;
    }
    int status;
    if (waitpid(-1, &status, WNOHANG) != -1 || errno != ECHILD) {
        fprintf(stderr, "FAIL: unexpected unreaped direct child\n");
        goto cleanup;
    }
    result = 0;
cleanup:
    for (int i = 0; i < 3; i++) {
        if (files[i].created && unlinkat(directory, files[i].name, 0) < 0) {
            perror("remove owned fixture file");
            result = 1;
        }
    }
    close(directory);
    if (rmdir(directory_path) < 0) {
        perror("remove owned fixture directory");
        result = 1;
    }
    puts(result == 0
        ? "PASS: native A/B/C/A exact-file data access; all workers reaped; fixture removed"
        : "FAIL: native A/B/C/A diagnostic");
    return result;
}
