/* SPDX-License-Identifier: GPL-3.0-only
 * Fixed native executable for the debug runner probe. No account or guest use. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <pthread.h>
#include <sched.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/mman.h>
#include <sys/resource.h>
#include <sys/syscall.h>
#include <sys/socket.h>
#include <sys/wait.h>
#include <unistd.h>
#include "native-runner-memory-contract.h"

static void check(int okay, const char *name) {
  if (!okay) { fprintf(stderr, "fixture_failure=%s errno=%d\n", name, errno); _exit(3); }
}
static void spin(void) { for (;;) { __asm__ volatile("" ::: "memory"); } }
static void *thread_value(void *argument) { return argument; }
static void allocator_and_thread(void) {
  // Actual malloc/free and pthread_create/join exercise the default allocator
  // and libc startup path; no alternative allocator or Scudo option is used.
  volatile unsigned char *memory = malloc(1024 * 1024);
  check(memory != NULL, "default-allocator");
  for (size_t i = 0; i < 1024 * 1024; i += 4096) memory[i] = 0x5a;
  pthread_t thread; void *result = NULL;
  check(pthread_create(&thread, NULL, thread_value, (void *)(uintptr_t)0x618) == 0, "pthread-create");
  check(pthread_join(thread, &result) == 0 && result == (void *)(uintptr_t)0x618, "pthread-join");
  free((void *)memory);
}
int main(int argc, char **argv) {
  if (argc != 5) return 2;
  const char *mode = argv[1], *outside = argv[2];
  int inherited = atoi(argv[3]);
  pid_t peer = (pid_t)atoi(argv[4]);
  if (!strcmp(mode, "control")) {
    int fd = open(outside, O_RDONLY | O_CLOEXEC);
    check(fd >= 0, "outside-positive-control"); close(fd);
    fd = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    check(fd >= 0, "socket-positive-control"); close(fd);
    check(kill(peer, 0) == 0, "peer-positive-control");
    struct sched_param parameters;
    check(sched_getscheduler(peer) >= 0 && sched_getparam(peer, &parameters) == 0, "peer-scheduler-positive-control");
    allocator_and_thread();
    FILE *status = fopen("/proc/self/status", "r");
    check(status != NULL, "control-memory-accounting");
    char line[256]; unsigned int counters = 0;
    while (fgets(line, sizeof(line), status)) {
      if (!strncmp(line, "VmSize:", 7) || !strncmp(line, "VmPeak:", 7)
          || !strncmp(line, "VmRSS:", 6) || !strncmp(line, "VmHWM:", 6)) {
        printf("control_%s", line); ++counters;
      }
    }
    check(!ferror(status) && counters == 4, "control-memory-counters"); fclose(status);
    return 0;
  }
  check(prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) == 1, "no-new-privileges");
  check(prctl(PR_GET_SECCOMP, 0, 0, 0, 0) == 2, "seccomp-active");
  check(getenv("FOLDGPT_PARENT_PRIVATE") == NULL, "environment-cleaned");
  errno = 0;
  check(fcntl(inherited, F_GETFD) < 0 && errno == EBADF, "descriptor-cleaned");
  if (!strcmp(mode, "address_limit")) {
    allocator_and_thread();
    struct rlimit bound;
    check(getrlimit(RLIMIT_AS, &bound) == 0 && bound.rlim_cur == NR_FIXTURE_ADDRESS_SPACE_BYTES
      && bound.rlim_max == NR_FIXTURE_ADDRESS_SPACE_BYTES, "exact-declared-address-space-limit");
    long page = sysconf(_SC_PAGESIZE); check(page > 0, "actual-page-size");
    void *mapping = mmap(NULL, (size_t)page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    check(mapping != MAP_FAILED, "small-mapping-positive-control");
    *(volatile unsigned char *)mapping = 0x61;
    check(munmap(mapping, (size_t)page) == 0, "small-mapping-release");
    errno = 0;
    mapping = mmap(NULL, (size_t)bound.rlim_cur + (size_t)page, PROT_NONE,
      MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    check(mapping == MAP_FAILED && errno == ENOMEM, "virtual-reservation-over-limit-denied");
    struct rlimit raised = {.rlim_cur = bound.rlim_cur + (rlim_t)page, .rlim_max = bound.rlim_max + (rlim_t)page};
    errno = 0;
    check(prlimit(0, RLIMIT_AS, &raised, NULL) < 0 && errno == EPERM, "hard-address-limit-cannot-be-raised");
    check(write(1, "address-limit\n", 14) == 14, "address-limit-output");
    return 0;
  }
  if (!strcmp(mode, "timeout") || !strcmp(mode, "cancelled")) spin();
  if (!strcmp(mode, "output_limit")) {
    char bytes[4096]; memset(bytes, 'X', sizeof(bytes));
    for (;;) if (write(1, bytes, sizeof(bytes)) <= 0) return 4;
  }
  if (!strcmp(mode, "readonly")) {
    errno = 0;
    int fd = open("value.txt", O_WRONLY | O_TRUNC | O_CLOEXEC);
    check(fd < 0 && errno == EACCES, "readonly-data-denied");
    check(write(1, "readonly\n", 9) == 9, "readonly-output"); return 0;
  }
  if (!strcmp(mode, "descendant")) {
    pid_t child = fork(); check(child >= 0, "fork-descendant");
    if (!child) spin();
    int fd = open("descendant.pid", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    check(fd >= 0, "record-descendant");
    char value[32]; int size = snprintf(value, sizeof(value), "%d\n", child);
    check(write(fd, value, (size_t)size) == size, "write-descendant"); close(fd);
    return 0;
  }
  check(!strcmp(mode, "data"), "known-fixture-mode");
  struct sched_param parameters;
  check(sched_getscheduler(0) >= 0 && sched_getparam(0, &parameters) == 0, "self-scheduler-queries");
  errno = 0;
  check(sched_getscheduler(peer) < 0 && errno == EPERM, "peer-scheduler-query-denied");
  errno = 0;
  check(sched_getparam(peer, &parameters) < 0 && errno == EPERM, "peer-scheduler-parameters-denied");
  errno = 0;
  check(syscall(SYS_sched_getscheduler, UINT64_C(1) << 32) < 0 && errno == EPERM, "scheduler-high-bits-denied");
  errno = 0;
  check(sched_setscheduler(0, SCHED_OTHER, &parameters) < 0 && errno == EPERM, "scheduler-mutation-denied");
  allocator_and_thread();
  errno = 0;
  int fd = open(outside, O_RDONLY | O_CLOEXEC);
  check(fd < 0 && errno == EACCES, "outside-read-denied");
  errno = 0;
  check(socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0) < 0 && errno == EPERM, "network-denied");
  int pair[2]; errno = 0;
  check(socketpair(AF_UNIX, SOCK_STREAM, 0, pair) < 0 && errno == EPERM, "named-ipc-unavailable");
  errno = 0;
  check(kill(peer, 0) < 0 && errno == EPERM, "outside-peer-signal-denied");
  fd = open("value.txt", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  check(fd >= 0 && write(fd, "native", 6) == 6, "create-file"); close(fd);
  fd = open("value.txt", O_WRONLY | O_APPEND | O_CLOEXEC);
  check(fd >= 0 && write(fd, "-runner\n", 8) == 8, "append-file"); close(fd);
  check(pipe(pair) == 0, "private-pipe");
  pid_t child = fork(); check(child >= 0, "fork");
  if (!child) { close(pair[0]); _exit(write(pair[1], "ok", 2) == 2 ? 0 : 1); }
  close(pair[1]); char answer[2]; int status;
  check(read(pair[0], answer, 2) == 2 && !memcmp(answer, "ok", 2), "child-pipe-data");
  close(pair[0]);
  check(waitpid(child, &status, 0) == child && WIFEXITED(status) && !WEXITSTATUS(status), "child-wait");
  check(write(1, "native-data\n", 12) == 12 && write(2, "native-stderr\n", 14) == 14, "separate-output");
  return 0;
}
