/* SPDX-License-Identifier: GPL-3.0-only
 * Bounded native process backend. See native-runner-contract.md for its
 * explicit additive data policy; this is not the full Codex managed-policy
 * interpreter.
 */
#define _GNU_SOURCE
#include "native-runner-seccomp.h"
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include "native-runner-memory-contract.h"
#include <linux/capability.h>
#include <linux/magic.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/ptrace.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/vfs.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define MAX_MANIFEST 65536
#define MAX_NODES 4096
#define MAX_GRANTS 128
#define MAX_ARGS 256
#define MAX_ENV 128
#define LL_READ_FILE (1ULL << 2)
#define LL_READ_DIR (1ULL << 3)
#define LL_WRITE_FILE (1ULL << 1)
#define LL_EXECUTE (1ULL << 0)
#define LL_TRUNCATE (1ULL << 14)
#define LL_SCOPE_SIGNAL (1ULL << 1)
#define LL_SCOPE_ABSTRACT (1ULL << 0)
#define LL_HANDLED_FS ((1ULL << 16) - 1)
#define LL_DIR_WRITE                                                           \
  ((1ULL << 4) | (1ULL << 5) | (1ULL << 7) | (1ULL << 8) | (1ULL << 13))

struct ll_ruleset {
  uint64_t fs, net, scoped;
};
struct ll_path {
  uint64_t allowed;
  int32_t fd;
} __attribute__((packed));
enum { OBJECT = 1, ARRAY, STRING, NUMBER };
struct node {
  int type, child, next, count;
  char *string;
  uint64_t number;
};
struct parser {
  const unsigned char *cursor, *end;
  struct node nodes[MAX_NODES];
  int used;
};
struct grant {
  char *path;
  int directory, fd;
  uint64_t rights;
};
struct config {
  char *workspace, *cwd, *executable;
  char *argv[MAX_ARGS + 1], *env[MAX_ENV + 1];
  struct grant grants[MAX_GRANTS];
  int count, workspace_fd, cwd_fd;
  uint64_t wall, output, memory, file, fds, processes;
};
struct setup_error {
  int stage, error;
};
static volatile sig_atomic_t cancelled;

static int64_t now_ms(void) {
  struct timespec t;
  if (clock_gettime(CLOCK_MONOTONIC, &t) < 0)
    return -1;
  return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static void cancel_signal(int signal_number) { cancelled = signal_number; }
static int fail(const char *stage) {
  fprintf(stderr, "native-runner: rejected at %s (errno=%d)\n", stage, errno);
  return -1;
}
static void space(struct parser *p) {
  while (p->cursor < p->end && (*p->cursor == ' ' || *p->cursor == '\n' ||
                                *p->cursor == '\r' || *p->cursor == '\t'))
    p->cursor++;
}
static int hex(unsigned char c) {
  if (c >= '0' && c <= '9')
    return c - '0';
  if (c >= 'a' && c <= 'f')
    return c - 'a' + 10;
  if (c >= 'A' && c <= 'F')
    return c - 'A' + 10;
  return -1;
}
static int unicode(struct parser *p, uint32_t *value) {
  *value = 0;
  for (int i = 0; i < 4; i++) {
    if (p->cursor == p->end)
      return -1;
    int h = hex(*p->cursor++);
    if (h < 0)
      return -1;
    *value = (*value << 4) | (unsigned)h;
  }
  return 0;
}
static char *string(struct parser *p) {
  if (p->cursor == p->end || *p->cursor++ != '"')
    return NULL;
  char *s = malloc((size_t)(p->end - p->cursor) + 1);
  if (!s)
    return NULL;
  size_t n = 0;
  while (p->cursor < p->end) {
    unsigned char c = *p->cursor++;
    if (c == '"') {
      s[n] = 0;
      return s;
    }
    if (c < 32)
      break;
    if (c == '\\') {
      if (p->cursor == p->end)
        break;
      c = *p->cursor++;
      if (c == '"' || c == '\\' || c == '/')
        s[n++] = (char)c;
      else if (c == 'b')
        s[n++] = '\b';
      else if (c == 'f')
        s[n++] = '\f';
      else if (c == 'n')
        s[n++] = '\n';
      else if (c == 'r')
        s[n++] = '\r';
      else if (c == 't')
        s[n++] = '\t';
      else if (c == 'u') {
        uint32_t u;
        if (unicode(p, &u) < 0 || u == 0)
          break;
        if (u >= 0xd800 && u <= 0xdbff) {
          uint32_t v;
          if (p->end - p->cursor < 2 || *p->cursor++ != '\\' ||
              *p->cursor++ != 'u' || unicode(p, &v) < 0 || v < 0xdc00 ||
              v > 0xdfff)
            break;
          u = 0x10000 + ((u - 0xd800) << 10) + (v - 0xdc00);
        } else if (u >= 0xdc00 && u <= 0xdfff)
          break;
        if (u < 128)
          s[n++] = (char)u;
        else if (u < 2048) {
          s[n++] = (char)(0xc0 | (u >> 6));
          s[n++] = (char)(0x80 | (u & 63));
        } else if (u < 65536) {
          s[n++] = (char)(0xe0 | (u >> 12));
          s[n++] = (char)(0x80 | ((u >> 6) & 63));
          s[n++] = (char)(0x80 | (u & 63));
        } else {
          s[n++] = (char)(0xf0 | (u >> 18));
          s[n++] = (char)(0x80 | ((u >> 12) & 63));
          s[n++] = (char)(0x80 | ((u >> 6) & 63));
          s[n++] = (char)(0x80 | (u & 63));
        }
      } else
        break;
    } else if (c < 128)
      s[n++] = (char)c;
    else {
      int extra = c >= 0xc2 && c <= 0xdf   ? 1
                  : c >= 0xe0 && c <= 0xef ? 2
                  : c >= 0xf0 && c <= 0xf4 ? 3
                                           : -1;
      if (extra < 0 || p->end - p->cursor < extra)
        break;
      if ((c == 0xe0 && p->cursor[0] < 0xa0) ||
          (c == 0xed && p->cursor[0] >= 0xa0) ||
          (c == 0xf0 && p->cursor[0] < 0x90) ||
          (c == 0xf4 && p->cursor[0] >= 0x90))
        break;
      int valid = 1;
      for (int i = 0; i < extra; i++)
        if ((p->cursor[i] & 0xc0) != 0x80)
          valid = 0;
      if (!valid)
        break;
      s[n++] = (char)c;
      for (int i = 0; i < extra; i++)
        s[n++] = (char)*p->cursor++;
    }
  }
  free(s);
  return NULL;
}
static int value(struct parser *p, int depth) {
  space(p);
  if (depth > 16 || p->cursor == p->end || p->used >= MAX_NODES - 1)
    return -1;
  int index = ++p->used;
  struct node *node = &p->nodes[index];
  unsigned char c = *p->cursor;
  if (c == '"') {
    node->type = STRING;
    node->string = string(p);
    return node->string ? index : -1;
  }
  if (c >= '0' && c <= '9') {
    node->type = NUMBER;
    int zero = c == '0';
    size_t digits = 0;
    while (p->cursor < p->end && isdigit(*p->cursor)) {
      unsigned d = *p->cursor++ - '0';
      if (node->number > (UINT64_MAX - d) / 10)
        return -1;
      node->number = node->number * 10 + d;
      digits++;
    }
    return zero && digits > 1 ? -1 : index;
  }
  if (c != '{' && c != '[')
    return -1;
  node->type = c == '{' ? OBJECT : ARRAY;
  p->cursor++;
  space(p);
  unsigned char end = c == '{' ? '}' : ']';
  int last = 0;
  if (p->cursor < p->end && *p->cursor == end) {
    p->cursor++;
    return index;
  }
  for (;;) {
    int key = 0;
    if (node->type == OBJECT) {
      space(p);
      if (p->cursor == p->end || *p->cursor != '"')
        return -1;
      key = value(p, depth + 1);
      if (key < 0)
        return -1;
      for (int k = node->child; k; k = p->nodes[p->nodes[k].next].next)
        if (!strcmp(p->nodes[k].string, p->nodes[key].string))
          return -1;
      space(p);
      if (p->cursor == p->end || *p->cursor++ != ':')
        return -1;
    }
    int child = value(p, depth + 1);
    if (child < 0)
      return -1;
    int first = key ? key : child;
    if (last)
      p->nodes[last].next = first;
    else
      node->child = first;
    if (key)
      p->nodes[key].next = child;
    last = child;
    node->count++;
    space(p);
    if (p->cursor == p->end)
      return -1;
    c = *p->cursor++;
    if (c == end)
      return index;
    if (c != ',')
      return -1;
  }
}
static struct node *field(struct parser *p, int obj, const char *key) {
  if (obj <= 0 || p->nodes[obj].type != OBJECT)
    return NULL;
  for (int k = p->nodes[obj].child; k; k = p->nodes[p->nodes[k].next].next)
    if (!strcmp(p->nodes[k].string, key))
      return &p->nodes[p->nodes[k].next];
  return NULL;
}
static int keys(struct parser *p, int obj, const char *const *allowed,
                size_t count) {
  if (obj <= 0 || p->nodes[obj].type != OBJECT ||
      p->nodes[obj].count != (int)count)
    return -1;
  for (size_t i = 0; i < count; i++)
    if (!field(p, obj, allowed[i]))
      return -1;
  return 0;
}
static char *text_field(struct parser *p, int obj, const char *key) {
  struct node *n = field(p, obj, key);
  return n && n->type == STRING ? n->string : NULL;
}
static int exact(struct parser *p, int obj, const char *key,
                 const char *expected) {
  char *s = text_field(p, obj, key);
  return s && !strcmp(s, expected);
}
static int number_field(struct parser *p, int obj, const char *key,
                        uint64_t low, uint64_t high, uint64_t *out) {
  struct node *n = field(p, obj, key);
  if (!n || n->type != NUMBER || n->number < low || n->number > high)
    return -1;
  *out = n->number;
  return 0;
}
static int beneath(const char *path, const char *root) {
  size_t n = strlen(root);
  return !strncmp(path, root, n) &&
         (path[n] == 0 || path[n] == '/' || !strcmp(root, "/"));
}
static int canonical(const char *path) {
  char resolved[PATH_MAX];
  return path && path[0] == '/' && strlen(path) < PATH_MAX &&
         realpath(path, resolved) && !strcmp(path, resolved);
}
static int forbidden_tree(const char *path) {
  return !strcmp(path, "/") || beneath(path, "/proc") ||
         beneath(path, "/sys") || beneath(path, "/dev");
}
static int ordinary_filesystem(int fd) {
  struct statfs fs;
  if (fstatfs(fd, &fs) < 0)
    return 0;
  /* Reject alternate mounts of kernel interfaces as well as their conventional
   * path names. A regular inode type alone does not identify ordinary data. */
  switch ((unsigned long)fs.f_type) {
  case PROC_SUPER_MAGIC:
  case SYSFS_MAGIC:
  case DEBUGFS_MAGIC:
  case TRACEFS_MAGIC:
  case SECURITYFS_MAGIC:
  case BPF_FS_MAGIC:
  case CGROUP_SUPER_MAGIC:
  case CGROUP2_SUPER_MAGIC:
  case 0x19800202UL: /* MQUEUE_MAGIC, absent from some userspace magic.h */
  case DEVPTS_SUPER_MAGIC:
  case ANON_INODE_FS_MAGIC:
    errno = EPERM;
    return 0;
  default:
    return 1;
  }
}

static int parse_config(struct parser *p, struct config *c) {
  static const char *const top[] = {
      "schema", "policy",     "metadata", "network", "ipc",    "workspace",
      "cwd",    "executable", "argv",     "env",     "grants", "limits"};
  int root = value(p, 0);
  space(p);
  if (root < 0 || p->cursor != p->end || keys(p, root, top, 12) < 0 ||
      !exact(p, root, "schema", "foldgpt.native-runner.v1") ||
      !exact(p, root, "policy", "landlock-basic-data-v1") ||
      !exact(p, root, "metadata", "visible") ||
      !exact(p, root, "network", "deny") ||
      !exact(p, root, "ipc", "private-pipes-only"))
    return -1;
  c->workspace = text_field(p, root, "workspace");
  c->cwd = text_field(p, root, "cwd");
  c->executable = text_field(p, root, "executable");
  if (!canonical(c->workspace) || !strcmp(c->workspace, "/") ||
      !canonical(c->cwd) || !canonical(c->executable) ||
      !beneath(c->cwd, c->workspace) || forbidden_tree(c->workspace))
    return -1;
  struct node *args = field(p, root, "argv"), *env = field(p, root, "env"),
              *grants = field(p, root, "grants"),
              *limits = field(p, root, "limits");
  if (!args || args->type != ARRAY || args->count < 1 ||
      args->count > MAX_ARGS || !env || env->type != OBJECT ||
      env->count > MAX_ENV || !grants || grants->type != ARRAY ||
      grants->count < 1 || grants->count > MAX_GRANTS || !limits)
    return -1;
  int i = 0;
  for (int k = args->child; k; k = p->nodes[k].next) {
    if (p->nodes[k].type != STRING)
      return -1;
    c->argv[i++] = p->nodes[k].string;
  }
  i = 0;
  for (int k = env->child; k; k = p->nodes[p->nodes[k].next].next) {
    struct node *v = &p->nodes[p->nodes[k].next];
    char *name = p->nodes[k].string;
    if (v->type != STRING || !name[0] || strchr(name, '=') ||
        strlen(name) > 256)
      return -1;
    for (const unsigned char *q = (unsigned char *)name; *q; q++)
      if (*q < 33 || *q > 126)
        return -1;
    size_t n = strlen(name) + strlen(v->string) + 2;
    c->env[i] = malloc(n);
    if (!c->env[i])
      return -1;
    snprintf(c->env[i++], n, "%s=%s", name, v->string);
  }
  static const char *const limit_keys[] = {
      "wallMs",    "outputBytes", "addressSpaceBytes",
      "fileBytes", "openFiles",   "uidProcesses"};
  int li = (int)(limits - p->nodes);
  if (keys(p, li, limit_keys, 6) < 0 ||
      number_field(p, li, "wallMs", 1, 3600000, &c->wall) < 0 ||
      number_field(p, li, "outputBytes", 1, 67108864, &c->output) < 0 ||
      number_field(p, li, "addressSpaceBytes", 16777216, NR_MAX_ADDRESS_SPACE_BYTES,
                   &c->memory) < 0 ||
      number_field(p, li, "fileBytes", 1, 1073741824, &c->file) < 0 ||
      number_field(p, li, "openFiles", 16, 1024, &c->fds) < 0 ||
      number_field(p, li, "uidProcesses", 1, 256, &c->processes) < 0)
    return -1;
  static const char *const grant_keys[] = {"kind", "path", "access"};
  for (int k = grants->child; k; k = p->nodes[k].next) {
    struct grant *g = &c->grants[c->count];
    g->fd = -1;
    if (keys(p, k, grant_keys, 3) < 0)
      return -1;
    char *kind = text_field(p, k, "kind");
    g->path = text_field(p, k, "path");
    if (!kind ||
        (!strcmp(kind, "directory") ? !(g->directory = 1)
                                    : strcmp(kind, "file")) ||
        !canonical(g->path) || forbidden_tree(g->path) ||
        (g->directory && !beneath(g->path, c->workspace)))
      return -1;
    struct node *access = field(p, k, "access");
    if (!access || access->type != ARRAY || access->count < 1 ||
        access->count > 3)
      return -1;
    unsigned seen = 0;
    for (int a = access->child; a; a = p->nodes[a].next) {
      if (p->nodes[a].type != STRING)
        return -1;
      char *s = p->nodes[a].string;
      unsigned bit;
      if (!strcmp(s, "read")) {
        bit = 1;
        g->rights |= LL_READ_FILE | (g->directory ? LL_READ_DIR : 0);
      } else if (!strcmp(s, "write")) {
        bit = 2;
        g->rights |=
            LL_WRITE_FILE | LL_TRUNCATE | (g->directory ? LL_DIR_WRITE : 0);
        if (!beneath(g->path, c->workspace))
          return -1;
      } else if (!strcmp(s, "execute")) {
        bit = 4;
        g->rights |= LL_EXECUTE;
      } else
        return -1;
      if (seen & bit)
        return -1;
      seen |= bit;
    }
    for (int j = 0; j < c->count; j++)
      if (!strcmp(g->path, c->grants[j].path))
        return -1;
    c->count++;
  }
  return 0;
}

/* Initial data profile excludes special files, symlinks and hardlinks inside
 * writable subtrees. The trusted owner must exclude concurrent outside writers.
 */
static int scan_workspace(int fd, unsigned *objects, int depth) {
  if (depth > 64 || ++*objects > 100000) {
    errno = E2BIG;
    return -1;
  }
  struct stat info;
  if (fstat(fd, &info) < 0)
    return -1;
  if (!ordinary_filesystem(fd) || info.st_uid != geteuid() ||
      (info.st_mode & 0077)) {
    errno = EPERM;
    return -1;
  }
  if (S_ISREG(info.st_mode)) {
    if (info.st_nlink != 1) {
      errno = EMLINK;
      return -1;
    }
    return 0;
  }
  if (!S_ISDIR(info.st_mode)) {
    errno = EPERM;
    return -1;
  }
  int listing =
      openat(fd, ".", O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (listing < 0)
    return -1;
  DIR *dir = fdopendir(listing);
  if (!dir) {
    close(listing);
    return -1;
  }
  int result = 0;
  struct dirent *entry;
  errno = 0;
  while ((entry = readdir(dir))) {
    if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, ".."))
      continue;
    int child = openat(fd, entry->d_name, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    if (child < 0 || scan_workspace(child, objects, depth + 1) < 0) {
      if (child >= 0)
        close(child);
      result = -1;
      break;
    }
    close(child);
    errno = 0;
  }
  if (errno)
    result = -1;
  int saved = errno;
  closedir(dir);
  errno = saved;
  return result;
}
static int prepare_paths(struct config *c) {
  c->workspace_fd =
      open(c->workspace, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (c->workspace_fd < 0)
    return -1;
  unsigned objects = 0;
  if (scan_workspace(c->workspace_fd, &objects, 0) < 0)
    return -1;
  c->cwd_fd = open(c->cwd, O_PATH | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
  if (c->cwd_fd < 0)
    return -1;
  struct stat executable;
  if (stat(c->executable, &executable) < 0 || !S_ISREG(executable.st_mode) ||
      (executable.st_mode & (S_ISUID | S_ISGID))) {
    errno = EINVAL;
    return -1;
  }
  for (int i = 0; i < c->count; i++) {
    struct grant *g = &c->grants[i];
    g->fd = open(g->path, O_PATH | O_NOFOLLOW | O_CLOEXEC);
    struct stat info;
    if (g->fd < 0 || fstat(g->fd, &info) < 0 || !ordinary_filesystem(g->fd) ||
        (g->directory ? !S_ISDIR(info.st_mode) : !S_ISREG(info.st_mode))) {
      errno = EINVAL;
      return -1;
    }
    if ((g->rights & LL_WRITE_FILE) &&
        (!S_ISDIR(info.st_mode) && info.st_nlink != 1)) {
      errno = EMLINK;
      return -1;
    }
  }
  return 0;
}
static int no_privilege(void) {
  struct __user_cap_header_struct h = {.version = _LINUX_CAPABILITY_VERSION_3};
  struct __user_cap_data_struct d[2] = {{0}, {0}};
  return geteuid() != 0 && getuid() == geteuid() && getgid() == getegid() &&
         syscall(SYS_capget, &h, d) == 0 &&
         !(d[0].effective | d[0].permitted | d[1].effective | d[1].permitted);
}
static int restrict_landlock(struct config *c) {
  struct ll_ruleset attr = {.fs = LL_HANDLED_FS,
                            .scoped = LL_SCOPE_SIGNAL | LL_SCOPE_ABSTRACT};
  int fd = (int)syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0);
  if (fd < 0)
    return -1;
  for (int i = 0; i < c->count; i++) {
    struct ll_path path = {.allowed = c->grants[i].rights,
                           .fd = c->grants[i].fd};
    if (syscall(SYS_landlock_add_rule, fd, 1, &path, 0) < 0) {
      int saved = errno;
      close(fd);
      errno = saved;
      return -1;
    }
  }
  int result = (int)syscall(SYS_landlock_restrict_self, fd, 0);
  int saved = errno;
  close(fd);
  errno = saved;
  return result;
}
static int limit(int resource, uint64_t amount) {
  struct rlimit l = {.rlim_cur = amount, .rlim_max = amount};
  return setrlimit(resource, &l);
}
static int close_except(int keep) {
  if (keep < 3) {
    errno = EINVAL;
    return -1;
  }
  if (keep > 3 && syscall(SYS_close_range, 3U, (unsigned)keep - 1, 0U) < 0)
    return -1;
  return (int)syscall(SYS_close_range, (unsigned)keep + 1, UINT_MAX, 0U);
}
static void launch(struct config *c, int input, int output, int error,
                   int setup, pid_t supervisor) {
  struct setup_error failure = {.stage = 1};
  if (setpgid(0, 0) < 0 || prctl(PR_SET_PDEATHSIG, SIGKILL, 0, 0, 0) < 0)
    goto failed;
  if (getppid() != supervisor) {
    errno = ECHILD;
    goto failed;
  }
  if (dup2(input, 0) < 0 || dup2(output, 1) < 0 || dup2(error, 2) < 0)
    goto failed;
  /* Trace only the launch transition, not the running command. The parent
   * requires the kernel's PTRACE_EVENT_EXEC before emitting started; EOF alone
   * also occurs when a child is killed before exec and is not such evidence.
   */
  if (ptrace(PTRACE_TRACEME, 0, NULL, NULL) < 0 || raise(SIGSTOP) != 0)
    goto failed;
  /* Preserve the CLOEXEC status pipe until exec, while replacing envp and all
   * other descriptors. Parent uses EOF plus prior status for the exec result.
   */
  failure.stage = 2;
  if (fchdir(c->cwd_fd) < 0 || prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0 ||
      restrict_landlock(c) < 0)
    goto failed;
  if (close_except(setup) < 0)
    goto failed;
  umask(0077);
  failure.stage = 3;
  if (limit(RLIMIT_CORE, 0) < 0 || limit(RLIMIT_AS, c->memory) < 0 ||
      limit(RLIMIT_FSIZE, c->file) < 0 || limit(RLIMIT_NOFILE, c->fds) < 0 ||
      limit(RLIMIT_NPROC, c->processes) < 0 ||
      limit(RLIMIT_CPU, (c->wall + 999) / 1000 + 1) < 0)
    goto failed;
  signal(SIGTERM, SIG_DFL);
  signal(SIGINT, SIG_DFL);
  signal(SIGPIPE, SIG_DFL);
  failure.stage = 4;
  if (nr_install_seccomp() < 0)
    goto failed;
  failure.stage = 5;
  execve(c->executable, c->argv, c->env);
failed:
  failure.error = errno ? errno : EINVAL;
  ssize_t reported = write(setup, &failure, sizeof(failure));
  _exit(reported == (ssize_t)sizeof(failure) ? 125 : 126);
}

static int all_write(int fd, const void *data, size_t size, int64_t deadline,
                     uint64_t *forwarded) {
  size_t done = 0;
  while (done < size) {
    if (cancelled) {
      errno = ECANCELED;
      return -1;
    }
    int64_t now = now_ms();
    if (now < 0 || now >= deadline) {
      errno = ETIMEDOUT;
      return -1;
    }
    struct pollfd p = {.fd = fd, .events = POLLOUT};
    int wait = poll(&p, 1, (int)(deadline - now > 100 ? 100 : deadline - now));
    if (wait < 0 && errno == EINTR)
      continue;
    if (wait < 0)
      return -1;
    if (!wait)
      continue;
    ssize_t n = write(fd, (const char *)data + done, size - done);
    if (n < 0 && (errno == EAGAIN || errno == EINTR))
      continue;
    if (n <= 0) {
      if (!n)
        errno = EPIPE;
      return -1;
    }
    done += (size_t)n;
    if (forwarded)
      *forwarded += (uint64_t)n;
  }
  return 0;
}
static int set_nonblock(int fd) {
  int f = fcntl(fd, F_GETFL);
  return f < 0 ? -1 : fcntl(fd, F_SETFL, f | O_NONBLOCK);
}
static int event(int fd, const char *data) {
  return all_write(fd, data, strlen(data), now_ms() + 1000, NULL);
}
static int supervise(struct config *c, int result_fd) {
  int in[2], out[2], err[2], status_pipe[2];
  if (pipe2(in, O_CLOEXEC) < 0 || pipe2(out, O_CLOEXEC) < 0 ||
      pipe2(err, O_CLOEXEC) < 0 || pipe2(status_pipe, O_CLOEXEC) < 0)
    return fail("pipes");
  if (prctl(PR_SET_CHILD_SUBREAPER, 1, 0, 0, 0) < 0)
    return fail("subreaper");
  pid_t supervisor = getpid();
  pid_t pid = fork();
  if (!pid)
    launch(c, in[0], out[1], err[1], status_pipe[1], supervisor);
  close(in[0]);
  close(in[1]);
  close(out[1]);
  close(err[1]);
  close(status_pipe[1]);
  if (pid < 0)
    return fail("fork");
  (void)set_nonblock(out[0]);
  (void)set_nonblock(err[0]);
  (void)set_nonblock(status_pipe[0]);
  int64_t start = now_ms(), end = start + (int64_t)c->wall, cleanup_end = 0;
  int alive = 1, leader_status = 0, leader_reaped = 0, leader_observed = 0,
      group_killed = 0, traced = 0, exec_confirmed = 0, eof[3] = {0, 0, 0},
      started = 0, terminating = 0, error_stage = 0, saved_error = 0;
  uint64_t bytes[2] = {0, 0};
  char buffer[8192], json[512];
  const char *outcome = "exited";
  struct setup_error setup = {0};
  size_t setup_size = 0;
  while (alive || !eof[0] || !eof[1] || !eof[2]) {
    int64_t now = now_ms();
    if (now < 0) {
      outcome = "cleanup_error";
      saved_error = errno;
      now = end;
    }
    if (!terminating && (cancelled || now >= end)) {
      outcome = cancelled ? "cancelled" : "timeout";
      terminating = 1;
      cleanup_end = now + 5000;
    }
    if (!exec_confirmed && !leader_observed) {
      siginfo_t observed = {0};
      if (waitid(P_PID, (id_t)pid, &observed,
                 WSTOPPED | WEXITED | WNOHANG | WNOWAIT) == 0 &&
          observed.si_pid == pid &&
          (observed.si_code == CLD_TRAPPED ||
           observed.si_code == CLD_STOPPED)) {
        int status = 0;
        if (waitpid(pid, &status, WNOHANG | __WALL) == pid &&
            WIFSTOPPED(status)) {
          if (!traced && WSTOPSIG(status) == SIGSTOP) {
            if (getpgid(pid) != pid ||
                ptrace(PTRACE_SETOPTIONS, pid, NULL,
                       (void *)(uintptr_t)(PTRACE_O_TRACEEXEC |
                                           PTRACE_O_EXITKILL)) < 0 ||
                ptrace(PTRACE_CONT, pid, NULL, NULL) < 0) {
              outcome = "setup_error";
              error_stage = 1;
              saved_error = errno;
              terminating = 1;
              cleanup_end = now + 5000;
            } else
              traced = 1;
          } else if (traced && (unsigned)status >> 16 == PTRACE_EVENT_EXEC) {
            if (ptrace(PTRACE_DETACH, pid, NULL, NULL) < 0) {
              outcome = "setup_error";
              error_stage = 5;
              saved_error = errno;
              terminating = 1;
              cleanup_end = now + 5000;
            } else {
              exec_confirmed = 1;
              if (!terminating) {
                snprintf(json, sizeof(json),
                         "{\"type\":\"started\",\"pid\":%d,\"policy\":"
                         "\"landlock-basic-data-v1\"}\n",
                         pid);
                if (event(result_fd, json) < 0) {
                  outcome = "cancelled";
                  saved_error = errno;
                  terminating = 1;
                  cleanup_end = now + 5000;
                } else
                  started = 1;
              }
            }
          } else {
            if (ptrace(PTRACE_CONT, pid, NULL,
                       (void *)(uintptr_t)WSTOPSIG(status)) < 0) {
              outcome = "setup_error";
              error_stage = 1;
              saved_error = errno;
              terminating = 1;
              cleanup_end = now + 5000;
            }
          }
        }
      }
    }
    if (terminating) {
      if (!leader_reaped) {
        if (kill(-pid, SIGKILL) == 0)
          group_killed = 1;
        /* The direct PID remains ours and unreaped even if cancellation won
         * before the trusted child established its separate process group. */
        (void)kill(pid, SIGKILL);
      }
      if (now >= cleanup_end) {
        outcome = "cleanup_error";
        saved_error = ETIMEDOUT;
        break;
      }
    }
    struct pollfd fds[3] = {
        {.fd = eof[0] ? -1 : out[0], .events = POLLIN},
        {.fd = eof[1] ? -1 : err[0], .events = POLLIN},
        {.fd = eof[2] ? -1 : status_pipe[0], .events = POLLIN}};
    int polled = poll(fds, 3, 20);
    if (polled < 0 && errno != EINTR) {
      outcome = "cleanup_error";
      saved_error = errno;
      terminating = 1;
      cleanup_end = now + 5000;
    }
    for (int i = 0; i < 3; i++)
      if (!eof[i] && (fds[i].revents & (POLLIN | POLLHUP | POLLERR))) {
        ssize_t n = read(fds[i].fd, buffer, sizeof(buffer));
        if (!n) {
          eof[i] = 1;
          if (i == 2) {
            if (setup_size) {
              outcome = "setup_error";
              error_stage = setup_size == sizeof(setup) ? setup.stage : 0;
              saved_error = setup_size == sizeof(setup) ? setup.error : EPROTO;
              terminating = 1;
              cleanup_end = now + 5000;
            }
          }
        } else if (n > 0) {
          if (i == 2) {
            size_t available = sizeof(setup) - setup_size;
            if ((size_t)n > available) {
              outcome = "setup_error";
              saved_error = EPROTO;
              terminating = 1;
              cleanup_end = now + 5000;
            } else {
              memcpy((char *)&setup + setup_size, buffer, (size_t)n);
              setup_size += (size_t)n;
            }
          } else {
            uint64_t total = bytes[0] + bytes[1],
                     remaining = total < c->output ? c->output - total : 0;
            size_t accepted =
                (uint64_t)n < remaining ? (size_t)n : (size_t)remaining;
            if (accepted && !strcmp(outcome, "exited")) {
              if (all_write(i + 1, buffer, accepted, end, &bytes[i]) < 0) {
                outcome = cancelled            ? "cancelled"
                          : errno == ETIMEDOUT ? "timeout"
                                               : "output_limit";
                saved_error = errno;
                terminating = 1;
                cleanup_end = now_ms() + 5000;
              }
            }
            if (accepted < (size_t)n && !strcmp(outcome, "exited")) {
              outcome = "output_limit";
              terminating = 1;
              cleanup_end = now_ms() + 5000;
            }
          }
        } else if (errno != EAGAIN && errno != EINTR) {
          outcome = "cleanup_error";
          saved_error = errno;
          terminating = 1;
          cleanup_end = now + 5000;
        }
      }
    /* Keep the group leader as a zombie until group termination. Its PID
     * cannot be reused while we send process-group signals. Once reaped,
     * never signal that numeric group again; seccomp prevents group escape.
     */
    if (!leader_observed) {
      siginfo_t info = {0};
      if (waitid(P_PID, (id_t)pid, &info, WEXITED | WNOHANG | WNOWAIT) == 0 &&
          info.si_pid == pid &&
          (info.si_code == CLD_EXITED || info.si_code == CLD_KILLED ||
           info.si_code == CLD_DUMPED)) {
        leader_observed = 1;
        if (!terminating) {
          terminating = 1;
          cleanup_end = now_ms() + 5000;
        }
        if (kill(-pid, SIGKILL) == 0)
          group_killed = 1;
      }
    }
    if (leader_observed && !leader_reaped) {
      pid_t r = waitpid(pid, &leader_status, WNOHANG);
      if (r == pid)
        leader_reaped = 1;
    }
    /* Reap only after the leader was observed. Before then waitpid(-1)
     * could consume its exit and lose the PID pin used above.
     */
    if (leader_reaped)
      for (;;) {
        int status;
        pid_t child = waitpid(-1, &status, WNOHANG | __WALL);
        if (child > 0)
          continue;
        if (child < 0 && errno == ECHILD)
          alive = 0;
        else if (child < 0 && errno != EINTR) {
          outcome = "cleanup_error";
          saved_error = errno;
        }
        break;
      }
  }
  close(out[0]);
  close(err[0]);
  close(status_pipe[0]);
  int complete = !alive && leader_reaped && (group_killed || !exec_confirmed);
  int code = leader_reaped && WIFEXITED(leader_status)
                 ? WEXITSTATUS(leader_status)
                 : -1;
  int sig =
      leader_reaped && WIFSIGNALED(leader_status) ? WTERMSIG(leader_status) : 0;
  if (!complete)
    outcome = "cleanup_error";
  if (!started && !strcmp(outcome, "exited")) {
    outcome = "setup_error";
    error_stage = 5;
    saved_error = EIO;
  }
  char code_text[32], signal_text[32], stage_text[32];
  if (code >= 0)
    snprintf(code_text, sizeof(code_text), "%d", code);
  else
    strcpy(code_text, "null");
  if (sig)
    snprintf(signal_text, sizeof(signal_text), "%d", sig);
  else
    strcpy(signal_text, "null");
  static const char *const names[] = {"unknown", "launch",  "landlock",
                                      "limits",  "seccomp", "exec"};
  if (error_stage)
    snprintf(stage_text, sizeof(stage_text), "\"%s\"",
             names[error_stage >= 1 && error_stage <= 5 ? error_stage : 0]);
  else
    strcpy(stage_text, "null");
  snprintf(json, sizeof(json),
           "{\"type\":\"result\",\"outcome\":\"%s\",\"exitCode\":%s,\"signal\":"
           "%s,\"stdoutBytes\":%llu,\"stderrBytes\":%llu,\"cleanupComplete\":%"
           "s,\"errorStage\":%s,\"errno\":%d}\n",
           outcome, code_text, signal_text, (unsigned long long)bytes[0],
           (unsigned long long)bytes[1], complete ? "true" : "false",
           stage_text, saved_error);
  cancelled = 0;
  if (event(result_fd, json) < 0)
    return 1;
  return !strcmp(outcome, "exited") ? 0 : 1;
}

int main(int argc, char **argv) {
  if (argc != 3 || strcmp(argv[1], "--result-fd")) {
    fprintf(stderr, "Usage: native-runner --result-fd N < manifest.json\n");
    return 2;
  }
  char *end;
  long result = strtol(argv[2], &end, 10);
  struct stat control;
  if (*end || result < 3 || result > INT_MAX ||
      fstat((int)result, &control) < 0 || !S_ISFIFO(control.st_mode) ||
      !no_privilege()) {
    errno = EINVAL;
    fail("invocation");
    return 2;
  }
  if (syscall(SYS_landlock_create_ruleset, NULL, 0, 1U) < 6) {
    fail("landlock_abi");
    return 2;
  }
  signal(SIGPIPE, SIG_IGN);
  signal(SIGTERM, cancel_signal);
  signal(SIGINT, cancel_signal);
  unsigned char input[MAX_MANIFEST + 1];
  size_t n = 0;
  int64_t deadline = now_ms() + 5000;
  for (;;) {
    if (n == sizeof(input)) {
      fail("manifest_size");
      return 2;
    }
    if (now_ms() >= deadline || cancelled) {
      errno = ETIMEDOUT;
      fail("manifest_deadline");
      return 2;
    }
    struct pollfd p = {.fd = 0, .events = POLLIN};
    int ready = poll(&p, 1, 100);
    if (ready < 0 && errno == EINTR)
      continue;
    if (ready < 0)
      return 2;
    if (!ready)
      continue;
    ssize_t got = read(0, input + n, sizeof(input) - n);
    if (got < 0 && errno == EINTR)
      continue;
    if (got < 0)
      return 2;
    if (!got)
      break;
    n += (size_t)got;
  }
  struct parser *parser = calloc(1, sizeof(*parser));
  struct config config = {.workspace_fd = -1, .cwd_fd = -1};
  if (!parser)
    return 2;
  for (int i = 0; i < MAX_GRANTS; i++)
    config.grants[i].fd = -1;
  parser->cursor = input;
  parser->end = input + n;
  if (parse_config(parser, &config) < 0 || prepare_paths(&config) < 0) {
    fail("manifest_or_paths");
    return 2;
  }
  if (set_nonblock(1) < 0 || set_nonblock(2) < 0 ||
      set_nonblock((int)result) < 0) {
    fail("output_descriptors");
    return 2;
  }
  int code = supervise(&config, (int)result);
  for (int i = 0; i < config.count; i++)
    if (config.grants[i].fd >= 0)
      close(config.grants[i].fd);
  if (config.workspace_fd >= 0)
    close(config.workspace_fd);
  if (config.cwd_fd >= 0)
    close(config.cwd_fd);
  for (int i = 0; i < MAX_ENV; i++)
    free(config.env[i]);
  for (int i = 1; i <= parser->used; i++)
    free(parser->nodes[i].string);
  free(parser);
  return code < 0 ? 1 : code;
}
