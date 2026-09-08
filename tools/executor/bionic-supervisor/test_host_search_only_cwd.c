/* Real Linux qualification fixture: permit directory lookup but refuse reads
 * of /. It never changes host permissions. The exact human supervisor runs
 * inside this additional Landlock domain; all actual worker logic is retained. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

struct search_ruleset { uint64_t handled_access_fs; };
struct search_rule { uint64_t allowed_access; int32_t parent_fd; } __attribute__((packed));
#define READ_DIRECTORY (1ULL << 3)

static int allow_directory(int ruleset,int fd) {
  struct search_rule rule={READ_DIRECTORY,fd};
  return (int)syscall(SYS_landlock_add_rule,ruleset,1,&rule,0);
}

int main(int argc,char **argv) {
  if(argc!=7)return 70;
  char *end;long workspace=strtol(argv[2],&end,10);
  if(!*argv[2]||*end||workspace<3||workspace>INT32_MAX)return 70;
  struct search_ruleset rules={READ_DIRECTORY};
  int fd=(int)syscall(SYS_landlock_create_ruleset,&rules,sizeof(rules),0);
  if(fd<0||allow_directory(fd,(int)workspace)<0)return 70;
  const char *paths[]={"/proc","/usr","/lib","/lib64"};
  for(unsigned i=0;i<sizeof(paths)/sizeof(paths[0]);i++){
    int directory=open(paths[i],O_PATH|O_DIRECTORY|O_CLOEXEC);
    if(directory<0||allow_directory(fd,directory)<0)return 70;
    close(directory);
  }
  if(prctl(PR_SET_NO_NEW_PRIVS,1,0,0,0)<0||
     syscall(SYS_landlock_restrict_self,fd,0)<0)return 70;
  close(fd);
  /* Verify that the test really reproduces Android's missing read authority. */
  int root=open("/",O_RDONLY|O_DIRECTORY|O_CLOEXEC);
  if(root>=0||errno!=EACCES){if(root>=0)close(root);return 70;}
  execv(argv[1],argv+1);
  perror("Actual human supervisor exec");
  return 70;
}
