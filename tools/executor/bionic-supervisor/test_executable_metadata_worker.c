/* Actual syscall regression for the executable alias, under the real broker.
 * The host observer independently checks procfs while this worker stays alive. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <linux/stat.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/sysmacros.h>
#include <unistd.h>

#define NEED(value) do { if(!(value)){fprintf(stderr,"metadata regression line %d errno %d\n",__LINE__,errno);return 1;} } while(0)
static const char *executable;
static struct stat observed_link,observed_target;
static int same(const struct stat *a,const struct stat *b) {
  return a->st_dev==b->st_dev&&a->st_ino==b->st_ino&&a->st_mode==b->st_mode&&
    a->st_uid==b->st_uid&&a->st_gid==b->st_gid&&a->st_size==b->st_size;
}
static int same_statx(const struct stat *a,const struct statx *b) {
  return major(a->st_dev)==b->stx_dev_major&&minor(a->st_dev)==b->stx_dev_minor&&
    a->st_ino==b->stx_ino&&a->st_mode==b->stx_mode&&a->st_uid==b->stx_uid&&
    a->st_gid==b->stx_gid&&(uint64_t)a->st_size==b->stx_size;
}
static int checks(int retain) {
  const char *alias="/proc/self/exe";
  struct stat actual,follow,link;struct statx extended;
  NEED(stat(executable,&actual)==0&&S_ISREG(actual.st_mode));
  NEED(stat(alias,&follow)==0&&same(&actual,&follow));
  NEED(syscall(SYS_newfstatat,AT_FDCWD,alias,&follow,0)==0&&same(&actual,&follow));
  NEED(syscall(SYS_newfstatat,27,alias,&follow,AT_NO_AUTOMOUNT)==0&&same(&actual,&follow));
  NEED(lstat(alias,&link)==0&&S_ISLNK(link.st_mode));
  if(!retain)NEED(same(&link,&observed_link)); /* /proc/self is TGID, not TID. */
  NEED(syscall(SYS_newfstatat,AT_FDCWD,alias,&follow,AT_SYMLINK_NOFOLLOW)==0&&same(&link,&follow));
#ifdef SYS_stat
  NEED(syscall(SYS_stat,alias,&follow)==0&&same(&actual,&follow));
  NEED(syscall(SYS_lstat,alias,&follow)==0&&same(&link,&follow));
#endif
  NEED(syscall(SYS_statx,AT_FDCWD,alias,0,STATX_BASIC_STATS,&extended)==0&&same_statx(&actual,&extended));
  NEED(syscall(SYS_statx,AT_FDCWD,alias,AT_SYMLINK_NOFOLLOW,STATX_BASIC_STATS,&extended)==0&&same_statx(&link,&extended));
  NEED(syscall(SYS_newfstatat,AT_FDCWD,alias,&follow,0x40000000)==-1&&errno==EINVAL);
  NEED(syscall(SYS_statx,AT_FDCWD,alias,0x40000000,STATX_BASIC_STATS,&extended)==-1&&errno==EINVAL);
  NEED(syscall(SYS_newfstatat,AT_FDCWD,alias,(void *)(uintptr_t)1,0)==-1&&errno==EFAULT);
  NEED(syscall(SYS_statx,AT_FDCWD,alias,0,STATX_BASIC_STATS,(void *)(uintptr_t)1)==-1&&errno==EFAULT);
  const char *denied[]={"/proc","/proc/self","/proc/self/status","/proc/self/fd/1",
    "/proc/self/exe/..","/proc/self/exe.suffix","/proc/self/./exe","/proc/thread-self/exe"};
  for(size_t i=0;i<sizeof(denied)/sizeof(denied[0]);i++){
    NEED(stat(denied[i],&follow)==-1&&errno==EACCES);
    NEED(lstat(denied[i],&follow)==-1&&errno==EACCES);
  }
  char numeric[80];snprintf(numeric,sizeof(numeric),"/proc/%ld/exe",(long)getpid());
  NEED(stat(numeric,&follow)==-1&&errno==EACCES);
  snprintf(numeric,sizeof(numeric),"/proc/%ld/exe",(long)getppid());
  NEED(stat(numeric,&follow)==-1&&errno==EACCES);
  NEED(open(alias,O_RDONLY|O_CLOEXEC)==-1&&errno==EACCES);
  NEED(open(alias,O_WRONLY|O_CLOEXEC)==-1&&errno==EACCES);
  char name[4096];ssize_t length=readlink(alias,name,sizeof(name)-1);
  NEED(length>0&&(size_t)length<sizeof(name)-1);name[length]=0;NEED(!strcmp(name,executable));
  if(retain){observed_link=link;observed_target=actual;}
  return 0;
}
static void *thread_checks(void *unused) {(void)unused;return (void *)(intptr_t)checks(0);}
int main(int argc,char **argv) {
  NEED(getuid()!=0&&argc==2&&!strcmp(argv[0],"logical-executable"));
  executable=argv[1];NEED(checks(1)==0);
  pthread_t thread;NEED(pthread_create(&thread,NULL,thread_checks,NULL)==0);
  void *result=NULL;NEED(pthread_join(thread,&result)==0&&result==NULL);
  printf("{\"pid\":%ld,\"linkDevice\":%llu,\"linkInode\":%llu,\"linkMode\":%u,\"linkSize\":%lld,"
    "\"targetDevice\":%llu,\"targetInode\":%llu,\"mainAndThread\":true}\n",(long)getpid(),
    (unsigned long long)observed_link.st_dev,(unsigned long long)observed_link.st_ino,
    (unsigned)observed_link.st_mode,(long long)observed_link.st_size,
    (unsigned long long)observed_target.st_dev,(unsigned long long)observed_target.st_ino);
  NEED(fflush(stdout)==0);char release;NEED(read(STDIN_FILENO,&release,1)==1&&release=='R');
  return 0;
}
