/* Separate Android application transport. Between fork and exec, use only
 * async-signal-safe operations; never inherit Binder/JVM descriptors. */
#define _GNU_SOURCE
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/capability.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static int admitted_identity(uid_t application_uid) {
    uid_t real, effective, saved;
    gid_t greal, geffective, gsaved;
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct capabilities[2] = {{0}, {0}};
    if (application_uid < 10000 ||
            getresuid(&real, &effective, &saved) < 0 || getresgid(&greal, &geffective, &gsaved) < 0 ||
            real != application_uid || effective != real || saved != real ||
            greal != application_uid || geffective != greal || gsaved != greal ||
            prctl(PR_GET_SECCOMP, 0, 0, 0, 0) != 2 || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 0 ||
            syscall(__NR_capget, &header, capabilities) < 0) return 0;
    for (int i = 0; i < 2; ++i) {
        if (capabilities[i].effective || capabilities[i].permitted || capabilities[i].inheritable) return 0;
    }
    /* Empty permitted/inheritable sets also exclude all ambient capabilities. */
    return 1;
}

static int same_private_data(const char *declared, const char *canonical, uid_t uid) {
    char actual[PATH_MAX];
    struct stat named, resolved;
    if (strcmp(declared, "/data/user/0/app.foldgpt") != 0 ||
            (strcmp(canonical, declared) != 0 && strcmp(canonical, "/data/data/app.foldgpt") != 0) ||
            realpath(declared, actual) == NULL || strcmp(actual, canonical) != 0 ||
            lstat(declared, &named) < 0 || lstat(canonical, &resolved) < 0 ||
            !S_ISDIR(named.st_mode) || !S_ISDIR(resolved.st_mode) ||
            named.st_uid != uid || named.st_gid != uid || resolved.st_uid != uid || resolved.st_gid != uid ||
            (named.st_mode & 0077) != 0 || (resolved.st_mode & 0077) != 0 ||
            named.st_dev != resolved.st_dev || named.st_ino != resolved.st_ino) return 0;
    return 1;
}

static int fixed_arguments(const char *entry, char *const argv[], int count, uid_t uid, const char *data) {
    char number[32], expected[PATH_MAX], actual_launch[PATH_MAX];
    const char *base = strrchr(entry, '/');
    if (count != 8 || !base || strcmp(base + 1, "libfoldgpt_app_bootstrap.so") != 0 ||
            strncmp(entry, "/data/app/", 10) != 0 || strcmp(argv[0], entry) != 0 ||
            strcmp(argv[1], "--app-runtime-v1") != 0) return 0;
    snprintf(number, sizeof(number), "%u", (unsigned)uid);
    if (strcmp(argv[2], number) != 0 || !same_private_data(argv[3], data, uid)) return 0;
    snprintf(number, sizeof(number), "%d", (int)getpid());
    if (strcmp(argv[4], number) != 0 || strlen(argv[5]) != 32 ||
            strspn(argv[5], "0123456789abcdef") != 32 || strncmp(argv[6], "/data/app/", 10) != 0) return 0;
    int length = snprintf(expected, sizeof(expected), "%s/app_foldgpt_exec/%s/launch.json", data, argv[5]);
    return length > 0 && (size_t)length < sizeof(expected) && strcmp(argv[7], expected) == 0 &&
            realpath(argv[7], actual_launch) != NULL && strcmp(actual_launch, argv[7]) == 0;
}

static void failure(JNIEnv *env, const char *message) {
    jclass type = (*env)->FindClass(env, "java/io/IOException");
    if (type != NULL) (*env)->ThrowNew(env, type, message);
}

JNIEXPORT jint JNICALL Java_app_foldgpt_shizukuexec_AppNativeSpawn_launch(
        JNIEnv *env, jclass cls, jstring executable, jobjectArray arguments,
        jint application_uid, jstring canonical_data, jint input, jint output, jint report, jint control) {
    (void)cls;
    if (application_uid < 10000 || !admitted_identity((uid_t)application_uid)) {
        failure(env, "Application transport requires the exact non-root app identity and inherited seccomp 2");
        return -1;
    }
    if (!executable || !arguments || !canonical_data) {
        failure(env, "Missing fixed application bootstrap input"); return -1;
    }
    jsize count = (*env)->GetArrayLength(env, arguments);
    if (count != 8) { failure(env, "Invalid fixed application bootstrap argv"); return -1; }
    char *argv[9] = {0};
    int sources[4] = {input, output, report, control};
    int fds[4] = {-1, -1, -1, -1};
    const char *entry = (*env)->GetStringUTFChars(env, executable, NULL);
    if (entry == NULL) return -1;
    const char *data = (*env)->GetStringUTFChars(env, canonical_data, NULL);
    if (data == NULL) { (*env)->ReleaseStringUTFChars(env, executable, entry); return -1; }
    pid_t pid = -1;
    for (jsize i = 0; i < count; ++i) {
        jstring argument = (jstring)(*env)->GetObjectArrayElement(env, arguments, i);
        if (argument == NULL) goto done;
        const char *bytes = (*env)->GetStringUTFChars(env, argument, NULL);
        if (bytes == NULL) { (*env)->DeleteLocalRef(env, argument); goto done; }
        argv[i] = strdup(bytes);
        (*env)->ReleaseStringUTFChars(env, argument, bytes);
        (*env)->DeleteLocalRef(env, argument);
        if (argv[i] == NULL) goto done;
    }
    if (!fixed_arguments(entry, argv, count, (uid_t)application_uid, data)) goto done;
    for (int i = 0; i < 4; ++i) {
        fds[i] = fcntl(sources[i], F_DUPFD_CLOEXEC, 10);
        if (fds[i] < 0) goto done;
    }
    pid = fork();
    if (pid == 0) {
        static char *const empty_environment[] = {NULL};
        for (int i = 0; i < 4; ++i) if (dup2(fds[i], i) < 0) _exit(126);
        if (syscall(__NR_close_range, 4U, UINT_MAX, 0U) < 0) _exit(126);
        if (chdir(data) < 0) _exit(126);
        execve(entry, argv, empty_environment);
        _exit(126);
    }
done:
    for (int i = 0; i < 4; ++i) if (fds[i] >= 0) close(fds[i]);
    for (jsize i = 0; i < count; ++i) free(argv[i]);
    (*env)->ReleaseStringUTFChars(env, canonical_data, data);
    (*env)->ReleaseStringUTFChars(env, executable, entry);
    if (pid < 0 && !(*env)->ExceptionCheck(env)) failure(env, "Application bootstrap fork/admission failed");
    return pid;
}

JNIEXPORT jint JNICALL Java_app_foldgpt_shizukuexec_AppNativeSpawn_waitChild(
        JNIEnv *env, jclass cls, jint pid) {
    (void)cls;
    if (pid <= 0) { failure(env, "No owned application bootstrap child"); return -1; }
    int status;
    pid_t found;
    do { found = waitpid(pid, &status, 0); } while (found < 0 && errno == EINTR);
    if (found != pid) { failure(env, "Application bootstrap ownership could not be reaped"); return -1; }
    return status;
}
