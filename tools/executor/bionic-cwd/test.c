/* Actual nonroot libc calls under a kernel filter that refuses raw chdir.
 * This narrow filter verifies compatibility; it is not the production sandbox.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

#define CHECK(expression) do { if (!(expression)) { \
    fprintf(stderr, "%s:%d: %s (errno=%d)\n", __FILE__, __LINE__, #expression, errno); \
    exit(1); } } while (0)

static void deny_raw_chdir(void) {
    struct sock_filter instructions[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_chdir, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {
        .len = sizeof(instructions) / sizeof(instructions[0]),
        .filter = instructions,
    };
    CHECK(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0);
    CHECK(syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, 0, &program) == 0);
}

static int descriptors(void) {
    DIR *directory = opendir("/proc/self/fd");
    CHECK(directory != NULL);
    int count = 0;
    struct dirent *entry;
    while ((entry = readdir(directory)) != NULL) {
        if (strcmp(entry->d_name, ".") && strcmp(entry->d_name, "..")) ++count;
    }
    CHECK(closedir(directory) == 0);
    return count;
}

int main(int argc, char **argv) {
    CHECK(argc == 3);
    CHECK(getuid() != 0 && geteuid() == getuid());
    CHECK(syscall(SYS_chdir, argv[2]) == 0);
    if (!strcmp(argv[1], "baseline")) {
        deny_raw_chdir();
        CHECK(chdir(".") == -1 && errno == EPERM);
        puts("baseline: libc chdir is refused by the kernel");
        return 0;
    }
    CHECK(!strcmp(argv[1], "shim"));
    CHECK(mkdir("child", 0700) == 0);
    CHECK(mkdir("search_only", 0111) == 0);
    CHECK(mkdir("read_only", 0444) == 0);
    /* Prove the documented restriction: kernel chdir accepts a searchable,
     * unreadable directory; our deliberately narrower O_RDONLY profile does not.
     */
    CHECK(syscall(SYS_chdir, "search_only") == 0);
    CHECK(syscall(SYS_chdir, "..") == 0);
    int file = open("ordinary_file", O_WRONLY | O_CREAT | O_EXCL, 0600);
    CHECK(file >= 0 && close(file) == 0);
    char original[4096], actual[4096];
    CHECK(getcwd(original, sizeof(original)) != NULL);
    int initial_descriptors = descriptors();
    deny_raw_chdir();
    CHECK(chdir("child") == 0);
    file = open("actual_child_output", O_WRONLY | O_CREAT | O_EXCL, 0600);
    CHECK(file >= 0 && write(file, "42", 2) == 2 && close(file) == 0);
    CHECK(chdir("..") == 0);
    CHECK(access("child/actual_child_output", F_OK) == 0);
    CHECK(getcwd(actual, sizeof(actual)) && !strcmp(original, actual));
    CHECK(chdir("absent") == -1 && errno == ENOENT);
    CHECK(chdir("ordinary_file") == -1 && errno == ENOTDIR);
    CHECK(chdir("search_only") == -1 && errno == EACCES);
    /* Acquisition succeeds here, but fchdir must preserve its own EACCES and
     * close the temporary descriptor because directory search is forbidden. */
    CHECK(chdir("read_only") == -1 && errno == EACCES);
    CHECK(chdir((const char *)(uintptr_t)1) == -1 && errno == EFAULT);
    CHECK(syscall(SYS_chdir, "child") == -1 && errno == EPERM);
    CHECK(getcwd(actual, sizeof(actual)) && !strcmp(original, actual));
    for (int i = 0; i < 256; ++i) {
        CHECK(chdir("child") == 0 && chdir("..") == 0);
        CHECK(chdir("absent") == -1 && errno == ENOENT);
        CHECK(chdir("read_only") == -1 && errno == EACCES);
    }
    CHECK(descriptors() == initial_descriptors);
    /* A full FD table is a real failure. Do not report a successful cwd change. */
    struct rlimit old_limit, limited;
    CHECK(getrlimit(RLIMIT_NOFILE, &old_limit) == 0);
    limited = old_limit;
    limited.rlim_cur = 32;
    CHECK(setrlimit(RLIMIT_NOFILE, &limited) == 0);
    int opened[32], count = 0, next;
    while ((next = open("ordinary_file", O_RDONLY)) >= 0) {
        CHECK(count < 32);
        opened[count++] = next;
    }
    CHECK(errno == EMFILE);
    CHECK(chdir("child") == -1 && errno == EMFILE);
    CHECK(getcwd(actual, sizeof(actual)) && !strcmp(original, actual));
    while (count) CHECK(close(opened[--count]) == 0);
    CHECK(setrlimit(RLIMIT_NOFILE, &old_limit) == 0);
    CHECK(descriptors() == initial_descriptors);
    puts("shim: real cwd, relative IO, denial errno, raw syscall denial and descriptor lifetime passed");
    return 0;
}
