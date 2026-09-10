#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

/* Harmless isolation check using only a disposable marker created by this test.
 * Run inside the experimental PRoot container, never against user documents.
 * The raw AArch64 call observes the kernel through PRoot, without libc hooks.
 */
static long raw_unshare(unsigned long flags) {
#if defined(__aarch64__)
    register unsigned long x0 __asm__("x0") = flags;
    register unsigned long x8 __asm__("x8") = 97; /* AArch64 __NR_unshare */
    __asm__ volatile("svc 0" : "+r"(x0) : "r"(x8) : "memory", "cc");
    return (long)x0;
#else
#error This diagnostic targets AArch64 only
#endif
}

int main(void) {
    char base[] = "/tmp/fold-isolation-audit-XXXXXX";
    char empty[256], marker[256];
    if (!mkdtemp(base)) { perror("mkdtemp"); return 2; }
    snprintf(empty, sizeof(empty), "%s/empty", base);
    snprintf(marker, sizeof(marker), "%s/outside-marker", base);
    if (mkdir(empty, 0700)) return 2;
    int fd = open(marker, O_CREAT | O_EXCL | O_WRONLY, 0600);
    if (fd < 0) return 2;
    if (write(fd, "AUDIT_ONLY\n", 11) != 11) return 2;
    close(fd);

    errno = 0;
    int libc_ns = unshare(CLONE_NEWUSER);
    int libc_errno = errno;
    long kernel_ns = raw_unshare(CLONE_NEWUSER);
    printf("libc_unshare=%d errno=%d; raw_unshare=%ld\n",
           libc_ns, libc_errno, kernel_ns);
    errno = 0;
    int jail = chroot(empty);
    int jail_errno = errno;
    fd = open(marker, O_RDONLY);
    printf("chroot_empty=%d errno=%d; outside_marker_accessible=%s\n",
           jail, jail_errno, fd >= 0 ? "YES" : "NO");
    if (fd >= 0) close(fd);
    /* If chroot really succeeded these absolute paths no longer resolve. */
    unlink(marker);
    rmdir(empty);
    rmdir(base);
    return 0;
}
