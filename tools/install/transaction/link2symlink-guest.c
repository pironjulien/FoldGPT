#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/ipc.h>
#include <sys/shm.h>
#include <sys/wait.h>
#include <unistd.h>

#define REQUIRE(x) do { if (!(x)) { fprintf(stderr,"FAIL line=%d errno=%d\n",__LINE__,errno); return 1; } } while(0)

static int inspect_pair(const char *left, const char *right) {
    struct stat a,b;
    struct statx ax,bx;
    REQUIRE(lstat(left,&a)==0 && lstat(right,&b)==0);
    REQUIRE(S_ISREG(a.st_mode) && S_ISREG(b.st_mode));
    REQUIRE(a.st_dev==b.st_dev && a.st_ino==b.st_ino && a.st_nlink==2 && b.st_nlink==2);
    REQUIRE(statx(AT_FDCWD,left,AT_SYMLINK_NOFOLLOW,STATX_BASIC_STATS,&ax)==0);
    REQUIRE(statx(AT_FDCWD,right,AT_SYMLINK_NOFOLLOW,STATX_BASIC_STATS,&bx)==0);
    REQUIRE(ax.stx_ino==bx.stx_ino && ax.stx_nlink==2 && bx.stx_nlink==2);
    int l=open(left,O_RDONLY), r=open(right,O_RDONLY); REQUIRE(l>=0 && r>=0);
    char first[4096],second[4096]; ssize_t n;
    while ((n=read(l,first,sizeof(first)))>0)
        REQUIRE(read(r,second,(size_t)n)==n && !memcmp(first,second,(size_t)n));
    REQUIRE(n==0 && read(r,second,1)==0);
    REQUIRE(close(l)==0 && close(r)==0);
    printf("PASS read-only archive pair %s %s inode=%llu links=2 bytes=%llu\n",left,right,
        (unsigned long long)a.st_ino,(unsigned long long)a.st_size);
    return 0;
}

static int shared_memory(void) {
    /* Real glibc SysV calls exercise PRoot's native shared-memory backend.
     * Synchronization is through waitpid, not an unbounded polling loop. */
    const size_t bytes = 16384;
    int id = shmget(IPC_PRIVATE, bytes, IPC_CREAT | 0600);
    REQUIRE(id >= 0);
    char *memory = shmat(id, NULL, 0);
    REQUIRE(memory != (void *)-1);
    memcpy(memory, "parent", 7);
    pid_t child = fork();
    REQUIRE(child >= 0);
    if (!child) {
        if (memcmp(memory, "parent", 7)) _exit(2);
        /* Attach again: inherited memory alone would only test fork/mmap. */
        char *attached = shmat(id, NULL, 0);
        if (attached == (void *)-1) _exit(3);
        if (memcmp(attached, "parent", 7)) _exit(4);
        memcpy(attached + bytes - 6, "child", 6);
        if (shmdt(attached) || shmdt(memory)) _exit(5);
        _exit(0);
    }
    int status;
    REQUIRE(waitpid(child, &status, 0) == child && WIFEXITED(status) && WEXITSTATUS(status) == 0);
    REQUIRE(!memcmp(memory + bytes - 6, "child", 6));
    REQUIRE(shmdt(memory) == 0 && shmctl(id, IPC_RMID, NULL) == 0);
    errno = 0;
    REQUIRE(shmat(id, NULL, 0) == (void *)-1);
    REQUIRE(errno == EINVAL || errno == EIDRM);
    puts("PASS SysV IPC: private segment, fork, second attach, shared bytes, detach, remove and stale id rejected");
    return 0;
}

/* Static host or ARM64 guest fixture; no model calls, account or networking. */
int main(int argc, char **argv) {
    struct stat a,b;
    const char *left="/data/a", *right="/data/b", *survivor="/data/c";
    REQUIRE(argc==2);
    if (!strcmp(argv[1],"shared-memory")) return shared_memory();
    if (!strcmp(argv[1],"inspect-archive")) {
        REQUIRE(inspect_pair("/usr/bin/perl","/usr/bin/perl5.40.1")==0);
        REQUIRE(inspect_pair("/usr/bin/perlbug","/usr/bin/perlthanks")==0);
        return 0;
    }
    REQUIRE(!strcmp(argv[1],"create") || !strcmp(argv[1],"verify"));
    if (!strcmp(argv[1],"create")) {
        int fd=open(left,O_WRONLY|O_CREAT|O_EXCL,0644); REQUIRE(fd>=0);
        REQUIRE(write(fd,"one\n",4)==4); REQUIRE(close(fd)==0);
        REQUIRE(link(left,right)==0);
    }
    REQUIRE(lstat(left,&a)==0 && lstat(right,&b)==0);
    REQUIRE(S_ISREG(a.st_mode) && S_ISREG(b.st_mode));
    REQUIRE(a.st_dev==b.st_dev && a.st_ino==b.st_ino && a.st_nlink==2 && b.st_nlink==2);
    struct statx ax,bx;
    REQUIRE(statx(AT_FDCWD,left,AT_SYMLINK_NOFOLLOW,STATX_BASIC_STATS,&ax)==0);
    REQUIRE(statx(AT_FDCWD,right,AT_SYMLINK_NOFOLLOW,STATX_BASIC_STATS,&bx)==0);
    REQUIRE(ax.stx_ino==bx.stx_ino && ax.stx_nlink==2 && bx.stx_nlink==2);
    int fd=open(right,O_WRONLY|O_APPEND); REQUIRE(fd>=0);
    REQUIRE(write(fd,"two\n",4)==4); REQUIRE(fsync(fd)==0); REQUIRE(close(fd)==0);
    char bytes[8];fd=open(left,O_RDONLY);REQUIRE(fd>=0);
    REQUIRE(read(fd,bytes,8)==8 && !memcmp(bytes,"one\ntwo\n",8)); REQUIRE(close(fd)==0);
    REQUIRE(chmod(right,0640)==0 && stat(left,&a)==0 && (a.st_mode&07777)==0640);
    struct timespec times[2]={{1,0},{3,123456789}};
    REQUIRE(utimensat(AT_FDCWD,right,times,0)==0 && stat(left,&a)==0);
    REQUIRE(a.st_mtim.tv_sec==3 && a.st_mtim.tv_nsec==123456789);
    REQUIRE(rename(left,survivor)==0);
    REQUIRE(unlink(right)==0 && lstat(survivor,&a)==0 && a.st_nlink==1);
    REQUIRE(unlink(survivor)==0);
    puts("PASS actual guest root: lstat/statx identity and count, shared write/chmod/mtime, rename, unlink survivor and last");
    return 0;
}
