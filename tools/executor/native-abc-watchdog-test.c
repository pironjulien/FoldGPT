/* SPDX-License-Identifier: GPL-3.0-only
 * Exercise the real supervisor timeout with a blocked fixed worker.
 */
#define main native_abc_program_main
#include "native-abc-probe.c"
#undef main

int main(void)
{
    int abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0, LL_VERSION);
    if (abi < 6) {
        fprintf(stderr, "FAIL: watchdog test requires Landlock ABI >= 6\n");
        return 1;
    }
    char directory_path[] = "/tmp/foldgpt-native-abc-watchdog-XXXXXX";
    if (!mkdtemp(directory_path))
        return 1;
    struct fixture_file files[3] = {
        {.name = "blocked-target.fifo"},
        {.name = "permitted-control.txt"},
        {.name = "unused-excluded.txt"},
    };
    int directory = open(directory_path, O_DIRECTORY | O_RDONLY | O_CLOEXEC);
    int result = 1;
    if (directory < 0)
        goto cleanup;
    for (int i = 0; i < 3; i++) {
        int n = snprintf(files[i].path, sizeof(files[i].path), "%s/%s", directory_path, files[i].name);
        if (n < 0 || (size_t)n >= sizeof(files[i].path))
            goto cleanup;
    }
    if (mkfifoat(directory, files[0].name, 0600) < 0)
        goto cleanup;
    files[0].created = 1;
    int fd = openat(directory, files[1].name, O_CREAT | O_EXCL | O_WRONLY | O_CLOEXEC, 0600);
    if (fd < 0)
        goto cleanup;
    files[1].created = 1;
    int wrote = write_all(fd, control_bytes, strlen(control_bytes));
    close(fd);
    if (wrote < 0)
        goto cleanup;
    struct report report = {0};
    int64_t started = monotonic_ms();
    /* B permits this exact FIFO's read. Its blocking open has no writer. */
    int outcome = run_worker(1, abi, files, violation_bytes, &report);
    int failure = errno;
    int64_t elapsed = monotonic_ms() - started;
    int status;
    int no_child = waitpid(-1, &status, WNOHANG) == -1 && errno == ECHILD;
    if (outcome != -1 || failure != ETIMEDOUT || !no_child ||
        elapsed < WORKER_TIMEOUT_MS || elapsed > WORKER_TIMEOUT_MS + REAP_TIMEOUT_MS) {
        fprintf(stderr, "FAIL: watchdog result=%d errno=%d elapsed=%lld no_child=%d\n",
                outcome, failure, (long long)elapsed, no_child);
        goto cleanup;
    }
    printf("PASS: blocked native worker timed out after %lldms and was reaped\n", (long long)elapsed);
    result = 0;
cleanup:
    if (directory >= 0) {
        for (int i = 0; i < 3; i++) {
            if (files[i].created && unlinkat(directory, files[i].name, 0) < 0)
                result = 1;
        }
        close(directory);
    }
    if (rmdir(directory_path) < 0)
        result = 1;
    return result;
}
