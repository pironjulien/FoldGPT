/* Separate GNU syscall profile, frozen from the real Android GNU test. */
#define ALLOW_SYSCALL(number) \
    BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (number), 0, 1), \
    BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW)

static int gnu_notification_filter(void) {
    /* Read-only opens stay kernel-enforced; writing opens must reach the broker.
     * No notification is ever continued against mutable tracee arguments. */
    struct sock_filter filter[] = {
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, MG_ARCH, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Standard descriptor queries and nonblocking mode used by Rust pipes.
         * FIONBIO changes only an existing FD's mode, like allowed fcntl;
         * all device-specific ioctls still go to a refusal, never CONTINUE. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_ioctl, 0, 15),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        ALLOW_SYSCALL(TCGETS),
        ALLOW_SYSCALL(FIONREAD),
        ALLOW_SYSCALL(FIONBIO),
        /* glibc fopen uses FIOCLEX; both match already permitted F_SETFD. */
        ALLOW_SYSCALL(FIOCLEX),
        ALLOW_SYSCALL(FIONCLEX),
        ALLOW_SYSCALL(TIOCGWINSZ),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Tokio's signal self-pipe and Rust's process-spawn error channel are
         * unnamed Unix pairs (STREAM and SEQPACKET respectively). These only
         * create private endpoints; socket/connect/bind remain refused. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_socketpair, 0, 13),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AF_UNIX, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K, ~(SOCK_CLOEXEC | SOCK_NONBLOCK)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SOCK_STREAM, 2, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SOCK_SEQPACKET, 1, 0),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* Only the calling process's limits; never another PID's limits. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_prlimit64, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_fchmodat, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
#ifdef SYS_chmod
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_chmod, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
#endif
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_openat, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K,
                 O_ACCMODE | O_CREAT | O_TRUNC | O_APPEND | (O_TMPFILE & ~O_DIRECTORY)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#ifdef SYS_open
        /* The x86 PRoot loader uses raw open(O_RDONLY). Writable legacy open
         * remains denied; this experiment brokers openat only. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_open, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K,
                 O_ACCMODE | O_CREAT | O_TRUNC | O_APPEND | (O_TMPFILE & ~O_DIRECTORY)),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#endif
        ALLOW_SYSCALL(SYS_read),
        ALLOW_SYSCALL(SYS_pread64),
        /* SQLite positional writes use the same actually granted descriptors
         * as write(); no new path or writable capability is introduced. */
        ALLOW_SYSCALL(SYS_pwrite64),
        ALLOW_SYSCALL(SYS_write),
        ALLOW_SYSCALL(SYS_writev),
        ALLOW_SYSCALL(SYS_close),
        ALLOW_SYSCALL(SYS_sendmsg),
        /* send()/recv() use sendto/recvfrom on ARM64. Only the unnamed
         * socketpairs above are available; external sockets remain denied. */
        ALLOW_SYSCALL(SYS_sendto),
        ALLOW_SYSCALL(SYS_recvfrom),
        ALLOW_SYSCALL(SYS_execve),
        ALLOW_SYSCALL(SYS_execveat),
        ALLOW_SYSCALL(SYS_exit),
        ALLOW_SYSCALL(SYS_exit_group),
        ALLOW_SYSCALL(SYS_rt_sigaction),
        ALLOW_SYSCALL(SYS_rt_sigreturn),
        ALLOW_SYSCALL(SYS_rt_sigprocmask),
        ALLOW_SYSCALL(SYS_sigaltstack),
        ALLOW_SYSCALL(SYS_futex),
        ALLOW_SYSCALL(SYS_mmap),
        ALLOW_SYSCALL(SYS_munmap),
        ALLOW_SYSCALL(SYS_mprotect),
        ALLOW_SYSCALL(SYS_brk),
        ALLOW_SYSCALL(SYS_madvise),
        ALLOW_SYSCALL(SYS_mremap),
        ALLOW_SYSCALL(SYS_getuid),
        ALLOW_SYSCALL(SYS_geteuid),
        ALLOW_SYSCALL(SYS_getgid),
        ALLOW_SYSCALL(SYS_getegid),
        ALLOW_SYSCALL(SYS_getpid),
        ALLOW_SYSCALL(SYS_getppid),
        ALLOW_SYSCALL(SYS_gettid),
        ALLOW_SYSCALL(SYS_getpgid),
        ALLOW_SYSCALL(SYS_getcwd),
        ALLOW_SYSCALL(SYS_uname),
        ALLOW_SYSCALL(SYS_clock_gettime),
        ALLOW_SYSCALL(SYS_gettimeofday),
        ALLOW_SYSCALL(SYS_getrandom),
        ALLOW_SYSCALL(SYS_set_tid_address),
        ALLOW_SYSCALL(SYS_set_robust_list),
        ALLOW_SYSCALL(SYS_prctl),
        ALLOW_SYSCALL(SYS_fstat),
        ALLOW_SYSCALL(SYS_fstatfs),
        ALLOW_SYSCALL(SYS_sched_getscheduler),
        ALLOW_SYSCALL(SYS_sched_getparam),
        ALLOW_SYSCALL(SYS_newfstatat),
        ALLOW_SYSCALL(SYS_statx),
        ALLOW_SYSCALL(SYS_faccessat),
        ALLOW_SYSCALL(SYS_faccessat2),
        ALLOW_SYSCALL(SYS_readlinkat),
        ALLOW_SYSCALL(SYS_getdents64),
        ALLOW_SYSCALL(SYS_lseek),
        ALLOW_SYSCALL(SYS_dup),
        ALLOW_SYSCALL(SYS_dup3),
        ALLOW_SYSCALL(SYS_fcntl),
        /* PRoot tracer and descendants. Landlock prevents access to our parent;
         * mutation rights below cover only the private scratch grant. */
        /* Ordinary fork/threads only. No namespace flags, CLONE_PARENT,
         * CLONE_PTRACE or CLONE_UNTRACED. clone3's pointer flags cannot be
         * inspected by classic BPF: return ENOSYS for libc's native clone
         * fallback, as in the existing native-runner profile. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_clone, 0, 9),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0]) + 4),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 6),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K,
            (uint32_t)~(CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD |
            CLONE_SYSVSEM | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID |
            CLONE_CHILD_SETTID | CLONE_VFORK | 0xff), 4, 0),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K, 0xff),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SIGCHLD, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#ifdef SYS_clone3
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_clone3, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
#endif
        ALLOW_SYSCALL(SYS_readv),
        ALLOW_SYSCALL(SYS_fsync),
        ALLOW_SYSCALL(SYS_fdatasync),
        ALLOW_SYSCALL(SYS_epoll_create1),
        ALLOW_SYSCALL(SYS_epoll_ctl),
        ALLOW_SYSCALL(SYS_epoll_pwait),
        ALLOW_SYSCALL(SYS_eventfd2),
        ALLOW_SYSCALL(SYS_ppoll),
        ALLOW_SYSCALL(SYS_pselect6),
        ALLOW_SYSCALL(SYS_clock_nanosleep),
        ALLOW_SYSCALL(SYS_nanosleep),
        ALLOW_SYSCALL(SYS_restart_syscall),
        ALLOW_SYSCALL(SYS_capget),
        ALLOW_SYSCALL(SYS_sched_yield),
        ALLOW_SYSCALL(SYS_sched_getaffinity),
        ALLOW_SYSCALL(SYS_getrusage),
        ALLOW_SYSCALL(SYS_sysinfo),
        ALLOW_SYSCALL(SYS_statfs),
        ALLOW_SYSCALL(SYS_flock),
        ALLOW_SYSCALL(SYS_getresuid),
        ALLOW_SYSCALL(SYS_getresgid),
        ALLOW_SYSCALL(SYS_close_range),
#ifdef SYS_epoll_wait
        ALLOW_SYSCALL(SYS_epoll_wait),
#endif
#ifdef SYS_poll
        ALLOW_SYSCALL(SYS_poll),
#endif
#ifdef SYS_select
        ALLOW_SYSCALL(SYS_select),
#endif
        /* PRoot child stacks a scope-only Landlock domain before guest code.
         * These calls can only add restrictions to the inherited domain. */
        ALLOW_SYSCALL(SYS_landlock_create_ruleset),
        ALLOW_SYSCALL(SYS_landlock_restrict_self),
        /* The immutable, single-threaded PRoot leader cannot be inspected or
         * modified by guests in this Landlock domain. PID is captured before
         * exec and remains owned/unreaped until descendant cleanup finishes. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_ptrace, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[1])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (uint32_t)getpid(), 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* The immutable, single-threaded PRoot leader cannot be inspected or
         * modified by guests in this Landlock domain. PID is captured before
         * exec and remains owned/unreaped until descendant cleanup finishes. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_process_vm_readv, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (uint32_t)getpid(), 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        /* The immutable, single-threaded PRoot leader cannot be inspected or
         * modified by guests in this Landlock domain. PID is captured before
         * exec and remains owned/unreaped until descendant cleanup finishes. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_process_vm_writev, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (uint32_t)getpid(), 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
        ALLOW_SYSCALL(SYS_wait4),
        ALLOW_SYSCALL(SYS_waitid),
        ALLOW_SYSCALL(SYS_kill),
        ALLOW_SYSCALL(SYS_tgkill),
        ALLOW_SYSCALL(SYS_rt_sigsuspend),
        ALLOW_SYSCALL(SYS_setitimer),
        ALLOW_SYSCALL(SYS_chdir),
        ALLOW_SYSCALL(SYS_fchdir),
        ALLOW_SYSCALL(SYS_pipe2),
        ALLOW_SYSCALL(SYS_umask),
        ALLOW_SYSCALL(SYS_ftruncate),
        MG_ACQUIRE(unlinkat),
        MG_ACQUIRE(mkdirat),
        MG_ACQUIRE(renameat),
        MG_ACQUIRE(renameat2),
        MG_ACQUIRE(linkat),
        MG_ACQUIRE(symlinkat),
#ifdef SYS_fork
        ALLOW_SYSCALL(SYS_fork),
#endif
#ifdef SYS_vfork
        ALLOW_SYSCALL(SYS_vfork),
#endif
#ifdef SYS_unlink
        MG_ACQUIRE(unlink),
#endif
#ifdef SYS_rmdir
        MG_ACQUIRE(rmdir),
#endif
#ifdef SYS_mkdir
        MG_ACQUIRE(mkdir),
#endif
#ifdef SYS_rename
        MG_ACQUIRE(rename),
#endif
#ifdef SYS_link
        MG_ACQUIRE(link),
#endif
#ifdef SYS_symlink
        MG_ACQUIRE(symlink),
#endif
#ifdef SYS_alarm
        ALLOW_SYSCALL(SYS_alarm),
#endif
#ifdef SYS_dup2
        ALLOW_SYSCALL(SYS_dup2),
#endif
#ifdef SYS_getpgrp
        ALLOW_SYSCALL(SYS_getpgrp),
#endif
#ifdef SYS_getrlimit
        ALLOW_SYSCALL(SYS_getrlimit),
#endif
#ifdef SYS_access
        ALLOW_SYSCALL(SYS_access),
#endif
#ifdef SYS_readlink
        ALLOW_SYSCALL(SYS_readlink),
#endif
#ifdef SYS_arch_prctl
        ALLOW_SYSCALL(SYS_arch_prctl),
#endif
#ifdef SYS_rseq
        ALLOW_SYSCALL(SYS_rseq),
#endif
        /* Report unsupported syscall numbers and actually refuse them. */
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_USER_NOTIF),
    };
    struct sock_fprog program = {.len = (unsigned short)(sizeof(filter) / sizeof(filter[0])),
                                .filter = filter};
    return (int)syscall(SYS_seccomp, SECCOMP_SET_MODE_FILTER,
                       SECCOMP_FILTER_FLAG_NEW_LISTENER, &program);
}
