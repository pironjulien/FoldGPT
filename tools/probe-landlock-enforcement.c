#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/landlock.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* A bounded kernel experiment, NOT a Codex sandbox implementation. All writes
 * target this invocation's own mkdtemp tree. The parent independently checks
 * the child's files, including the expected Landlock metadata limitation. */
static void require(int ok, const char *what) {
    if (!ok) { perror(what); exit(1); }
}
static int write_marker(const char *path) {
    int fd = open(path, O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    const char data[] = "FoldGPT kernel enforcement experiment\n";
    int saved = write(fd, data, sizeof(data) - 1) == sizeof(data) - 1 ? 0 : errno;
    if (close(fd) < 0 && !saved) saved = errno;
    errno = saved;
    return saved ? -1 : 0;
}
static void allow_path(int ruleset, const char *path, uint64_t access) {
    int fd = open(path, O_PATH | O_CLOEXEC);
    require(fd >= 0, "open rule path");
    struct landlock_path_beneath_attr rule = {.allowed_access = access, .parent_fd = fd};
    require(syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) == 0, "add rule");
    close(fd);
}
static void network_filter(void) {
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_AARCH64, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_socket, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {.len = sizeof(filter) / sizeof(filter[0]), .filter = filter};
    require(syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &program) == 0, "install diagnostic socket filter");
}
static void child_probe(void) {
    const uint64_t read_access = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;
    const uint64_t write_access = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
        LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR | LANDLOCK_ACCESS_FS_MAKE_DIR |
        LANDLOCK_ACCESS_FS_MAKE_REG | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
        LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM | LANDLOCK_ACCESS_FS_REFER |
        LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_IOCTL_DEV;
    struct landlock_ruleset_attr attr = {.handled_access_fs = read_access | write_access};
    int ruleset = syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0);
    require(ruleset >= 0, "create ruleset");
    allow_path(ruleset, "/", read_access);
    allow_path(ruleset, "workspace", read_access | write_access);
    /* This added read-only rule cannot subtract the parent's write grant. */
    allow_path(ruleset, "workspace/.git", read_access);
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "no new privileges");
    require(syscall(SYS_landlock_restrict_self, ruleset, 0) == 0, "restrict self");
    close(ruleset);
    network_filter();
    require(write_marker("workspace/allowed.txt") == 0, "allowed write");
    errno = 0;
    require(write_marker("outside/denied.txt") == -1 && errno == EACCES, "outside write must be denied");
    errno = 0;
    require(write_marker("workspace/outside-link/denied-link.txt") == -1 && errno == EACCES, "symlink write must be denied");
    errno = 0;
    require(socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0) == -1 && errno == EPERM, "socket must be denied");
    require(write_marker("workspace/.git/recursive-grant.txt") == 0, "metadata limitation measurement");
    pid_t grandchild = fork();
    require(grandchild >= 0, "fork inheritance");
    if (!grandchild) {
        errno = 0;
        _exit(write_marker("outside/denied-child.txt") == -1 && errno == EACCES ? 0 : 1);
    }
    int status;
    require(waitpid(grandchild, &status, 0) == grandchild && WIFEXITED(status) && WEXITSTATUS(status) == 0, "child inherits restrictions");
    pid_t exec_child = fork();
    require(exec_child >= 0, "fork native exec");
    if (!exec_child) {
        execl("/system/bin/sh", "sh", "-c", "printf 'native_readonly_exec=PASS\\n'", (char *)NULL);
        perror("native read-only exec");
        _exit(1);
    }
    require(waitpid(exec_child, &status, 0) == exec_child && WIFEXITED(status) && WEXITSTATUS(status) == 0, "native exec with Landlock");
    puts("allowed_write=PASS outside_denied=PASS symlink_denied=PASS fork_inheritance=PASS socket_denied=PASS");
    puts("metadata_protected=NO (recursive parent grant also permits .git despite its read-only rule)");
}
int main(int argc, char **argv) {
    setbuf(stdout, NULL);
    require(argc == 2, "usage: probe PRIVATE_PARENT_DIRECTORY");
    long abi = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    printf("uid=%u seccomp=%d landlock_abi=%ld\n", getuid(), prctl(PR_GET_SECCOMP), abi);
    require(abi >= 5, "Landlock ABI 5 required by this experiment");
    char path[4096];
    require(snprintf(path, sizeof(path), "%s/foldgpt-landlock-XXXXXX", argv[1]) < (int)sizeof(path), "path too long");
    require(mkdtemp(path) != NULL && chdir(path) == 0, "create private experiment");
    require(mkdir("workspace", 0700) == 0 && mkdir("outside", 0700) == 0 && mkdir("workspace/.git", 0700) == 0, "create experiment directories");
    require(symlink("../outside", "workspace/outside-link") == 0, "create experiment symlink");
    pid_t child = fork();
    require(child >= 0, "fork sandbox child");
    if (!child) { child_probe(); _exit(0); }
    int status;
    require(waitpid(child, &status, 0) == child, "wait for child");
    if (!WIFEXITED(status) || WEXITSTATUS(status)) {
        fprintf(stderr, "sandbox experiment failed, wait_status=%d\n", status); return 1;
    }
    require(access("workspace/allowed.txt", F_OK) == 0 && access("workspace/.git/recursive-grant.txt", F_OK) == 0, "independent allowed file verification");
    require(access("outside/denied.txt", F_OK) == -1 && errno == ENOENT, "independent denied file verification");
    require(access("outside/denied-link.txt", F_OK) == -1 && errno == ENOENT, "independent symlink verification");
    require(access("outside/denied-child.txt", F_OK) == -1 && errno == ENOENT, "independent child verification");
    printf("independent_parent_verification=PASS evidence_directory=%s\n", path);
    return 0;
}
