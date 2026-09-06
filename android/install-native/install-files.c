/* SPDX-License-Identifier: GPL-3.0-or-later */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <jni.h>
#include <limits.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

static int path_bytes(JNIEnv *env, jbyteArray input, char *output, size_t capacity) {
    if (!input) return EINVAL;
    jsize size = (*env)->GetArrayLength(env, input);
    if (size <= 0 || (size_t)size >= capacity) return ENAMETOOLONG;
    (*env)->GetByteArrayRegion(env, input, 0, size, (jbyte *)output);
    if ((*env)->ExceptionCheck(env)) return EINVAL;
    if (memchr(output, 0, (size_t)size)) return EINVAL;
    output[size] = 0;
    return 0;
}

JNIEXPORT jint JNICALL
Java_app_foldgpt_install_NativeInstallFiles_setLinkTime(
        JNIEnv *env, jclass cls, jbyteArray parent, jbyteArray name,
        jlong seconds, jint nanos) {
    (void)cls;
    char parent_path[PATH_MAX], basename[NAME_MAX + 1];
    int error = path_bytes(env, parent, parent_path, sizeof(parent_path));
    if (!error) error = path_bytes(env, name, basename, sizeof(basename));
    if (error) return error;
    if (parent_path[0] != '/' || strchr(basename, '/') || !strcmp(basename, ".")
            || !strcmp(basename, "..") || nanos < 0 || nanos >= 1000000000) return EINVAL;
    int directory = open(parent_path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (directory < 0) return errno;
    struct stat parent_stat, before, after;
    if (fstat(directory, &parent_stat) < 0) error = errno;
    else if (parent_stat.st_uid != getuid()) error = EPERM;
    else if (fstatat(directory, basename, &before, AT_SYMLINK_NOFOLLOW) < 0) error = errno;
    else if (!S_ISLNK(before.st_mode) || before.st_uid != getuid()) error = EPERM;
    // The parent FD is pinned. The exclusive staging contract prevents other
    // writers; never follow the guest link, including absolute guest targets.
    if (!error) {
        struct timespec timestamps[2] = {
            {.tv_sec = 0, .tv_nsec = UTIME_OMIT},
            {.tv_sec = (time_t)seconds, .tv_nsec = nanos}
        };
        if ((jlong)timestamps[1].tv_sec != seconds) error = EOVERFLOW;
        else if (utimensat(directory, basename, timestamps, AT_SYMLINK_NOFOLLOW) < 0) error = errno;
        else if (fstatat(directory, basename, &after, AT_SYMLINK_NOFOLLOW) < 0) error = errno;
        else if (before.st_dev != after.st_dev || before.st_ino != after.st_ino
                || after.st_mtim.tv_sec != timestamps[1].tv_sec
                || after.st_mtim.tv_nsec != nanos) error = EIO;
        else if (fsync(directory) < 0) error = errno;
    }
    if (close(directory) < 0 && !error) error = errno;
    return error;
}
