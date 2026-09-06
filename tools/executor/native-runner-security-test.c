/* SPDX-License-Identifier: GPL-3.0-only
 * Real syscall exercise invoked as an arbitrary executable by native-runner.
 * It never targets user data. The Python harness supplies one disposable peer.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/io_uring.h>
#include <linux/sched.h>
#include <sched.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <sys/msg.h>
#include <sys/prctl.h>
#include <sys/ptrace.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/wait.h>
#include <unistd.h>

static int denied(const char *name, long result, int error) {
  if (result != -1 || error != EPERM) {
    fprintf(stderr, "FAIL %s result=%ld errno=%d\n", name, result, error);
    return 0;
  }
  printf("PASS %s EPERM\n", name);
  return 1;
}
#define DENIED(name, operation)                                                \
  do {                                                                         \
    errno = 0;                                                                 \
    long result = (operation);                                                 \
    int error = errno;                                                         \
    if (!denied(name, result, error))                                          \
      return 1;                                                                \
  } while (0)

int main(int argc, char **argv) {
  if (argc != 4)
    return 2;
  pid_t peer = (pid_t)strtol(argv[1], NULL, 10);
  const char *outside = argv[2], *value = argv[3];
  if (peer <= 0 || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1 ||
      prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != 2)
    return 3;
  DENIED("network socket", syscall(SYS_socket, AF_INET, SOCK_STREAM, 0));
  DENIED("Unix socket", syscall(SYS_socket, AF_UNIX, SOCK_STREAM, 0));
  int sockets[2];
  DENIED("socketpair",
         syscall(SYS_socketpair, AF_UNIX, SOCK_STREAM, 0, sockets));
  DENIED("System V IPC", syscall(SYS_msgget, IPC_PRIVATE, IPC_CREAT | 0600));
  DENIED("POSIX queue", syscall(SYS_mq_open, "foldgpt-private-test",
                                O_CREAT | O_RDWR, 0600, NULL));
  DENIED("ptrace peer", ptrace(PTRACE_ATTACH, peer, NULL, NULL));
  unsigned char data[16];
  struct iovec local = {.iov_base = data, .iov_len = sizeof(data)},
               remote = {.iov_base = (void *)(uintptr_t)1,
                         .iov_len = sizeof(data)};
  DENIED("process_vm peer",
         syscall(SYS_process_vm_readv, peer, &local, 1UL, &remote, 1UL, 0UL));
  DENIED("pidfd peer", syscall(SYS_pidfd_open, peer, 0));
  DENIED("namespace unshare", syscall(SYS_unshare, CLONE_NEWUSER));
  DENIED("process group escape", setpgid(0, 0));
  DENIED("session escape", setsid());
  DENIED("clone parent escape",
         syscall(SYS_clone, CLONE_PARENT | SIGCHLD, NULL, NULL, NULL, 0));
  struct io_uring_params ring = {0};
  DENIED("io_uring", syscall(SYS_io_uring_setup, 8, &ring));
  DENIED("chmod mutation", chmod(value, 0644));
  DENIED("peer signal", kill(peer, SIGUSR1));
  DENIED("peer resource limit", prlimit(peer, RLIMIT_NOFILE, NULL, NULL));
  struct sched_param scheduler;
  if (sched_getscheduler(0) < 0 || sched_getparam(0, &scheduler) < 0)
    return 12;
  puts("PASS calling-thread scheduler queries with pid zero");
  DENIED("peer scheduler", sched_getscheduler(peer));
  DENIED("peer scheduler parameters", sched_getparam(peer, &scheduler));
  unsigned long affinity[16];
  if (syscall(SYS_sched_getaffinity, 0, sizeof(affinity), affinity) < 0)
    return 13;
  DENIED("peer scheduler affinity", syscall(SYS_sched_getaffinity, peer, sizeof(affinity), affinity));
  DENIED("scheduler pid high bits", syscall(SYS_sched_getscheduler, UINT64_C(1) << 32));
  DENIED("scheduler mutation", sched_setscheduler(0, SCHED_OTHER, &scheduler));
  errno = 0;
  int fd = open(outside, O_RDONLY | O_CLOEXEC);
  if (fd >= 0 || errno != EACCES)
    return 4;
  errno = 0;
  if (link(outside, "outside-alias") == 0 ||
      !(errno == EACCES || errno == EXDEV))
    return 5;
  errno = 0;
  if (syscall(SYS_mknodat, AT_FDCWD, "host-fifo", S_IFIFO | 0600, 0) == 0 ||
      !(errno == EACCES || errno == EPERM))
    return 6;
  int p[2];
  if (pipe(p) < 0)
    return 7;
  pid_t child = fork();
  if (child < 0)
    return 8;
  if (!child) {
    close(p[0]);
    if (write(p[1], "ok", 2) != 2)
      _exit(1);
    _exit(0);
  }
  close(p[1]);
  char answer[2];
  int status;
  if (read(p[0], answer, 2) != 2 || waitpid(child, &status, 0) != child ||
      !WIFEXITED(status) || WEXITSTATUS(status))
    return 9;
  close(p[0]);
  puts("PASS actual fork/pipe/wait within the command domain");
  child = fork();
  if (child < 0)
    return 10;
  if (!child) {
    for (;;)
      pause();
  }
  if (kill(child, SIGTERM) < 0 || waitpid(child, &status, 0) != child ||
      !WIFSIGNALED(status) || WTERMSIG(status) != SIGTERM)
    return 11;
  puts("PASS signal to own child while peer signal is denied");
  return 0;
}
