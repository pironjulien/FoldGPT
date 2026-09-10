/* SPDX-License-Identifier: GPL-3.0-only
 * One fixed offline qualification. This is not a generic command executor.
 * No ptrace, PRoot, seccomp notification, namespaces or privileged service API.
 */
#define _GNU_SOURCE
#include "native-runner-seccomp.h"
#include "shizuku-fixture.h"
#include <dirent.h>
#include <linux/capability.h>
#include <poll.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <time.h>

#ifndef SHIZUKU_ROOT
#define SHIZUKU_ROOT "/data/local/tmp/foldgpt-shizuku-lab"
#endif
#ifndef SHIZUKU_EXPECT_UID
#define SHIZUKU_EXPECT_UID 2000
#endif
#ifdef SHIZUKU_HOST_TEST
#define PYTHON SHIZUKU_HOST_PYTHON
#define BASH "/usr/bin/bash"
#else
#define PYTHON SHIZUKU_ROOT "/native/libfoldgpt_python_cli.so"
#define BASH SHIZUKU_ROOT "/native/libfoldgpt_bash.so"
#endif
#define WORKSPACE SHIZUKU_ROOT "/workspace"
#define OUTSIDE SHIZUKU_ROOT "/outside-sentinel"
#define LL_EXECUTE (1ULL << 0)
#define LL_WRITE (1ULL << 1)
#define LL_READ (1ULL << 2)
#define LL_READ_DIR (1ULL << 3)
#define LL_TRUNCATE (1ULL << 14)
#define LL_READ_TREE (LL_READ | LL_READ_DIR)
/* Ordinary directory/file creation/removal plus cross-directory references.
 * No executable, device, socket, FIFO or symlink creation grant in workspace. */
#define LL_WRITE_TREE (LL_READ_TREE | LL_WRITE | LL_TRUNCATE | (1ULL << 4) | \
                       (1ULL << 5) | (1ULL << 7) | (1ULL << 8) | (1ULL << 13))
#define MAX_OUTPUT 65536U
#define WALL_MS 30000
#define CLEANUP_MS 5000

struct ll_ruleset { uint64_t fs, net, scoped; };
struct ll_path { uint64_t allowed; int32_t fd; } __attribute__((packed));
struct setup_message { int stage, error; };
static volatile sig_atomic_t cancelled;

static void on_signal(int number) { cancelled = number; }
static int64_t now_ms(void) {
  struct timespec value;
  if (clock_gettime(CLOCK_MONOTONIC, &value) < 0) return -1;
  return (int64_t)value.tv_sec * 1000 + value.tv_nsec / 1000000;
}
static int rejected(const char *stage) {
  int saved = errno;
  fprintf(stderr, "{\"type\":\"probe-rejected\",\"stage\":\"%s\",\"errno\":%d}\n",
          stage, saved);
  /* Called only before a successful fork: no descendant ownership exists. */
  dprintf(1, "{\"type\":\"probe-result\",\"success\":false,\"outcome\":\"rejected\","
             "\"exitCode\":-1,\"signal\":0,\"setupCompleted\":false,"
             "\"cleanup_complete\":true,\"supervisorPid\":%d,\"childPid\":0}\n", getpid());
  return 70;
}
static int nonblock(int fd) {
  int flags = fcntl(fd, F_GETFL);
  return flags < 0 ? -1 : fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}
static int write_bytes(int fd, const void *buffer, size_t size, int64_t deadline, int heed_cancel) {
  const char *cursor = buffer;
  while (size) {
    if ((heed_cancel && cancelled) || now_ms() >= deadline) { errno = ETIMEDOUT; return -1; }
    ssize_t count = write(fd, cursor, size);
    if (count > 0) { cursor += count; size -= (size_t)count; continue; }
    if (count < 0 && errno == EINTR) continue;
    if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK)) {
      struct pollfd pending = {.fd = fd, .events = POLLOUT};
      if (poll(&pending, 1, 20) >= 0 || errno == EINTR) continue;
    }
    return -1;
  }
  return 0;
}
static int write_until(int fd, const void *buffer, size_t size, int64_t deadline) {
  return write_bytes(fd, buffer, size, deadline, 1);
}
static int write_control(int fd, const void *buffer, size_t size, int64_t deadline) {
  return write_bytes(fd, buffer, size, deadline, 0);
}
static int same_identity_without_caps(void) {
  uid_t real, effective, saved;
  gid_t greal, geffective, gsaved;
  struct __user_cap_header_struct h = {.version = _LINUX_CAPABILITY_VERSION_3};
  struct __user_cap_data_struct d[2] = {{0}, {0}};
  if (getresuid(&real, &effective, &saved) < 0 ||
      getresgid(&greal, &geffective, &gsaved) < 0 ||
      real != SHIZUKU_EXPECT_UID || !real || real != effective || real != saved ||
      greal != geffective || greal != gsaved ||
      syscall(SYS_capget, &h, d) < 0 ||
      (d[0].effective | d[0].permitted | d[0].inheritable |
       d[1].effective | d[1].permitted | d[1].inheritable)) {
    errno = EPERM; return -1;
  }
  for (unsigned bit = 0; bit < 64; ++bit) {
    int value = prctl(PR_CAP_AMBIENT, PR_CAP_AMBIENT_IS_SET, bit, 0, 0);
    if (value == 0) continue;
    if (value < 0 && errno == EINVAL) break;
    errno = EPERM; return -1;
  }
  return 0;
}
static int private_directory(const char *path) {
  struct stat info;
  if (lstat(path, &info) < 0) return -1;
  if (!S_ISDIR(info.st_mode) || info.st_uid != getuid() ||
      (info.st_mode & (0077 | S_ISUID | S_ISGID))) {
    errno = EPERM; return -1;
  }
  return 0;
}
/* Root provisioning must remain exclusive to the trusted operator. UID 2000
 * is shared by Shizuku/adb peers; chmod is not isolation from a hostile peer
 * with that same UID. Runtime hashes are verified during host deployment.
 */
static int runtime_tree(const char *path, unsigned *count, unsigned depth) {
  if (++*count > 8192 || depth > 32) { errno = E2BIG; return -1; }
  struct stat info;
  if (lstat(path, &info) < 0) return -1;
  if (info.st_uid != getuid()) {
    errno = EPERM; return -1;
  }
  if (S_ISLNK(info.st_mode)) {
    char target[PATH_MAX];
    if (!realpath(path, target) ||
        (strncmp(target, SHIZUKU_ROOT "/native/", strlen(SHIZUKU_ROOT "/native/")) &&
         strncmp(target, SHIZUKU_ROOT "/python/", strlen(SHIZUKU_ROOT "/python/"))) ||
        stat(target, &info) < 0 || !S_ISREG(info.st_mode) ||
        info.st_uid != getuid() || info.st_nlink != 1 ||
        (info.st_mode & (0022 | S_ISUID | S_ISGID))) {
      errno = EPERM; return -1;
    }
    return 0;
  }
  if (info.st_mode & (0022 | S_ISUID | S_ISGID)) { errno = EPERM; return -1; }
  if (S_ISREG(info.st_mode)) {
    if (info.st_nlink == 1) return 0;
    errno = EMLINK; return -1;
  }
  if (!S_ISDIR(info.st_mode)) { errno = EPERM; return -1; }
  DIR *directory = opendir(path);
  if (!directory) return -1;
  int result = 0;
  struct dirent *entry;
  errno = 0;
  while ((entry = readdir(directory))) {
    if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
    char child[PATH_MAX];
    int length = snprintf(child, sizeof(child), "%s/%s", path, entry->d_name);
    if (length < 0 || (size_t)length >= sizeof(child) ||
        runtime_tree(child, count, depth + 1) < 0) { result = -1; break; }
    errno = 0;
  }
  if (errno) result = -1;
  int saved = errno;
  closedir(directory);
  errno = saved;
  return result;
}
/* RLIMIT_NPROC counts tasks sharing the real UID; it is not a per-job cgroup.
 * Measure before fork and add eight tasks for this tiny sequential fixture.
 * Concurrent UID activity can make fork fail; this is never relaxed on failure.
 */
static int task_limit(rlim_t *limit) {
  DIR *directory = opendir("/proc");
  if (!directory) return -1;
  struct dirent *entry;
  unsigned long total = 0;
  int failed = 0;
  while ((entry = readdir(directory))) {
    char *end;
    long pid = strtol(entry->d_name, &end, 10);
    if (!*entry->d_name || *end || pid <= 0) continue;
    char path[PATH_MAX];
    snprintf(path, sizeof(path), "/proc/%ld", pid);
    struct stat info;
    if (stat(path, &info) < 0 || info.st_uid != getuid()) continue;
    snprintf(path, sizeof(path), "/proc/%ld/status", pid);
    FILE *stream = fopen(path, "re");
    if (!stream) { if (errno != ENOENT && errno != ESRCH) failed = 1; continue; }
    char line[512];
    unsigned long threads = 0;
    while (fgets(line, sizeof(line), stream))
      if (sscanf(line, "Threads: %lu", &threads) == 1) break;
    fclose(stream);
    if (!threads) { failed = 1; break; }
    total += threads;
    if (total > 4096) { failed = 1; break; }
  }
  closedir(directory);
  if (failed || !total) { errno = EACCES; return -1; }
  struct rlimit existing;
  if (getrlimit(RLIMIT_NPROC, &existing) < 0) return -1;
  *limit = total + 8;
  if (*limit > existing.rlim_max) *limit = existing.rlim_max;
  return 0;
}
static int set_limit(int resource, rlim_t value) {
  struct rlimit old;
  if (getrlimit(resource, &old) < 0) return -1;
  if (old.rlim_max < value) value = old.rlim_max;
  struct rlimit limit = {.rlim_cur = value, .rlim_max = value};
  return setrlimit(resource, &limit);
}
static int add_rule(int ruleset, const char *path, uint64_t rights, int optional) {
  int fd = open(path, O_PATH | O_CLOEXEC);
  if (fd < 0) return optional && errno == ENOENT ? 0 : -1;
  struct stat info;
  if (fstat(fd, &info) < 0) {
    int saved = errno;
    dprintf(2, "{\"type\":\"landlock-rule-error\",\"path\":\"%s\",\"operation\":\"fstat\",\"errno\":%d}\n", path, saved);
    close(fd); errno = saved; return -1;
  }
  if (!S_ISDIR(info.st_mode) && !S_ISREG(info.st_mode)) {
    close(fd); errno = EPERM; return -1;
  }
  if (S_ISREG(info.st_mode)) rights &= ~LL_READ_DIR;
  struct ll_path rule = {.allowed = rights, .fd = fd};
  int result = (int)syscall(SYS_landlock_add_rule, ruleset, 1, &rule, 0);
  int saved = errno;
  close(fd);
  errno = saved;
  return result;
}
static int install_landlock(void) {
  struct ll_ruleset attributes = {.fs = (1ULL << 16) - 1, .scoped = 3};
  int ruleset = (int)syscall(SYS_landlock_create_ruleset, &attributes, sizeof(attributes), 0);
  if (ruleset < 0) return -1;
  int result = -1;
  if (add_rule(ruleset, WORKSPACE, LL_WRITE_TREE, 0) < 0) goto done;
#ifdef SHIZUKU_HOST_TEST
  if (add_rule(ruleset, "/usr", LL_READ_TREE | LL_EXECUTE, 0) < 0 ||
      add_rule(ruleset, "/lib", LL_READ_TREE | LL_EXECUTE, 0) < 0 ||
      add_rule(ruleset, "/lib64", LL_READ_TREE | LL_EXECUTE, 1) < 0 ||
      add_rule(ruleset, "/etc/ld.so.cache", LL_READ, 1) < 0) goto done;
#else
  if (add_rule(ruleset, SHIZUKU_ROOT "/native", LL_READ_TREE | LL_EXECUTE, 0) < 0 ||
      add_rule(ruleset, SHIZUKU_ROOT "/python", LL_READ_TREE, 0) < 0 ||
      add_rule(ruleset, "/system/lib64", LL_READ_TREE | LL_EXECUTE, 0) < 0 ||
      add_rule(ruleset, "/system/bin/linker64", LL_READ | LL_EXECUTE, 0) < 0 ||
      add_rule(ruleset, "/apex/com.android.runtime", LL_READ_TREE | LL_EXECUTE, 0) < 0 ||
      add_rule(ruleset, "/linkerconfig/ld.config.txt", LL_READ, 0) < 0 ||
      add_rule(ruleset, "/apex/com.android.tzdata/etc/tz/tzdata", LL_READ, 0) < 0 ||
      add_rule(ruleset, "/dev/__properties__", LL_READ_TREE, 0) < 0) goto done;
#endif
  result = (int)syscall(SYS_landlock_restrict_self, ruleset, 0);
done:;
  int saved = errno;
  close(ruleset);
  errno = saved;
  return result;
}
static int denied_open(const char *path, int flags) {
  errno = 0;
  int fd = open(path, flags | O_CLOEXEC);
  if (fd >= 0) { close(fd); errno = EIO; return -1; }
  return errno == EACCES || errno == EPERM ? 0 : -1;
}
static int denied_socket(int domain) {
  int fd = socket(domain, SOCK_STREAM, 0);
  if (fd >= 0) { close(fd); errno = EIO; return -1; }
  return errno == EPERM ? 0 : -1;
}
static void launch(int input, int output, int error, int setup,
                   pid_t supervisor, rlim_t processes, const char *binder) {
  struct setup_message message = {.stage = 1};
  if (setpgid(0, 0) < 0 || prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0 ||
      getppid() != supervisor || dup2(input, 0) < 0 || dup2(output, 1) < 0 ||
      dup2(error, 2) < 0) goto failed;
  if ((setup > 3 && syscall(SYS_close_range, 3U, (unsigned)setup - 1, 0U) < 0) ||
      syscall(SYS_close_range, (unsigned)setup + 1, UINT_MAX, 0U) < 0) goto failed;
  if (same_identity_without_caps() < 0 ||
      prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
      prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 1) goto failed;
  /* Reset inherited signal handlers to normal command semantics. */
  struct sigaction normal = {.sa_handler = SIG_DFL};
  sigemptyset(&normal.sa_mask);
  if (sigaction(SIGINT, &normal, NULL) < 0 || sigaction(SIGTERM, &normal, NULL) < 0 ||
      sigaction(SIGPIPE, &normal, NULL) < 0) goto failed;
  message.stage = 2;
  if (set_limit(RLIMIT_CORE, 0) < 0 || set_limit(RLIMIT_CPU, 15) < 0 ||
      set_limit(RLIMIT_FSIZE, 8U * 1024 * 1024) < 0 ||
      set_limit(RLIMIT_NOFILE, 128) < 0 || set_limit(RLIMIT_NPROC, processes) < 0 ||
      set_limit(RLIMIT_DATA, 256U * 1024 * 1024) < 0 ||
      set_limit(RLIMIT_STACK, 8U * 1024 * 1024) < 0) goto failed;
  message.stage = 3;
  if (chdir(WORKSPACE) < 0 || install_landlock() < 0) goto failed;
  message.stage = 4;
  if (nr_install_seccomp() < 0 || prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != 2) goto failed;
  message.stage = 5;
  if (denied_open(OUTSIDE, O_RDONLY) < 0 || denied_open(OUTSIDE, O_WRONLY) < 0 ||
      denied_socket(AF_INET) < 0 || denied_socket(AF_UNIX) < 0) goto failed;
  errno = 0;
  if (syscall(SYS_ioctl, 1, 0, 0) != -1 || errno != EPERM) goto failed;
  errno = 0;
  if (kill(supervisor, 0) != -1 || (errno != EPERM && errno != EACCES)) goto failed;
  if (binder && denied_open(binder, O_RDWR) < 0) goto failed;
  dprintf(1, "{\"type\":\"restrictions-checked\",\"landlock\":true,"
             "\"seccomp\":true,\"outsideReadDenied\":true,\"outsideWriteDenied\":true,"
             "\"networkDenied\":true,\"ioctlDenied\":true,\"outsideSignalDenied\":true,"
             "\"binderOpenDenied\":%s}\n", binder ? "true" : "null");
  message.stage = 0;
  message.error = 0;
  if (write(setup, &message, sizeof(message)) != sizeof(message)) _exit(70);
  char supervisor_env[64];
  snprintf(supervisor_env, sizeof(supervisor_env), "FOLDGPT_SUPERVISOR=%d", supervisor);
  char *environment[] = {
      "PATH=" SHIZUKU_ROOT "/native:/system/bin", "HOME=" WORKSPACE,
      "TMPDIR=" WORKSPACE, "LC_ALL=C.UTF-8", "FOLDGPT_WORKSPACE=" WORKSPACE,
      "FOLDGPT_OUTSIDE=" OUTSIDE, "FOLDGPT_PYTHON=" PYTHON,
      "FOLDGPT_PYTHON_REAL=" PYTHON, supervisor_env,
      "FOLDGPT_CODE=" SHIZUKU_FIXTURE, NULL};
  char *arguments[] = {BASH, "--noprofile", "--norc", "-c",
      "exec \"$FOLDGPT_PYTHON\" -I -B -c \"$FOLDGPT_CODE\"", NULL};
  execve(BASH, arguments, environment);
  message.stage = 6;
failed:
  message.error = errno;
  ssize_t reported = write(setup, &message, sizeof(message));
  (void)reported;
  _exit(70);
}
static void terminate_once(int *terminating, int64_t *deadline, int64_t now) {
  if (!*terminating) { *terminating = 1; *deadline = now + CLEANUP_MS; }
}
static int supervise(rlim_t processes, const char *binder) {
  int input[2], output[2], error[2], setup[2];
  if (pipe2(input, O_CLOEXEC) < 0 || pipe2(output, O_CLOEXEC) < 0 ||
      pipe2(error, O_CLOEXEC) < 0 || pipe2(setup, O_CLOEXEC) < 0 ||
      prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) < 0)
    return rejected("pipes-subreaper");
  pid_t supervisor = getpid();
  pid_t child = fork();
  if (!child) launch(input[0], output[1], error[1], setup[1], supervisor, processes, binder);
  close(input[0]); close(input[1]); close(output[1]); close(error[1]); close(setup[1]);
  if (child < 0) return rejected("fork");
  int fds[3] = {output[0], error[0], setup[0]};
  int bad_nonblock = 0;
  for (int i = 0; i < 3; ++i) if (nonblock(fds[i]) < 0) bad_nonblock = 1;
  int64_t start = now_ms(), deadline = start + WALL_MS, cleanup = 0;
  int observed = 0, reaped = 0, group_killed = 0, no_children = 0, leader_status = 0;
  int eof[3] = {0, 0, 0}, terminating = bad_nonblock, successful_setup = 0;
  int owner_held = 0;
  if (terminating) cleanup = start + CLEANUP_MS;
  const char *outcome = bad_nonblock ? "setup-error" : "exited";
  size_t emitted = 0, pending_size = 0;
  struct setup_message pending = {0};
  int error_stage = 0, error_number = 0;
  while (!no_children || !eof[0] || !eof[1] || !eof[2]) {
    int64_t now = now_ms();
    if (now < 0) {
      outcome = "clock-error";
      terminate_once(&terminating, &cleanup, deadline);
      now = cleanup;
    }
    if (!terminating && (cancelled || now >= deadline)) {
      outcome = cancelled ? "cancelled" : "timeout";
      terminate_once(&terminating, &cleanup, now);
    }
    if (terminating && !reaped) {
      if (kill(-child, SIGKILL) == 0) group_killed = 1;
      (void)kill(child, SIGKILL);
    }
    if (terminating && now >= cleanup && !owner_held) {
      /* A deadline cannot make an uninterruptible kernel task reapable. Keep
       * its actual supervisor alive instead of returning a dead Java handle.
       * No command is retried; Java retains this process on its own deadline.
       */
      owner_held = 1;
      outcome = "cleanup-error";
      char held[256];
      int held_size = snprintf(held, sizeof(held), "{\"type\":\"probe-cleanup-pending\","
          "\"cleanup_complete\":false,\"owner_retained\":true,\"supervisorPid\":%d,"
          "\"childPid\":%d}\n", supervisor, child);
      (void)write_control(1, held, (size_t)held_size, now + 500);
    }
    struct pollfd pollers[3];
    for (int i = 0; i < 3; ++i)
      pollers[i] = (struct pollfd){.fd = eof[i] ? -1 : fds[i], .events = POLLIN};
    if (poll(pollers, 3, owner_held ? 1000 : 20) < 0 && errno != EINTR) {
      outcome = "poll-error"; terminate_once(&terminating, &cleanup, now);
    }
    for (int i = 0; i < 3; ++i) {
      if (eof[i] || !(pollers[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
      char buffer[4096];
      ssize_t count = read(fds[i], buffer, sizeof(buffer));
      if (!count) {
        eof[i] = 1;
        if (i == 2 && pending_size) {
          outcome = "setup-protocol-error"; terminate_once(&terminating, &cleanup, now);
        }
      } else if (count > 0 && i == 2) {
        for (ssize_t offset = 0; offset < count; ++offset) {
          ((char *)&pending)[pending_size++] = buffer[offset];
          if (pending_size != sizeof(pending)) continue;
          if (!pending.stage && !pending.error && !successful_setup) successful_setup = 1;
          else {
            error_stage = pending.stage; error_number = pending.error;
            outcome = "setup-error"; terminate_once(&terminating, &cleanup, now);
          }
          pending_size = 0;
        }
      } else if (count > 0) {
        size_t accepted = (size_t)count;
        if (accepted > MAX_OUTPUT - emitted) accepted = MAX_OUTPUT - emitted;
        int64_t capture_deadline = terminating && cleanup < deadline ? cleanup : deadline;
        if (accepted && !owner_held && write_until(i + 1, buffer, accepted, capture_deadline) < 0) {
          outcome = "capture-error"; terminate_once(&terminating, &cleanup, now_ms());
        }
        emitted += accepted;
        if (accepted < (size_t)count) {
          outcome = "output-limit"; terminate_once(&terminating, &cleanup, now_ms());
        }
      } else if (errno != EAGAIN && errno != EINTR) {
        outcome = "read-error"; terminate_once(&terminating, &cleanup, now);
      }
    }
    /* Keep the leader unreaped while signaling its process group, so its
     * numeric ID cannot be recycled. Seccomp forbids setpgid/setsid/escape.
     */
    if (!observed) {
      siginfo_t info = {0};
      if (waitid(P_PID, (id_t)child, &info, WEXITED | WNOHANG | WNOWAIT) < 0) {
        if (errno != EINTR) {
          outcome = "wait-error"; terminate_once(&terminating, &cleanup, now);
        }
      } else if (info.si_pid == child) {
        observed = 1;
        if (kill(-child, SIGKILL) == 0) group_killed = 1;
        terminate_once(&terminating, &cleanup, now_ms());
      }
    }
    if (observed && !reaped && waitpid(child, &leader_status, WNOHANG) == child) reaped = 1;
    if (reaped) {
      for (;;) {
        int ignored;
        pid_t remaining = waitpid(-1, &ignored, WNOHANG);
        if (remaining > 0) continue;
        if (remaining < 0 && errno == ECHILD) no_children = 1;
        break;
      }
    }
  }
  for (int i = 0; i < 3; ++i) close(fds[i]);
  int code = reaped && WIFEXITED(leader_status) ? WEXITSTATUS(leader_status) : -1;
  int signal_number = reaped && WIFSIGNALED(leader_status) ? WTERMSIG(leader_status) : 0;
  int complete = reaped && no_children && (group_killed || !successful_setup);
  int success = complete && successful_setup && !strcmp(outcome, "exited") && code == 0;
  char report[1024];
  int length = snprintf(report, sizeof(report),
      "{\"type\":\"probe-result\",\"success\":%s,\"outcome\":\"%s\","
      "\"exitCode\":%d,\"signal\":%d,\"setupCompleted\":%s,\"cleanup_complete\":%s,"
      "\"errorStage\":%d,\"errno\":%d,\"outputBytes\":%zu,\"wallMs\":%lld,"
      "\"supervisorPid\":%d,\"childPid\":%d}\n",
      success ? "true" : "false", outcome, code, signal_number,
      successful_setup ? "true" : "false", complete ? "true" : "false",
      error_stage, error_number, emitted, (long long)(now_ms() - start), supervisor, child);
  (void)write_control(1, report, (size_t)length, now_ms() + 500);
  return success ? 0 : !strcmp(outcome, "timeout") ? 124 : 70;
}
int main(int argc, char **argv) {
  (void)argv;
  if (argc != 1) { errno = EINVAL; return rejected("arguments"); }
  /* Close Shizuku/Binder/control FDs in the trusted supervisor too. Children
   * later receive newly-created pipes only, never these inherited stdio FDs. */
  if (syscall(SYS_close_range, 3U, UINT_MAX, 0U) < 0) return rejected("inherited-fds");
  umask(0077);
  if (same_identity_without_caps() < 0) return rejected("identity-capabilities");
  if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) return rejected("no-new-privs");
  int abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0, 1);
  if (abi < 6) { errno = EOPNOTSUPP; return rejected("landlock-abi"); }
  if (private_directory(SHIZUKU_ROOT) < 0) return rejected("deployment-root");
#ifndef SHIZUKU_HOST_TEST
  unsigned objects = 0;
  if (runtime_tree(SHIZUKU_ROOT "/native", &objects, 0) < 0 ||
      runtime_tree(SHIZUKU_ROOT "/python", &objects, 0) < 0)
    return rejected("runtime-tree");
#endif
  rlim_t processes;
  if (task_limit(&processes) < 0) return rejected("uid-task-count");
  const char *binder = NULL;
#ifndef SHIZUKU_HOST_TEST
  static const char *nodes[] = {"/dev/binder", "/dev/binderfs/binder", "/dev/vndbinder", NULL};
  for (int i = 0; nodes[i]; ++i) {
    struct stat info;
    if (stat(nodes[i], &info) == 0 && S_ISCHR(info.st_mode)) { binder = nodes[i]; break; }
  }
  if (!binder) { errno = ENODEV; return rejected("binder-node"); }
#endif
  if (mkdir(WORKSPACE, 0700) < 0) return rejected("fresh-workspace");
  int sentinel = open(OUTSIDE, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
  if (sentinel < 0) return rejected("fresh-sentinel");
  static const char marker[] = "outside readable only before confinement\n";
  int wrote = write(sentinel, marker, sizeof(marker) - 1) == sizeof(marker) - 1;
  close(sentinel);
  if (!wrote) return rejected("sentinel-write");
  /* Prove the DAC/SELinux baseline permits both opens before denying them. */
  sentinel = open(OUTSIDE, O_RDWR | O_CLOEXEC);
  if (sentinel < 0) return rejected("sentinel-baseline");
  close(sentinel);
  if (nonblock(1) < 0 || nonblock(2) < 0) return rejected("capture-fds");
  struct sigaction action = {.sa_handler = on_signal};
  sigemptyset(&action.sa_mask);
  if (sigaction(SIGINT, &action, NULL) < 0 || sigaction(SIGTERM, &action, NULL) < 0)
    return rejected("signal-handlers");
  action.sa_handler = SIG_IGN;
  if (sigaction(SIGPIPE, &action, NULL) < 0) return rejected("signal-pipe");
  char context[768];
  int length = snprintf(context, sizeof(context),
      "{\"type\":\"probe-context\",\"uid\":%d,\"landlockAbi\":%d,\"noNewPrivs\":true,"
      "\"capabilities\":\"effective-permitted-inheritable-ambient-zero\","
      "\"nprocSharedUidLimit\":%llu,\"wallLimitMs\":%d,\"cpuLimitSeconds\":15,"
      "\"dataLimitBytes\":268435456,\"fileLimitBytes\":8388608,\"outputLimitBytes\":%u}\n",
      (int)getuid(), abi, (unsigned long long)processes, WALL_MS, MAX_OUTPUT);
  if (write_until(1, context, (size_t)length, now_ms() + 500) < 0)
    return rejected("context-output");
  return supervise(processes, binder);
}
