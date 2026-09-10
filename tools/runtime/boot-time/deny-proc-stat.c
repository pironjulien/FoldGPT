/* SPDX-License-Identifier: GPL-2.0-or-later */
/* Test fixture: REAL Landlock denial, no replaced file data or LD_PRELOAD. */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>

static void die(const char *what) { perror(what); exit(125); }
static void allow_children(int ruleset, const char *dir, const char *except)
{
    DIR *entries = opendir(dir);
    if (!entries) die("opendir");
    struct dirent *entry;
    while ((entry = readdir(entries))) {
        if (!strcmp(entry->d_name,".") || !strcmp(entry->d_name,"..")
            || !strcmp(entry->d_name,except)) continue;
        int fd = openat(dirfd(entries),entry->d_name,O_PATH|O_CLOEXEC);
        if (fd < 0) {
            if (errno == ENOENT || errno == EACCES) continue;
            die("open rule path");
        }
        struct stat st;
        if (fstat(fd,&st)) die("stat rule path");
        struct landlock_path_beneath_attr rule = {
            .allowed_access = LANDLOCK_ACCESS_FS_READ_FILE |
                              (S_ISDIR(st.st_mode) ? LANDLOCK_ACCESS_FS_READ_DIR : 0),
            .parent_fd = fd
        };
        if (syscall(SYS_landlock_add_rule,ruleset,LANDLOCK_RULE_PATH_BENEATH,&rule,0))
            die("landlock_add_rule");
        close(fd);
    }
    closedir(entries);
}
int main(int argc, char **argv)
{
    if (argc < 2 || getuid() == 0) {
        fputs("test requires nonroot and a command\n",stderr); return 125;
    }
    struct landlock_ruleset_attr attr = {
        .handled_access_fs = LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR
    };
    int ruleset = syscall(SYS_landlock_create_ruleset,&attr,sizeof(attr),0);
    if (ruleset < 0) die("landlock_create_ruleset");
    allow_children(ruleset,"/","proc");
    allow_children(ruleset,"/proc","stat");
    /* Process selection opens the real proc directory itself. Grant only
     * directory enumeration here: READ_FILE stays denied for /proc/stat. */
    int procdir = open("/proc",O_PATH|O_DIRECTORY|O_CLOEXEC);
    if (procdir < 0) die("open proc directory");
    struct landlock_path_beneath_attr listing = {
        .allowed_access = LANDLOCK_ACCESS_FS_READ_DIR,
        .parent_fd = procdir
    };
    if (syscall(SYS_landlock_add_rule,ruleset,LANDLOCK_RULE_PATH_BENEATH,&listing,0))
        die("allow proc listing");
    close(procdir);
    if (prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)) die("no_new_privs");
    if (syscall(SYS_landlock_restrict_self,ruleset,0)) die("landlock_restrict_self");
    close(ruleset);
    int denied = open("/proc/stat",O_RDONLY|O_CLOEXEC);
    if (denied != -1 || errno != EACCES) die("/proc/stat was not denied with EACCES");
    int own = open("/proc/self/stat",O_RDONLY|O_CLOEXEC);
    if (own < 0) die("own process stat inaccessible");
    close(own);
    fprintf(stderr,"test-fixture: real /proc/stat EACCES; /proc/self/stat readable; uid=%u\n",getuid());
    execvp(argv[1],argv+1);
    die("execvp");
}
