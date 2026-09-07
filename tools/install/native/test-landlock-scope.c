/* Actual nonroot ABI admission and filesystem behavior of a scope-only layer. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

int main(void)
{
    if (!getuid()) return 90;
    long abi = syscall(SYS_landlock_create_ruleset, NULL, 0, 1U);
    if (abi < 6) { perror("Landlock ABI 6 required"); return 91; }
    char fixture[] = "/var/tmp/foldgpt-scope-XXXXXXXX";
    if (!mkdtemp(fixture) || chdir(fixture) || mkdir("a", 0700) || mkdir("b", 0700)) return 92;
    int file = open("a/file", O_CREAT | O_RDWR | O_CLOEXEC, 0600);
    if (file < 0 || write(file, "sentinel\n", 9) != 9 || close(file)) return 93;
    struct { uint64_t fs, net, scoped; } attr = { .scoped = 3 };
    int ruleset = (int)syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0U);
    if (ruleset < 0) { perror("scope-only creation"); return 94; }
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) || syscall(SYS_landlock_restrict_self, ruleset, 0U)) {
        perror("scope-only restriction"); return 95;
    }
    close(ruleset);
    errno = 0;
    int result = rename("a/file", "b/file"), error = errno;
    printf("abi=%ld scope_only=active cross_directory_rename=%d errno=%d fixture=%s\n", abi, result, error, fixture);
    return result ? 96 : 0;
}
