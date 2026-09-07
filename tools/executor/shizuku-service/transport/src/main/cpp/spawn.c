/* The child performs only async-signal-safe operations between fork and exec.
 * No shell, client-controlled executable, root path, process signal API or VM.
 */
#define _GNU_SOURCE
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/capability.h>
#include <stdlib.h>
#include <string.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>
#ifdef FOLDGPT_TRANSPORT_HOST_TEST
#define EXPECTED_UID 65534
#else
#define EXPECTED_UID 2000
#endif

static int admitted_identity(void) {
    uid_t real, effective, saved;
    gid_t greal, geffective, gsaved;
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct capabilities[2] = {{0}, {0}};
    if (getresuid(&real, &effective, &saved) < 0 || getresgid(&greal, &geffective, &gsaved) < 0 ||
            real != EXPECTED_UID || effective != real || saved != real ||
            greal != EXPECTED_UID || geffective != greal || gsaved != greal ||
            syscall(__NR_capget, &header, capabilities) < 0) return 0;
    for (int i = 0; i < 2; ++i) {
        if (capabilities[i].effective || capabilities[i].permitted || capabilities[i].inheritable) return 0;
    }
    /* Ambient caps must be subsets of both permitted and inheritable caps. */
    return 1;
}

static void failure(JNIEnv *env, const char *message) {
    jclass type = (*env)->FindClass(env, "java/io/IOException");
    if (type != NULL) (*env)->ThrowNew(env, type, message);
}

JNIEXPORT jint JNICALL Java_app_foldgpt_shizukuexec_NativeSpawn_launch(
        JNIEnv *env, jclass cls, jstring executable, jobjectArray arguments,
        jint input, jint output, jint report, jint control) {
    (void)cls;
    if (!admitted_identity()) {
        failure(env, "The executor requires non-root shell UID 2000"); return -1;
    }
    jsize count = (*env)->GetArrayLength(env, arguments);
    if (count < 1 || count > 16) { failure(env, "Invalid fixed bootstrap argv"); return -1; }
    char *argv[17] = {0};
    int sources[4] = {input, output, report, control};
    int fds[4] = {-1, -1, -1, -1};
    const char *entry = (*env)->GetStringUTFChars(env, executable, NULL);
    if (entry == NULL) return -1;
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
    /* Duplicate before fork so dup2 cannot overwrite another source. */
    for (int i = 0; i < 4; ++i) {
        fds[i] = fcntl(sources[i], F_DUPFD_CLOEXEC, 10);
        if (fds[i] < 0) goto done;
    }
    pid = fork();
    if (pid == 0) {
        static char *const empty_environment[] = {NULL};
        for (int i = 0; i < 4; ++i) if (dup2(fds[i], i) < 0) _exit(126);
        /* Required close_range support: never inherit Binder or JVM FDs. */
        if (syscall(__NR_close_range, 4U, UINT_MAX, 0U) < 0) _exit(126);
        if (chdir("/") < 0) _exit(126);
        execve(entry, argv, empty_environment);
        _exit(126);
    }
done:
    for (int i = 0; i < 4; ++i) if (fds[i] >= 0) close(fds[i]);
    for (jsize i = 0; i < count; ++i) free(argv[i]);
    (*env)->ReleaseStringUTFChars(env, executable, entry);
    if (pid < 0 && !(*env)->ExceptionCheck(env)) failure(env, "Native bootstrap fork/admission failed");
    return pid;
}

JNIEXPORT jint JNICALL Java_app_foldgpt_shizukuexec_NativeSpawn_waitChild(
        JNIEnv *env, jclass cls, jint pid) {
    (void)cls;
    if (pid <= 0) { failure(env, "No owned bootstrap child"); return -1; }
    int status;
    pid_t found;
    do { found = waitpid(pid, &status, 0); } while (found < 0 && errno == EINTR);
    if (found != pid) { failure(env, "Bootstrap ownership could not be reaped"); return -1; }
    return status;
}
