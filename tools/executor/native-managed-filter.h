/* SPDX-License-Identifier: GPL-3.0-only */
#ifndef FOLDGPT_NATIVE_MANAGED_FILTER_H
#define FOLDGPT_NATIVE_MANAGED_FILTER_H
/* Stacked above the unchanged native-runner data filter. USER_NOTIF mediates
 * every admitted acquisition. Namespace/cwd/path-metadata operations remain
 * explicitly unsupported by this first private process profile. The initial
 * permissive default allows the trusted bootstrap to send its listener and
 * install the existing stricter allowlist before any target userspace runs.
 */
#include <linux/seccomp.h>
#include <sys/ioctl.h>
#include <sys/socket.h>
#include <linux/openat2.h>
#include <sys/uio.h>
#include <elf.h>
#include <inttypes.h>
#if defined(__aarch64__)
#define MG_ARCH AUDIT_ARCH_AARCH64
#else
#define MG_ARCH AUDIT_ARCH_X86_64
#endif
#define MG_DENY(name) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_##name, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM)
#define MG_ACQUIRE(name) BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_##name, 0, 1), BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF)
static int mg_notification_filter(void) {
    const struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, MG_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#if defined(__x86_64__)
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x40000000U, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
#endif
#ifdef __NR_open
        MG_ACQUIRE(open),
#endif
        MG_ACQUIRE(openat), MG_ACQUIRE(openat2),
#ifdef __NR_creat
        MG_ACQUIRE(creat),
#endif
        MG_DENY(chdir), MG_DENY(fchdir),
        MG_DENY(mkdirat), MG_DENY(unlinkat), MG_DENY(renameat),
        MG_DENY(renameat2), MG_DENY(linkat), MG_DENY(symlinkat),
        MG_DENY(readlinkat), MG_DENY(faccessat), MG_DENY(faccessat2),
        MG_DENY(getdents64), MG_DENY(newfstatat), MG_DENY(statx), MG_DENY(statfs),
        MG_DENY(truncate),
#ifdef __NR_mkdir
        MG_DENY(mkdir), MG_DENY(rmdir), MG_DENY(unlink), MG_DENY(rename),
        MG_DENY(link), MG_DENY(symlink), MG_DENY(readlink), MG_DENY(access),
        MG_DENY(getdents), MG_DENY(stat), MG_DENY(lstat),
#endif
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
    };
    struct sock_fprog program = {.len=(unsigned short)(sizeof(filter)/sizeof(filter[0])), .filter=(struct sock_filter *)filter};
    return (int)syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER, SECCOMP_FILTER_FLAG_NEW_LISTENER, &program);
}
#endif
