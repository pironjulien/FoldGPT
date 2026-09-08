/* Fixed, one-child identity/FD qualification. No ptrace, fork, namespace,
 * seccomp, Landlock or credential-changing operation is performed here. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/capability.h>
#include <poll.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

static int read_fixed(int fd, const char *expected) {
    size_t size = strlen(expected), offset = 0;
    char buffer[128];
    if (size >= sizeof(buffer)) return 0;
    while (offset < size) {
        struct pollfd event = {.fd = fd, .events = POLLIN};
        int result;
        do { result = poll(&event, 1, 5000); } while (result < 0 && errno == EINTR);
        if (result != 1 || !(event.revents & POLLIN)) return 0;
        ssize_t count = read(fd, buffer + offset, size - offset);
        if (count <= 0) return 0;
        offset += (size_t)count;
    }
    if (memcmp(buffer, expected, size)) return 0;
    // EOF proves the challenge is exactly the admitted payload, not a prefix.
    char extra;
    return read(fd, &extra, 1) == 0;
}

static int read_proc(const char *path, char *buffer, size_t capacity) {
    int fd = open(path, O_RDONLY | O_CLOEXEC);
    if (fd < 0) return 0;
    ssize_t count = read(fd, buffer, capacity - 1);
    char extra;
    int complete = count >= 0 && read(fd, &extra, 1) == 0;
    close(fd);
    if (!complete) return 0;
    buffer[count] = '\0';
    while (count > 0 && (buffer[count - 1] == '\n' || buffer[count - 1] == '\0')) buffer[--count] = '\0';
    return 1;
}

static void quote(FILE *output, const char *value) {
    fputc('"', output);
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') fprintf(output, "\\%c", *p);
        else if (*p < 32 || *p > 126) fprintf(output, "\\u%04x", *p);
        else fputc(*p, output);
    }
    fputc('"', output);
}

static int no_extra_fds(void) {
    DIR *directory = opendir("/proc/self/fd");
    if (!directory) return 0;
    int own = dirfd(directory), result = 1;
    struct dirent *entry;
    errno = 0;
    while ((entry = readdir(directory))) {
        char *end;
        long fd = strtol(entry->d_name, &end, 10);
        if (*end == '\0' && fd > 3 && fd != own) result = 0;
    }
    if (errno) result = 0;
    closedir(directory);
    return result;
}

static long number(const char *value) {
    char *end;
    errno = 0;
    long result = strtol(value, &end, 10);
    return errno || *end || result <= 0 || result > INT_MAX ? -1 : result;
}

int main(int argc, char **argv) {
    // Default SIGALRM bounds this process even if its peer disappears. No
    // descendants exist and no device setting or parent process is changed.
    struct sigaction deadline = {.sa_handler = SIG_DFL};
    sigset_t deadline_signal;
    if (sigemptyset(&deadline.sa_mask) || sigaction(SIGALRM, &deadline, NULL)
        || sigemptyset(&deadline_signal) || sigaddset(&deadline_signal, SIGALRM)
        || sigprocmask(SIG_UNBLOCK, &deadline_signal, NULL)) return 70;
    alarm(20);
    if (argc != 6 || strcmp(argv[1], "--identity-fds-v1")) return 64;
    long expected_uid = number(argv[2]), expected_parent = number(argv[4]);
    if (expected_uid < 10000 || expected_parent < 1 || strlen(argv[5]) != 32
        || strspn(argv[5], "0123456789abcdef") != 32
        || strcmp(argv[3], "/data/user/0/app.foldgpt")) return 64;
    uid_t ur = 0, ue = 0, us = 0;
    gid_t gr = 0, ge = 0, gs = 0;
    int identity = getresuid(&ur, &ue, &us) == 0 && getresgid(&gr, &ge, &gs) == 0;
    identity = identity && ur == expected_uid && ue == ur && us == ur && gr == ur && ge == gr && gs == gr;
    int parent_matches = getppid() == expected_parent;
    char context[1024] = "", status[8192] = "", cwd[PATH_MAX] = "", resolved[PATH_MAX] = "";
    int proc_read = read_proc("/proc/self/attr/current", context, sizeof(context))
        && read_proc("/proc/self/status", status, sizeof(status));
    int cwd_matches = getcwd(cwd, sizeof(cwd)) && realpath(argv[3], resolved) && !strcmp(cwd, resolved);
    struct stat directory;
    int target_owned = stat(argv[3], &directory) == 0 && S_ISDIR(directory.st_mode) && directory.st_uid == expected_uid;
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct caps[2] = {{0}, {0}};
    int zero_caps = syscall(__NR_capget, &header, caps) == 0;
    for (int i = 0; i < 2; ++i) if (caps[i].effective || caps[i].permitted || caps[i].inheritable) zero_caps = 0;
    int no_new_privs = prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0);
    int seccomp = prctl(PR_GET_SECCOMP, 0, 0, 0, 0);
    int fd_flags[4] = {-1, -1, -1, -1}, fifo[4] = {0};
    int descriptor_contract = 1;
    for (int i = 0; i < 4; ++i) {
        struct stat st;
        fd_flags[i] = fcntl(i, F_GETFL);
        fifo[i] = fstat(i, &st) == 0 && S_ISFIFO(st.st_mode);
        int direction = (i == 0 || i == 3) ? O_RDONLY : O_WRONLY;
        if (!fifo[i] || fd_flags[i] < 0 || (fd_flags[i] & O_ACCMODE) != direction) descriptor_contract = 0;
    }
    int extra_closed = no_extra_fds();
    char stdin_expected[128], control_expected[128];
    snprintf(stdin_expected, sizeof(stdin_expected), "foldgpt.runas.identity.v1:stdin:%s\n", argv[5]);
    snprintf(control_expected, sizeof(control_expected), "foldgpt.runas.identity.v1:control:%s\n", argv[5]);
    int input_matches = descriptor_contract && read_fixed(0, stdin_expected);
    int control_matches = descriptor_contract && read_fixed(3, control_expected);
    int context_matches = !strncmp(context, "u:r:runas_app:", strlen("u:r:runas_app:"));
    int passed = identity && parent_matches && proc_read && cwd_matches && target_owned
        && zero_caps && no_new_privs == 0 && seccomp == 0 && descriptor_contract
        && extra_closed && input_matches && control_matches && context_matches;
    fprintf(stdout, "{\"schema\":\"foldgpt.runas.identity-child.v1\",\"nonce\":\"%s\",\"pid\":%d,\"parentPid\":%d,"
        "\"uid\":[%u,%u,%u],\"gid\":[%u,%u,%u],\"identityMatches\":%s,\"parentMatches\":%s,"
        "\"zeroCapabilities\":%s,\"noNewPrivileges\":%d,\"seccomp\":%d,\"cwdMatches\":%s,"
        "\"targetOwned\":%s,\"noExtraDescriptors\":%s,\"descriptorContract\":%s,"
        "\"stdinChallengeMatches\":%s,\"controlChallengeMatches\":%s,\"contextMatches\":%s,\"passed\":%s,\"cwd\":",
        argv[5], getpid(), getppid(), ur, ue, us, gr, ge, gs,
        identity ? "true" : "false", parent_matches ? "true" : "false", zero_caps ? "true" : "false",
        no_new_privs, seccomp, cwd_matches ? "true" : "false", target_owned ? "true" : "false",
        extra_closed ? "true" : "false", descriptor_contract ? "true" : "false",
        input_matches ? "true" : "false", control_matches ? "true" : "false",
        context_matches ? "true" : "false", passed ? "true" : "false");
    quote(stdout, cwd);
    fputs(",\"context\":", stdout); quote(stdout, context);
    fputs(",\"procStatus\":", stdout); quote(stdout, status);
    fputs(",\"fdFlags\":[", stdout);
    for (int i = 0; i < 4; ++i) fprintf(stdout, "%s%d", i ? "," : "", fd_flags[i]);
    fputs("]}\n", stdout);
    if (fflush(stdout)) return 74;
    fprintf(stderr, "{\"schema\":\"foldgpt.runas.identity-report.v1\",\"nonce\":\"%s\","
        "\"pid\":%d,\"reportFd\":2,\"stdoutFlushed\":true,\"passed\":%s}\n",
        argv[5], getpid(), passed ? "true" : "false");
    if (fflush(stderr)) return 74;
    return passed ? 0 : 65;
}
