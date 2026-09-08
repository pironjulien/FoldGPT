/* This fixed pre-interpreter admission runs after Android run-as. It validates
 * the private data before Python can import it; no worker starts here. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/capability.h>
#include <openssl/evp.h>
#include <signal.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

struct runtime_file { const char *path; size_t size; const char *sha256; };
struct runtime_alias { const char *path; const char *library; };
#include "runtime-inventory.h"
#define ROOT "/data/user/0/app.foldgpt/files/runas-native-v2/python"

static const char *trial_nonce = "";
static int refuse(const char *stage) {
    int error = errno;
    fprintf(stderr, "{\"schema\":\"foldgpt.runas.broker-admission.v2\",\"stage\":\"%s\",\"errno\":%d,"
                    "\"passed\":false,\"nativeWorkerStarted\":false,\"pid\":%d,\"nonce\":\"%s\"}\n", stage, error, getpid(), trial_nonce);
    return 70;
}
static int hash_file(const char *path, const char *expected, size_t size, uid_t owner, int private_data) {
    int fd = open(path, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
    if (fd < 0) return 0;
    struct stat before, after;
    int ok = fstat(fd, &before) == 0 && S_ISREG(before.st_mode) && !(before.st_mode & 022)
        && before.st_nlink == 1 && before.st_size >= 0 && (size_t)before.st_size == size
        && (!private_data || before.st_uid == owner);
    EVP_MD_CTX *hash = EVP_MD_CTX_new();
    if (hash == NULL || EVP_DigestInit_ex(hash, EVP_sha256(), NULL) != 1) ok = 0;
    unsigned char buffer[65536], digest[EVP_MAX_MD_SIZE];
    size_t total = 0;
    while (ok) {
        ssize_t count = read(fd, buffer, sizeof(buffer));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0) { ok = 0; break; }
        if (!count) break;
        total += (size_t)count;
        if (total > size || EVP_DigestUpdate(hash, buffer, (size_t)count) != 1) ok = 0;
    }
    unsigned int length = 0;
    if (ok && (total != size || EVP_DigestFinal_ex(hash, digest, &length) != 1 || length != 32)) ok = 0;
    if (ok) {
        char hex[65];
        for (unsigned int i = 0; i < length; ++i) snprintf(hex + i * 2, 3, "%02x", digest[i]);
        ok = !strcmp(hex, expected) && fstat(fd, &after) == 0 && before.st_dev == after.st_dev
            && before.st_ino == after.st_ino && before.st_size == after.st_size
            && before.st_mtim.tv_sec == after.st_mtim.tv_sec && before.st_mtim.tv_nsec == after.st_mtim.tv_nsec;
    }
    EVP_MD_CTX_free(hash);
    close(fd);
    return ok;
}
static int directory_owned(const char *path, uid_t uid, int private_root) {
    char canonical[PATH_MAX]; struct stat st;
    return realpath(path, canonical) && !strcmp(path, canonical) && lstat(path, &st) == 0
        && S_ISDIR(st.st_mode) && st.st_uid == uid
        && (private_root < 0 || !(st.st_mode & (private_root ? 077 : 022)));
}
static int tree(const char *path, uid_t uid, size_t *leaves, unsigned int depth) {
    if (depth > 32 || !directory_owned(path, uid, 0)) return 0;
    DIR *directory = opendir(path);
    if (!directory) return 0;
    struct dirent *entry; int ok = 1;
    errno = 0;
    while (ok && (entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char child[PATH_MAX]; struct stat st;
        if (snprintf(child, sizeof(child), "%s/%s", path, entry->d_name) >= (int)sizeof(child)
            || lstat(child, &st) < 0 || st.st_uid != uid) { ok = 0; break; }
        if (S_ISDIR(st.st_mode)) ok = tree(child, uid, leaves, depth + 1);
        else if (S_ISREG(st.st_mode) || S_ISLNK(st.st_mode)) ++*leaves;
        else ok = 0;
        errno = 0;
    }
    if (errno) ok = 0;
    closedir(directory);
    return ok;
}
static int number(const char *value) {
    char *end; errno = 0;
    long parsed = strtol(value, &end, 10);
    return errno || *end || parsed <= 0 || parsed > INT_MAX ? -1 : (int)parsed;
}
int main(int argc, char **argv) {
    struct sigaction deadline = {.sa_handler = SIG_DFL};
    sigset_t deadline_signal;
    if (sigemptyset(&deadline.sa_mask) || sigaction(SIGALRM, &deadline, NULL)
        || sigemptyset(&deadline_signal) || sigaddset(&deadline_signal, SIGALRM)
        || sigprocmask(SIG_UNBLOCK, &deadline_signal, NULL)) return refuse("deadline");
    alarm(30);
    if (argc != 7 || strcmp(argv[1], "--broker-v2") || strcmp(argv[3], "/data/user/0/app.foldgpt")
        || strlen(argv[5]) != 32 || strspn(argv[5], "0123456789abcdef") != 32) return refuse("arguments");
    trial_nonce = argv[5];
    int expected = number(argv[2]), parent = number(argv[4]);
    uid_t ur = 0, ue = 0, us = 0; gid_t gr = 0, ge = 0, gs = 0;
    if (expected < 10000 || parent < 1 || getresuid(&ur, &ue, &us) || getresgid(&gr, &ge, &gs)
        || ur != (uid_t)expected || ue != ur || us != ur || gr != ur || ge != gr || gs != gr
        || getppid() != parent || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 0
        || prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != 0) return refuse("identity");
    struct __user_cap_header_struct caps_header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct caps[2] = {{0}, {0}};
    if (syscall(__NR_capget, &caps_header, caps)) return refuse("capabilities");
    for (int i = 0; i < 2; ++i) if (caps[i].effective || caps[i].permitted || caps[i].inheritable) return refuse("capabilities");
    char own[PATH_MAX], directory[PATH_MAX], python[PATH_MAX];
    ssize_t count = readlink("/proc/self/exe", own, sizeof(own) - 1);
    if (count <= 0 || count >= (ssize_t)sizeof(own) - 1) return refuse("own-executable");
    own[count] = 0;
    char *slash = strrchr(own, '/');
    if (!slash || strcmp(slash + 1, "libfoldgpt_runas_broker_bootstrap.so")) return refuse("own-executable");
    *slash = 0; strcpy(directory, own);
    if (strncmp(directory, "/data/app/", 10) || strncmp(argv[6], "/data/app/", 10)) return refuse("installed-prefix");
    // The installed application's root is the private traversal boundary.
    // Its existing files/ may legitimately use broader bits; require actual
    // ownership/canonical identity there, keeping our new subtree owner-only.
    if (!directory_owned("/data/user/0/app.foldgpt", ur, 1)
        || !directory_owned("/data/user/0/app.foldgpt/files", ur, -1)
        || !directory_owned("/data/user/0/app.foldgpt/files/runas-native-v2", ur, 1)
        || !directory_owned(ROOT, ur, 1)) return refuse("private-root");
    for (size_t i = 0; i < sizeof(runtime_files) / sizeof(*runtime_files); ++i) {
        char path[PATH_MAX], canonical[PATH_MAX];
        if (snprintf(path, sizeof(path), "%s/%s", ROOT, runtime_files[i].path) >= (int)sizeof(path)
            || !realpath(path, canonical) || strcmp(path, canonical)
            || !hash_file(path, runtime_files[i].sha256, runtime_files[i].size, ur, 1)) return refuse("runtime-data");
    }
    for (size_t i = 0; i < sizeof(runtime_aliases) / sizeof(*runtime_aliases); ++i) {
        char path[PATH_MAX], target[PATH_MAX], actual[PATH_MAX]; struct stat st;
        if (snprintf(path, sizeof(path), "%s/%s", ROOT, runtime_aliases[i].path) >= (int)sizeof(path)
            || snprintf(target, sizeof(target), "%s/%s", directory, runtime_aliases[i].library) >= (int)sizeof(target)
            || lstat(path, &st) || !S_ISLNK(st.st_mode) || st.st_uid != ur) return refuse("runtime-alias");
        ssize_t size = readlink(path, actual, sizeof(actual) - 1);
        if (size <= 0 || size >= (ssize_t)sizeof(actual) - 1) return refuse("runtime-alias");
        actual[size] = 0;
        if (strcmp(target, actual) || !realpath(path, actual) || strcmp(target, actual)) return refuse("runtime-alias");
    }
    size_t leaves = 0;
    if (!tree(ROOT, ur, &leaves, 0)
        || leaves != sizeof(runtime_files) / sizeof(*runtime_files) + sizeof(runtime_aliases) / sizeof(*runtime_aliases)) {
        return refuse("runtime-tree");
    }
    for (size_t i = 0; i < sizeof(native_files) / sizeof(*native_files); ++i) {
        char path[PATH_MAX];
        if (snprintf(path, sizeof(path), "%s/%s", directory, native_files[i].path) >= (int)sizeof(path)
            || !hash_file(path, native_files[i].sha256, native_files[i].size, 0, 0)) return refuse("native-inventory");
    }
    if (snprintf(python, sizeof(python), "%s/libfoldgpt_python_cli.so", directory) >= (int)sizeof(python)) return refuse("python-path");
    static const char entry[] = "import sys;sys.path.insert(0,sys.argv[1]+'/assets/foldgpt-runas-broker');from foldgpt_runas_broker import main;main(sys.argv[1:])";
    char *arguments[] = {python, "-I", "-S", "-B", "-u", "-c", (char *)entry, argv[6], argv[2], argv[4], argv[5], NULL};
    char *environment[] = {NULL};
    // The setup deadline survives exec and Python imports. Python cancels it
    // just before entering the existing supervisor, which owns cancellation,
    // its bounded worker and any unresolved quarantine from that point.
    execve(python, arguments, environment);
    return refuse("python-exec");
}
