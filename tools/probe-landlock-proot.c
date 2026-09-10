#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/landlock.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <unistd.h>

/* Fixed diagnostic only: install the real filesystem restriction before PRoot
 * starts, so its APK loader and Android linker are covered by the host read
 * grant. Run one Linux shell against our own fixtures. Only the private PRoot
 * scratch directory is writable. This is not a general executor or a network,
 * IPC, process, or arbitrary-command sandbox. No account/profile is touched.
 */
static void require(int okay, const char *message) {
    if (!okay) { perror(message); exit(1); }
}
static void path_join(char out[PATH_MAX], const char *base, const char *suffix) {
    int length = snprintf(out, PATH_MAX, "%s/%s", base, suffix);
    require(length > 0 && length < PATH_MAX, "diagnostic path length");
}
static void allow_path(int ruleset, const char *path, uint64_t rights) {
    int fd = open(path, O_PATH | O_CLOEXEC);
    require(fd >= 0, "open rule path");
    struct landlock_path_beneath_attr rule = {.parent_fd = fd, .allowed_access = rights};
    require(syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) == 0,
            "add rule");
    close(fd);
}
static void restrict_filesystem(const char *scratch) {
    const uint64_t reads = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE
                         | LANDLOCK_ACCESS_FS_READ_DIR;
    const uint64_t writes = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR
        | LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR
        | LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG
        | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO
        | LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM
        | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_IOCTL_DEV;
    struct landlock_ruleset_attr attributes = {.handled_access_fs = reads | writes};
    int ruleset = syscall(SYS_landlock_create_ruleset, &attributes, sizeof(attributes), 0);
    require(ruleset >= 0, "create ruleset");
    allow_path(ruleset, "/", reads);
    allow_path(ruleset, scratch, reads | writes);
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "no new privileges");
    require(syscall(SYS_landlock_restrict_self, ruleset, 0) == 0, "enforce filesystem policy");
    close(ruleset);
}
int main(int argc, char **argv) {
    setbuf(stdout, NULL);
    if (argc != 3 || argv[1][0] != '/' || argv[2][0] != '/') {
        fprintf(stderr, "usage: probe APP_DATA_DIR APK_NATIVE_DIR\n");
        return 2;
    }
    long abi = syscall(SYS_landlock_create_ruleset, NULL, 0, LANDLOCK_CREATE_RULESET_VERSION);
    printf("uid=%u inherited_seccomp=%d landlock_abi=%ld\n", getuid(), prctl(PR_GET_SECCOMP), abi);
    require(abi >= 5, "Landlock ABI 5 required");
    char evidence[PATH_MAX], scratch[PATH_MAX], workspace[PATH_MAX], denied[PATH_MAX];
    char talloc[PATH_MAX], talloc_alias[PATH_MAX];
    path_join(evidence, argv[1], "cache/foldgpt-proot-policy-XXXXXX");
    require(mkdtemp(evidence) != NULL, "create own evidence tree");
    path_join(scratch, evidence, "scratch");
    path_join(workspace, evidence, "workspace");
    path_join(denied, workspace, "must-not-exist");
    require(mkdir(scratch, 0700) == 0 && mkdir(workspace, 0700) == 0, "create fixtures");
    path_join(talloc, argv[2], "libtalloc.so");
    path_join(talloc_alias, scratch, "libtalloc.so.2");
    require(symlink(talloc, talloc_alias) == 0, "create private versioned library alias");
    pid_t child = fork();
    require(child >= 0, "fork diagnostic");
    if (!child) {
        alarm(20);
        char proot[PATH_MAX], loader[PATH_MAX], loader32[PATH_MAX], root[PATH_MAX];
        char library_path[PATH_MAX * 2], scratch_bind[PATH_MAX + 32], workspace_bind[PATH_MAX + 32];
        path_join(proot, argv[2], "libproot.so");
        path_join(loader, argv[2], "libproot-loader.so");
        path_join(loader32, argv[2], "libproot-loader32.so");
        path_join(root, argv[1], "files/debian");
        int n = snprintf(library_path, sizeof(library_path), "%s:%s", scratch, argv[2]);
        require(n > 0 && n < (int)sizeof(library_path), "library search path length");
        snprintf(scratch_bind, sizeof(scratch_bind), "%s:/tmp", scratch);
        snprintf(workspace_bind, sizeof(workspace_bind), "%s:/foldgpt-fixture", workspace);
        require(clearenv() == 0, "clear inherited environment");
        require(setenv("LD_LIBRARY_PATH", library_path, 1) == 0
            && setenv("PROOT_LOADER", loader, 1) == 0
            && setenv("PROOT_LOADER_32", loader32, 1) == 0
            && setenv("PROOT_TMP_DIR", scratch, 1) == 0, "set diagnostic environment");
        restrict_filesystem(scratch);
        execl(proot, proot, "--kill-on-exit", "-r", root, "-w", "/foldgpt-fixture",
            "-b", "/dev", "-b", "/proc", "-b", "/system", "-b", "/apex",
            "-b", scratch_bind, "-b", workspace_bind, "-b", "/dev/null:/etc/ld.so.preload",
            "/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "HOME=/foldgpt-fixture", "LANG=C.UTF-8",
            "/bin/sh", "-c",
            "printf 'linux_shell_exec=PASS\\n'; "
            "if printf forbidden > /foldgpt-fixture/must-not-exist; then exit 17; fi; "
            "printf 'linux_write_denied=PASS\\n'",
            (char *)NULL);
        perror("exec native PRoot");
        _exit(1);
    }
    int status;
    require(waitpid(child, &status, 0) == child, "wait for diagnostic");
    printf("child_wait_status=%d evidence_directory=%s\n", status, evidence);
    require(WIFEXITED(status) && WEXITSTATUS(status) == 0, "fixed Linux command completed");
    struct stat value;
    errno = 0;
    require(lstat(denied, &value) < 0 && errno == ENOENT, "independent denied file check");
    puts("independent_parent_verification=PASS");
    return 0;
}
