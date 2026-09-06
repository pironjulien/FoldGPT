/* Test only native listener timing/FD receipt. Never calls the probe main,
 * PRoot, Codex, Landlock, seccomp, or any Android/device command.
 * Include the production code so the tested deadline/receipt helpers cannot
 * drift into an independent implementation. Build with the generated header.
 */
#define main foldgpt_codex_probe_main
#include "probe-landlock-codex.c"
#undef main

int main(void) {
    int sockets[2];
    require(socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, sockets) == 0,
            "create local listener test pair");
    struct timespec before, after;
    require(clock_gettime(CLOCK_MONOTONIC, &before) == 0, "read local test start");
    const struct timespec deadline = deadline_after_seconds(1);
    errno = 0;
    require(receive_fd(sockets[0], &deadline) < 0 && errno == ETIMEDOUT,
            "silent peer must reach the monotonic deadline");
    require(clock_gettime(CLOCK_MONOTONIC, &after) == 0, "read local test end");
    require(after.tv_sec > deadline.tv_sec ||
            (after.tv_sec == deadline.tv_sec && after.tv_nsec >= deadline.tv_nsec),
            "silent peer must not expire before its deadline");
    printf("PASS: silent peer timed out after %.3f monotonic seconds\n",
           (double)(after.tv_sec - before.tv_sec) +
           (double)(after.tv_nsec - before.tv_nsec) / 1000000000.0);

    int input = open("/dev/null", O_RDONLY | O_CLOEXEC);
    require(input >= 0 && send_fd(sockets[1], input) == 0,
            "queue a real descriptor after timeout");
    errno = 0;
    require(receive_fd(sockets[0], &deadline) < 0 && errno == ETIMEDOUT,
            "an expired deadline must not reset even with a queued descriptor");
    puts("PASS: expired absolute deadline remains expired");

    const struct timespec next_deadline = deadline_after_seconds(1);
    int received = receive_fd(sockets[0], &next_deadline);
    require(received >= 0, "receive the queued descriptor under a new deadline");
    struct stat original, transferred;
    require(fstat(input, &original) == 0 && fstat(received, &transferred) == 0
            && original.st_dev == transferred.st_dev && original.st_ino == transferred.st_ino
            && (fcntl(received, F_GETFD) & FD_CLOEXEC),
            "received descriptor identity and CLOEXEC");
    close(received);
    close(input);
    close(sockets[1]);
    errno = 0;
    require(receive_fd(sockets[0], &next_deadline) < 0 && errno == EPROTO,
            "peer close must report EOF without waiting for the deadline");
    close(sockets[0]);
    puts("PASS: real FD transfer preserved; closed peer rejected promptly");
    return 0;
}
