/* libc compatibility for the native FoldGPT supervisor's mediated directory FDs.
 * This library grants no authority: raw chdir stays denied by seccomp, and
 * openat is approved and executed by the supervisor before fchdir can run.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <sys/syscall.h>
#include <unistd.h>

__attribute__((visibility("default")))
int chdir(const char *path) {
    /* SECCOMP_IOCTL_NOTIF_ADDFD cannot inject O_PATH descriptors (EBADF).
     * O_RDONLY intentionally requires directory readability as well as search
     * permission, matching the executor's admitted directory profile.
     * syscall wrappers, unlike libc open/close, are not cancellation points.
     */
    int saved_errno = errno;
    int directory = (int)syscall(SYS_openat, AT_FDCWD, path,
                                O_RDONLY | O_DIRECTORY | O_CLOEXEC, 0);
    if (directory < 0) return -1;
    int result = (int)syscall(SYS_fchdir, directory);
    int result_errno = result < 0 ? errno : saved_errno;
    /* Never retry close on EINTR: the descriptor may already have been reused.
     * The descriptor is close-on-exec even if a concurrent thread execs here.
     */
    (void)syscall(SYS_close, directory);
    errno = result_errno;
    return result;
}
