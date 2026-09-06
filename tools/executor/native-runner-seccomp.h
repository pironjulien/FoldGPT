#ifndef FOLDGPT_NATIVE_RUNNER_SECCOMP_H
#define FOLDGPT_NATIVE_RUNNER_SECCOMP_H

/*
 * Bounded landlock-basic-data-v1 syscall profile, not a managed-policy engine.
 *
 * The caller must already have installed no_new_privs, a Landlock ABI >= 6
 * domain with LANDLOCK_SCOPE_SIGNAL, fixed hard resource limits, and a fresh
 * supervised process group. Only the command's private stdin/stdout/stderr and
 * a close-on-exec setup-error pipe may remain open. This function does not
 * establish any of those prerequisites. On failure the caller must fail closed.
 * Grants must exclude pre-existing FIFO/device/socket files and magic-link
 * filesystems, including entries reachable through directory grants. Ordinary
 * open/read/write syscalls cannot filter file types: that is a caller invariant.
 *
 * Landlock supplies pathname/data enforcement. This filter admits path metadata
 * queries, ordinary data/namespace changes and exec, but not ownership, mode,
 * timestamp or xattr mutation. New files use their creation mode and umask.
 * No sockets (including socketpair), foreign-memory/FD interfaces, SysV/POSIX IPC,
 * namespace/mount interfaces, io_uring, keyrings, BPF, perf or userfaultfd are
 * admitted. mmap and threads may still share allowed file data; this is not
 * confidentiality between descendants within the same Landlock domain.
 *
 * Compile only for native little-endian x86_64 or AArch64. Compat and x32
 * syscall ABIs are killed, not allowed to fall through a different number table.
 */

#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <signal.h>
#include <stddef.h>
#include <stdint.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/sched.h>
#include <linux/seccomp.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#if !defined(__BYTE_ORDER__) || __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
#error "native-runner seccomp supports only little-endian syscall arguments"
#endif

#if defined(__x86_64__) && !defined(__ILP32__)
#include <asm/prctl.h>
#define NR_SC_ARCH AUDIT_ARCH_X86_64
#elif defined(__aarch64__) && !defined(__ILP32__)
#define NR_SC_ARCH AUDIT_ARCH_AARCH64
#else
#error "native-runner seccomp supports only native x86_64 and AArch64"
#endif

#define NR_SC_DENY (SECCOMP_RET_ERRNO | (EPERM & SECCOMP_RET_DATA))
#define NR_SC_ARG_LO(n) ((uint32_t)(offsetof(struct seccomp_data, args) + 8U * (n)))
#define NR_SC_ARG_HI(n) (NR_SC_ARG_LO(n) + 4U)
#define NR_SC_ALLOW_NR(n) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (n), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)
#define NR_SC_ALLOW(name) NR_SC_ALLOW_NR(__NR_##name)
#define NR_SC_SELF_QUERY(name) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_##name, 0, 6), \
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_HI(0)), \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 3), \
    BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_LO(0)), \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW), \
    BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY)

/* No CLONE_PARENT, CLONE_PIDFD, CLONE_PTRACE, CLONE_UNTRACED, namespaces,
 * CLONE_IO or obsolete CLONE_DETACHED. The kernel also validates combinations.
 * The low byte is separately restricted to 0 or SIGCHLD. CLONE_SYSVSEM is a
 * normal pthread flag; no System V IPC syscalls are available to use it.
 */
#define NR_SC_CLONE_FLAGS ((uint32_t)(CLONE_VM | CLONE_FS | CLONE_FILES | \
    CLONE_SIGHAND | CLONE_THREAD | CLONE_SYSVSEM | CLONE_SETTLS | \
    CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID | CLONE_CHILD_SETTID | CLONE_VFORK))

static int nr_install_seccomp(void)
{
    const struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, NR_SC_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#if defined(__x86_64__)
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K, 0x40000000U, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
#endif

#ifdef __NR_clone3
        /* libc falls back to the inspectable legacy clone argument layout. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_clone3, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
#endif
#ifdef __NR_clone
        /* Nine instructions, all branches terminate inside this block. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_clone, 0, 9),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_HI(0)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 6),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_LO(0)),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K,
                 (uint32_t)~(NR_SC_CLONE_FLAGS | 0xffU), 4, 0),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K, 0xffU),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SIGCHLD, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY),
#endif
#ifdef __NR_prlimit64
        /* Only self. Hard limits must already prevent later soft-limit raises. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_prlimit64, 0, 6),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_HI(0)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 3),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_LO(0)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY),
#endif
        /* Bionic __init_thread calls sched_getscheduler(0) and, when needed,
         * sched_getparam(0) to inherit the calling thread's policy. Zero has
         * kernel-defined self semantics after fork and on every new thread.
         * Never bake the pre-exec PID into a filter inherited by descendants.
         * All explicit PIDs/TIDs, including a numeric self PID, are refused.
         */
#ifdef __NR_sched_getscheduler
        NR_SC_SELF_QUERY(sched_getscheduler),
#endif
#ifdef __NR_sched_getparam
        NR_SC_SELF_QUERY(sched_getparam),
#endif
#ifdef __NR_sched_getaffinity
        NR_SC_SELF_QUERY(sched_getaffinity),
#endif
#ifdef __NR_fcntl
        /* cmd is a kernel int. Do not admit locks, leases, F_NOTIFY, F_SETOWN,
         * F_SETSIG, F_ADD_SEALS or pipe resizing. Only private FD operations.
         * Seven commands => load + 14 compare/return + deny = 16 instructions.
         */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_fcntl, 0, 16),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_LO(1)),
        NR_SC_ALLOW_NR(F_DUPFD),
        NR_SC_ALLOW_NR(F_DUPFD_CLOEXEC),
        NR_SC_ALLOW_NR(F_GETFD),
        NR_SC_ALLOW_NR(F_SETFD),
        NR_SC_ALLOW_NR(F_GETFL),
        NR_SC_ALLOW_NR(F_SETFL),
        NR_SC_ALLOW_NR(F_GETPIPE_SZ),
        BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY),
#endif
#ifdef __NR_prctl
        /* Read-only process queries and the calling thread's display name.
         * No dumpability/capability/seccomp/subreaper/privilege-policy changes.
         * Twelve commands => load + 24 compare/return + deny = 26 instructions.
         */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_prctl, 0, 26),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_LO(0)),
        NR_SC_ALLOW_NR(PR_GET_DUMPABLE),
        NR_SC_ALLOW_NR(PR_GET_KEEPCAPS),
        NR_SC_ALLOW_NR(PR_GET_NAME),
        NR_SC_ALLOW_NR(PR_SET_NAME),
        NR_SC_ALLOW_NR(PR_GET_SECCOMP),
        NR_SC_ALLOW_NR(PR_CAPBSET_READ),
        NR_SC_ALLOW_NR(PR_GET_SECUREBITS),
        NR_SC_ALLOW_NR(PR_GET_TIMERSLACK),
        NR_SC_ALLOW_NR(PR_GET_CHILD_SUBREAPER),
        NR_SC_ALLOW_NR(PR_GET_NO_NEW_PRIVS),
        NR_SC_ALLOW_NR(PR_GET_THP_DISABLE),
        NR_SC_ALLOW_NR(PR_GET_TID_ADDRESS),
        BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY),
#endif
#ifdef __NR_arch_prctl
        /* x86 loader TLS setup and architecture queries only. In particular,
         * do not map a compat vDSO or change CET/CPUID/tagged-address policies.
         * Seven commands => load + 14 compare/return + deny = 16 instructions.
         */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_arch_prctl, 0, 16),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, NR_SC_ARG_LO(0)),
        NR_SC_ALLOW_NR(ARCH_SET_FS),
        NR_SC_ALLOW_NR(ARCH_SET_GS),
        NR_SC_ALLOW_NR(ARCH_GET_FS),
        NR_SC_ALLOW_NR(ARCH_GET_GS),
        NR_SC_ALLOW_NR(ARCH_GET_CPUID),
        NR_SC_ALLOW_NR(ARCH_GET_XCOMP_SUPP),
        NR_SC_ALLOW_NR(ARCH_GET_XCOMP_PERM),
        BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY),
#endif

        /* Dynamic loader, libc and process-local memory. No memfd_create,
         * userfaultfd, process_madvise, process_mrelease or executable handles.
         */
#ifdef __NR_brk
        NR_SC_ALLOW(brk),
#endif
#ifdef __NR_mmap
        NR_SC_ALLOW(mmap),
#endif
#ifdef __NR_mprotect
        NR_SC_ALLOW(mprotect),
#endif
#ifdef __NR_munmap
        NR_SC_ALLOW(munmap),
#endif
#ifdef __NR_mremap
        NR_SC_ALLOW(mremap),
#endif
#ifdef __NR_madvise
        NR_SC_ALLOW(madvise),
#endif
#ifdef __NR_msync
        NR_SC_ALLOW(msync),
#endif
#ifdef __NR_set_tid_address
        NR_SC_ALLOW(set_tid_address),
#endif
#ifdef __NR_set_robust_list
        NR_SC_ALLOW(set_robust_list),
#endif
#ifdef __NR_rseq
        NR_SC_ALLOW(rseq),
#endif
#ifdef __NR_futex
        NR_SC_ALLOW(futex),
#endif
#ifdef __NR_futex_waitv
        NR_SC_ALLOW(futex_waitv),
#endif
#ifdef __NR_getrandom
        NR_SC_ALLOW(getrandom),
#endif

        /* The command can execute only under its inherited Landlock domain.
         * fork/vfork cannot alter its process group; clone is checked above.
         */
#ifdef __NR_execve
        NR_SC_ALLOW(execve),
#endif
#ifdef __NR_execveat
        NR_SC_ALLOW(execveat),
#endif
#ifdef __NR_fork
        NR_SC_ALLOW(fork),
#endif
#ifdef __NR_vfork
        NR_SC_ALLOW(vfork),
#endif
#ifdef __NR_exit
        NR_SC_ALLOW(exit),
#endif
#ifdef __NR_exit_group
        NR_SC_ALLOW(exit_group),
#endif
#ifdef __NR_wait4
        NR_SC_ALLOW(wait4),
#endif
#ifdef __NR_waitid
        NR_SC_ALLOW(waitid),
#endif
#ifdef __NR_restart_syscall
        NR_SC_ALLOW(restart_syscall),
#endif
#ifdef __NR_kill
        NR_SC_ALLOW(kill),
#endif
#ifdef __NR_tkill
        NR_SC_ALLOW(tkill),
#endif
#ifdef __NR_tgkill
        NR_SC_ALLOW(tgkill),
#endif
#ifdef __NR_rt_sigaction
        NR_SC_ALLOW(rt_sigaction),
#endif
#ifdef __NR_rt_sigprocmask
        NR_SC_ALLOW(rt_sigprocmask),
#endif
#ifdef __NR_rt_sigreturn
        NR_SC_ALLOW(rt_sigreturn),
#endif
#ifdef __NR_rt_sigpending
        NR_SC_ALLOW(rt_sigpending),
#endif
#ifdef __NR_rt_sigsuspend
        NR_SC_ALLOW(rt_sigsuspend),
#endif
#ifdef __NR_rt_sigtimedwait
        NR_SC_ALLOW(rt_sigtimedwait),
#endif
#ifdef __NR_sigaltstack
        NR_SC_ALLOW(sigaltstack),
#endif
#ifdef __NR_pause
        NR_SC_ALLOW(pause),
#endif

        /* Filesystem data and namespace operations are checked by Landlock.
         * Mode/owner/time/xattr setters, mknod, ioctl, flock and handle-based
         * opens stay denied. Metadata queries are explicitly in this profile.
         */
#ifdef __NR_open
        NR_SC_ALLOW(open),
#endif
#ifdef __NR_openat
        NR_SC_ALLOW(openat),
#endif
#ifdef __NR_openat2
        NR_SC_ALLOW(openat2),
#endif
#ifdef __NR_creat
        NR_SC_ALLOW(creat),
#endif
#ifdef __NR_close
        NR_SC_ALLOW(close),
#endif
#ifdef __NR_close_range
        NR_SC_ALLOW(close_range),
#endif
#ifdef __NR_read
        NR_SC_ALLOW(read),
#endif
#ifdef __NR_write
        NR_SC_ALLOW(write),
#endif
#ifdef __NR_readv
        NR_SC_ALLOW(readv),
#endif
#ifdef __NR_writev
        NR_SC_ALLOW(writev),
#endif
#ifdef __NR_pread64
        NR_SC_ALLOW(pread64),
#endif
#ifdef __NR_pwrite64
        NR_SC_ALLOW(pwrite64),
#endif
#ifdef __NR_preadv
        NR_SC_ALLOW(preadv),
#endif
#ifdef __NR_pwritev
        NR_SC_ALLOW(pwritev),
#endif
#ifdef __NR_preadv2
        NR_SC_ALLOW(preadv2),
#endif
#ifdef __NR_pwritev2
        NR_SC_ALLOW(pwritev2),
#endif
#ifdef __NR_lseek
        NR_SC_ALLOW(lseek),
#endif
#ifdef __NR_dup
        NR_SC_ALLOW(dup),
#endif
#ifdef __NR_dup2
        NR_SC_ALLOW(dup2),
#endif
#ifdef __NR_dup3
        NR_SC_ALLOW(dup3),
#endif
#ifdef __NR_pipe
        NR_SC_ALLOW(pipe),
#endif
#ifdef __NR_pipe2
        NR_SC_ALLOW(pipe2),
#endif
#ifdef __NR_poll
        NR_SC_ALLOW(poll),
#endif
#ifdef __NR_ppoll
        NR_SC_ALLOW(ppoll),
#endif
#ifdef __NR_select
        NR_SC_ALLOW(select),
#endif
#ifdef __NR_pselect6
        NR_SC_ALLOW(pselect6),
#endif
#ifdef __NR_sendfile
        NR_SC_ALLOW(sendfile),
#endif
#ifdef __NR_copy_file_range
        NR_SC_ALLOW(copy_file_range),
#endif
#ifdef __NR_splice
        NR_SC_ALLOW(splice),
#endif
#ifdef __NR_tee
        NR_SC_ALLOW(tee),
#endif
#ifdef __NR_vmsplice
        NR_SC_ALLOW(vmsplice),
#endif
#ifdef __NR_fsync
        NR_SC_ALLOW(fsync),
#endif
#ifdef __NR_fdatasync
        NR_SC_ALLOW(fdatasync),
#endif
#ifdef __NR_sync_file_range
        NR_SC_ALLOW(sync_file_range),
#endif
#ifdef __NR_fadvise64
        NR_SC_ALLOW(fadvise64),
#endif
#ifdef __NR_truncate
        NR_SC_ALLOW(truncate),
#endif
#ifdef __NR_ftruncate
        NR_SC_ALLOW(ftruncate),
#endif
#ifdef __NR_fallocate
        NR_SC_ALLOW(fallocate),
#endif
#ifdef __NR_getcwd
        NR_SC_ALLOW(getcwd),
#endif
#ifdef __NR_chdir
        NR_SC_ALLOW(chdir),
#endif
#ifdef __NR_fchdir
        NR_SC_ALLOW(fchdir),
#endif
#ifdef __NR_umask
        NR_SC_ALLOW(umask),
#endif
#ifdef __NR_mkdir
        NR_SC_ALLOW(mkdir),
#endif
#ifdef __NR_mkdirat
        NR_SC_ALLOW(mkdirat),
#endif
#ifdef __NR_rmdir
        NR_SC_ALLOW(rmdir),
#endif
#ifdef __NR_unlink
        NR_SC_ALLOW(unlink),
#endif
#ifdef __NR_unlinkat
        NR_SC_ALLOW(unlinkat),
#endif
#ifdef __NR_rename
        NR_SC_ALLOW(rename),
#endif
#ifdef __NR_renameat
        NR_SC_ALLOW(renameat),
#endif
#ifdef __NR_renameat2
        NR_SC_ALLOW(renameat2),
#endif
#ifdef __NR_link
        NR_SC_ALLOW(link),
#endif
#ifdef __NR_linkat
        NR_SC_ALLOW(linkat),
#endif
#ifdef __NR_symlink
        NR_SC_ALLOW(symlink),
#endif
#ifdef __NR_symlinkat
        NR_SC_ALLOW(symlinkat),
#endif
#ifdef __NR_readlink
        NR_SC_ALLOW(readlink),
#endif
#ifdef __NR_readlinkat
        NR_SC_ALLOW(readlinkat),
#endif
#ifdef __NR_access
        NR_SC_ALLOW(access),
#endif
#ifdef __NR_faccessat
        NR_SC_ALLOW(faccessat),
#endif
#ifdef __NR_faccessat2
        NR_SC_ALLOW(faccessat2),
#endif
#ifdef __NR_getdents
        NR_SC_ALLOW(getdents),
#endif
#ifdef __NR_getdents64
        NR_SC_ALLOW(getdents64),
#endif
#ifdef __NR_stat
        NR_SC_ALLOW(stat),
#endif
#ifdef __NR_lstat
        NR_SC_ALLOW(lstat),
#endif
#ifdef __NR_fstat
        NR_SC_ALLOW(fstat),
#endif
#ifdef __NR_newfstatat
        NR_SC_ALLOW(newfstatat),
#endif
#ifdef __NR_statx
        NR_SC_ALLOW(statx),
#endif
#ifdef __NR_statfs
        NR_SC_ALLOW(statfs),
#endif
#ifdef __NR_fstatfs
        NR_SC_ALLOW(fstatfs),
#endif

        /* Identity, clocks and resource queries. No credential changes,
         * scheduling changes, setrlimit, process-group or session changes.
         */
#ifdef __NR_getpid
        NR_SC_ALLOW(getpid),
#endif
#ifdef __NR_getppid
        NR_SC_ALLOW(getppid),
#endif
#ifdef __NR_gettid
        NR_SC_ALLOW(gettid),
#endif
#ifdef __NR_getuid
        NR_SC_ALLOW(getuid),
#endif
#ifdef __NR_geteuid
        NR_SC_ALLOW(geteuid),
#endif
#ifdef __NR_getgid
        NR_SC_ALLOW(getgid),
#endif
#ifdef __NR_getegid
        NR_SC_ALLOW(getegid),
#endif
#ifdef __NR_getresuid
        NR_SC_ALLOW(getresuid),
#endif
#ifdef __NR_getresgid
        NR_SC_ALLOW(getresgid),
#endif
#ifdef __NR_getgroups
        NR_SC_ALLOW(getgroups),
#endif
#ifdef __NR_getpgrp
        NR_SC_ALLOW(getpgrp),
#endif
#ifdef __NR_getpgid
        NR_SC_ALLOW(getpgid),
#endif
#ifdef __NR_getsid
        NR_SC_ALLOW(getsid),
#endif
#ifdef __NR_uname
        NR_SC_ALLOW(uname),
#endif
#ifdef __NR_sysinfo
        NR_SC_ALLOW(sysinfo),
#endif
#ifdef __NR_getrlimit
        NR_SC_ALLOW(getrlimit),
#endif
#ifdef __NR_getrusage
        NR_SC_ALLOW(getrusage),
#endif
#ifdef __NR_times
        NR_SC_ALLOW(times),
#endif
#ifdef __NR_gettimeofday
        NR_SC_ALLOW(gettimeofday),
#endif
#ifdef __NR_time
        NR_SC_ALLOW(time),
#endif
#ifdef __NR_clock_gettime
        NR_SC_ALLOW(clock_gettime),
#endif
#ifdef __NR_clock_getres
        NR_SC_ALLOW(clock_getres),
#endif
#ifdef __NR_nanosleep
        NR_SC_ALLOW(nanosleep),
#endif
#ifdef __NR_clock_nanosleep
        NR_SC_ALLOW(clock_nanosleep),
#endif
#ifdef __NR_sched_yield
        NR_SC_ALLOW(sched_yield),
#endif
#ifdef __NR_getcpu
        NR_SC_ALLOW(getcpu),
#endif

        BPF_STMT(BPF_RET | BPF_K, NR_SC_DENY)
    };
    struct sock_fprog program = {
        .len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
        .filter = (struct sock_filter *)filter
    };
    _Static_assert(sizeof(filter) / sizeof(filter[0]) <= USHRT_MAX,
                   "seccomp program length exceeds sock_fprog");
    _Static_assert(sizeof(filter) / sizeof(filter[0]) <= BPF_MAXINSNS,
                   "seccomp program exceeds the kernel instruction limit");

    /* TSYNC also fails closed if an unexpectedly present thread cannot inherit
     * the filter. Such failure can return its positive TID instead of -1.
     */
    long result = syscall(__NR_seccomp, SECCOMP_SET_MODE_FILTER,
                          SECCOMP_FILTER_FLAG_TSYNC, &program);
    if (result == 0)
        return 0;
    if (result > 0)
        errno = EBUSY;
    return -1;
}

#undef NR_SC_CLONE_FLAGS
#undef NR_SC_ALLOW
#undef NR_SC_SELF_QUERY
#undef NR_SC_ALLOW_NR
#undef NR_SC_ARG_HI
#undef NR_SC_ARG_LO
#undef NR_SC_DENY
#undef NR_SC_ARCH

#endif /* FOLDGPT_NATIVE_RUNNER_SECCOMP_H */
