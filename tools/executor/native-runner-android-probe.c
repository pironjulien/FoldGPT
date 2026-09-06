/* SPDX-License-Identifier: GPL-3.0-only
 * Fixed offline Android/host integration checks for native-runner.
 * Only fresh cache fixtures are touched. The three executables must come from
 * the same trusted debug package. This is not a managed Codex policy adapter. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>
#include "native-runner-memory-contract.h"

static int probe_ok;
/* Only the single-threaded harness reaps children. On an assertion failure,
 * use kernel waitid parenthood to identify our children, never mutable PPid
 * text or unconfirmed numeric PIDs. The subreaper adopts fixture descendants
 * if a runner crashes. This cleanup never walks or deletes cache paths. */
static void failed_probe_cleanup(void) {
  if (probe_ok) return;
  for (int attempt = 0; attempt < 500; ++attempt) {
    int status; pid_t child;
    do { child = waitpid(-1, &status, WNOHANG); } while (child > 0 || (child < 0 && errno == EINTR));
    if (child < 0 && errno == ECHILD) return;
    DIR *entries = opendir("/proc");
    if (!entries) break;
    struct dirent *entry;
    while ((entry = readdir(entries)) != NULL) {
      char *end; long candidate = strtol(entry->d_name, &end, 10);
      if (*end || candidate < 1 || candidate > INT_MAX) continue;
      siginfo_t info = {0};
      if (waitid(P_PID, (id_t)candidate, &info, WEXITED | WNOHANG | WNOWAIT) == 0 && !info.si_pid)
        kill((pid_t)candidate, attempt < 100 ? SIGTERM : SIGKILL);
    }
    closedir(entries);
    struct timespec interval = {.tv_nsec = 10000000}; nanosleep(&interval, NULL);
  }
  fputs("failed_probe_cleanup=incomplete\n", stderr);
}
static void check(int okay, const char *name) {
  if (!okay) { fprintf(stderr, "probe_failure=%s errno=%d\n", name, errno); exit(1); }
}
static long long now_ms(void) {
  struct timespec now; check(clock_gettime(CLOCK_MONOTONIC, &now) == 0, "clock");
  return (long long)now.tv_sec * 1000 + now.tv_nsec / 1000000;
}
static void join(char out[PATH_MAX], const char *base, const char *name) {
  int size = snprintf(out, PATH_MAX, "%s/%s", base, name);
  check(size > 0 && size < PATH_MAX, "path-length");
}
static void safe_path(const char *path) {
  // These OS-derived application/cache paths are embedded in a fixed JSON
  // fixture. Refuse unsupported spelling; never accept caller command text.
  check(path[0] == '/' && strspn(path, "/abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-+=~") == strlen(path), "fixture-path-spelling");
}
static void write_all(int fd, const char *data, size_t bytes) {
  while (bytes) {
    ssize_t size = write(fd, data, bytes);
    if (size < 0 && errno == EINTR) continue;
    check(size > 0, "pipe-write"); data += size; bytes -= (size_t)size;
  }
}
struct capture { char events[4096], out[16384], err[4096]; size_t sizes[3]; };
static void drain_run(pid_t pid, int pipes[3], const char *mode, struct capture *capture) {
  char *buffers[] = {capture->events, capture->out, capture->err};
  const size_t limits[] = {sizeof(capture->events), sizeof(capture->out), sizeof(capture->err)};
  struct pollfd events[3];
  for (int i = 0; i < 3; ++i) events[i] = (struct pollfd){.fd = pipes[i], .events = POLLIN};
  int open_count = 3, cancelled = 0;
  long long deadline = now_ms() + 10000;
  while (open_count) {
    int remaining = (int)(deadline - now_ms());
    if (remaining <= 0) { check(0, "runner-supervisor-deadline"); }
    int ready = poll(events, 3, remaining < 100 ? remaining : 100);
    if (ready < 0 && errno == EINTR) continue;
    check(ready >= 0, "capture-poll");
    for (int i = 0; i < 3; ++i) {
      if (events[i].fd < 0 || !(events[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
      size_t capacity = limits[i] - capture->sizes[i] - 1;
      check(capacity > 0, "bounded-evidence-output");
      ssize_t count = read(events[i].fd, buffers[i] + capture->sizes[i], capacity);
      if (count < 0 && errno == EINTR) continue;
      check(count >= 0, "capture-read");
      if (!count) { close(events[i].fd); events[i].fd = -1; --open_count; }
      else { capture->sizes[i] += (size_t)count; buffers[i][capture->sizes[i]] = 0; }
    }
    if (!cancelled && !strcmp(mode, "cancelled") && strstr(capture->events, "\"type\":\"started\"")) {
      check(kill(pid, SIGTERM) == 0, "cancel-runner"); cancelled = 1;
    }
  }
}
static void run_case(const char *runner, const char *fixture, const char *workspace,
                     const char *outside, const char *mode, int inherited) {
  int input[2], control[2], output[2], error[2];
  check(pipe2(input, O_CLOEXEC) == 0 && pipe2(control, O_CLOEXEC) == 0
        && pipe2(output, O_CLOEXEC) == 0 && pipe2(error, O_CLOEXEC) == 0, "private-runner-pipes");
  char manifest[16384], inherited_text[32], parent_text[32];
  snprintf(inherited_text, sizeof(inherited_text), "%d", inherited);
  snprintf(parent_text, sizeof(parent_text), "%d", getpid());
  int noexec = !strcmp(mode, "exec_denied");
  int size = snprintf(manifest, sizeof(manifest),
    "{\"schema\":\"foldgpt.native-runner.v1\",\"policy\":\"landlock-basic-data-v1\","
    "\"metadata\":\"visible\",\"network\":\"deny\",\"ipc\":\"private-pipes-only\","
    "\"workspace\":\"%s\",\"cwd\":\"%s\",\"executable\":\"%s\","
    "\"argv\":[\"%s\",\"%s\",\"%s\",\"%s\",\"%s\"],\"env\":{\"LANG\":\"C\"},"
    "\"grants\":[{\"kind\":\"directory\",\"path\":\"%s\",\"access\":[\"read\"%s]},"
    "{\"kind\":\"file\",\"path\":\"%s\",\"access\":[\"read\"%s]}],"
    "\"limits\":{\"wallMs\":%d,\"outputBytes\":8192,\"addressSpaceBytes\":%llu,"
    "\"fileBytes\":1048576,\"openFiles\":64,\"uidProcesses\":256}}",
    workspace, workspace, fixture, fixture, noexec ? "data" : mode, outside, inherited_text, parent_text,
    workspace, !strcmp(mode, "readonly") ? "" : ",\"write\"", fixture, noexec ? "" : ",\"execute\"",
    !strcmp(mode, "timeout") ? 250 : 3000, (unsigned long long)NR_FIXTURE_ADDRESS_SPACE_BYTES);
  check(size > 0 && size < (int)sizeof(manifest), "manifest-size");
  pid_t parent_pid = getpid();
  pid_t child = fork(); check(child >= 0, "fork-runner");
  if (!child) {
    check(prctl(PR_SET_PDEATHSIG, SIGTERM, 0, 0, 0) == 0 && getppid() == parent_pid, "runner-parent-death");
    check(dup2(input[0], 0) == 0 && dup2(output[1], 1) == 1 && dup2(error[1], 2) == 2, "runner-streams");
    check(fcntl(control[1], F_SETFD, 0) == 0, "runner-control-fd");
    char descriptor[32]; snprintf(descriptor, sizeof(descriptor), "%d", control[1]);
    execl(runner, runner, "--result-fd", descriptor, (char *)NULL);
    _exit(127);
  }
  close(input[0]); close(control[1]); close(output[1]); close(error[1]);
  write_all(input[1], manifest, (size_t)size); close(input[1]);
  int pipes[] = {control[0], output[0], error[0]}; struct capture capture = {0};
  drain_run(child, pipes, mode, &capture);
  int status; check(waitpid(child, &status, 0) == child && WIFEXITED(status), "runner-reaped");
  printf("case=%s runner_exit=%d\n%s", mode, WEXITSTATUS(status), capture.events);
  if (capture.sizes[2]) printf("fixture_stderr=%s", capture.err);
  const char *outcome = noexec ? "setup_error" :
    (!strcmp(mode, "timeout") || !strcmp(mode, "cancelled") || !strcmp(mode, "output_limit")) ? mode : "exited";
  char expected[80]; snprintf(expected, sizeof(expected), "\"outcome\":\"%s\"", outcome);
  check(strstr(capture.events, expected) && strstr(capture.events, "\"cleanupComplete\":true"), "actual-outcome-and-cleanup");
  char *started = strstr(capture.events, "\"type\":\"started\"");
  check(noexec ? !started : started != NULL, "actual-exec-handshake");
  if (!strcmp(outcome, "exited")) {
    check(WEXITSTATUS(status) == 0 && strstr(capture.events, "\"exitCode\":0"), "command-exit-zero");
  } else check(WEXITSTATUS(status) == 1, "runner-failure-status");
  if (!strcmp(mode, "data")) {
    check(!strcmp(capture.out, "native-data\n") && !strcmp(capture.err, "native-stderr\n"), "separate-byte-exact-output");
    check(strstr(capture.events, "\"stdoutBytes\":12") && strstr(capture.events, "\"stderrBytes\":14"), "actual-output-counts");
  }
  if (!strcmp(mode, "readonly")) check(!strcmp(capture.out, "readonly\n"), "readonly-check-ran");
  if (!strcmp(mode, "address_limit")) check(!strcmp(capture.out, "address-limit\n"), "address-limit-check-ran");
  if (!strcmp(mode, "output_limit")) check(capture.sizes[1] == 8192, "exact-output-bound");
  printf("PASS case=%s\n", mode);
}
int main(int argc, char **argv) {
  setbuf(stdout, NULL);
  if (argc != 3 || getuid() == 0) return 2;
  check(prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) == 0, "own-fixture-subreaper");
  check(atexit(failed_probe_cleanup) == 0, "failure-cleanup-registration");
  char cache[PATH_MAX], native[PATH_MAX], runner[PATH_MAX], fixture[PATH_MAX], evidence[PATH_MAX];
  check(realpath(argv[1], cache) && realpath(argv[2], native), "canonical-application-paths");
  safe_path(cache); safe_path(native);
  join(runner, native, "libfoldgpt-native-runner.so");
  join(fixture, native, "libfoldgpt-native-runner-fixture.so");
  join(evidence, cache, "foldgpt-native-runner-XXXXXX");
  check(mkdtemp(evidence) != NULL, "fresh-private-fixtures");
  printf("uid=%u inherited_seccomp=%d evidence_directory=%s\n", getuid(), prctl(PR_GET_SECCOMP, 0, 0, 0, 0), evidence);
  printf("rlimit_as_bytes=%llu scudo_primary_reservation_bytes=%llu address_headroom_bytes=%llu memory_scope=virtual-address-space-not-resident-memory\n",
    (unsigned long long)NR_FIXTURE_ADDRESS_SPACE_BYTES,
    (unsigned long long)NR_FIXTURE_ALLOCATOR_RESERVATION_BYTES,
    (unsigned long long)NR_FIXTURE_ADDRESS_HEADROOM_BYTES);
  char workspace[PATH_MAX], outside[PATH_MAX];
  join(workspace, evidence, "workspace"); join(outside, evidence, "outside.txt");
  check(mkdir(workspace, 0700) == 0, "private-workspace");
  int fd = open(outside, O_RDWR | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
  check(fd >= 0, "outside-fixture"); write_all(fd, "outside-intact\n", 15);
  int inherited = fcntl(fd, F_DUPFD, 100); close(fd); check(inherited >= 100, "explicit-inherited-fd");
  check(setenv("FOLDGPT_PARENT_PRIVATE", "synthetic-fixture-only", 1) == 0, "parent-env-fixture");
  char parent[32]; snprintf(parent, sizeof(parent), "%d", getpid());
  pid_t control = fork(); check(control >= 0, "fork-positive-control");
  if (!control) { execl(fixture, fixture, "control", outside, "-1", parent, (char *)NULL); _exit(127); }
  int status; check(waitpid(control, &status, 0) == control && WIFEXITED(status) && !WEXITSTATUS(status), "unrestricted-positive-control");
  const char *cases[] = {"data", "readonly", "address_limit", "exec_denied", "timeout", "cancelled", "output_limit", "descendant"};
  for (size_t i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) run_case(runner, fixture, workspace, outside, cases[i], inherited);
  char path[PATH_MAX], bytes[64] = {0}; join(path, workspace, "value.txt");
  fd = open(path, O_RDONLY | O_CLOEXEC); check(fd >= 0 && read(fd, bytes, sizeof(bytes)) == 14 && !memcmp(bytes, "native-runner\n", 14), "independent-created-bytes"); close(fd);
  fd = open(outside, O_RDONLY | O_CLOEXEC); check(fd >= 0 && read(fd, bytes, sizeof(bytes)) == 15 && !memcmp(bytes, "outside-intact\n", 15), "independent-outside-bytes"); close(fd);
  join(path, workspace, "descendant.pid"); fd = open(path, O_RDONLY | O_CLOEXEC);
  check(fd >= 0, "read-recorded-child"); memset(bytes, 0, sizeof(bytes)); check(read(fd, bytes, sizeof(bytes) - 1) > 0, "child-pid-bytes"); close(fd);
  pid_t child = (pid_t)atoi(bytes); errno = 0;
  check(child > 0 && kill(child, 0) < 0 && errno == ESRCH, "independent-descendant-gone");
  close(inherited);
  puts("independent_native_runner_verification=PASS");
  puts("scope=fixed native executable and explicit limited grants; no PRoot, model, account, or full Codex policy");
  probe_ok = 1;
  return 0;
}
