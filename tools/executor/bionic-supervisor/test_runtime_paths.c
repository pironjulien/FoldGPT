/* Real nonroot resolver tests, compiled with the actual supervisor source.
 * These filesystem/FD checks do not reproduce Samsung SELinux. */
#define main supervisor_main
#include "runner.c"
#undef main
#include <assert.h>
#include <stddef.h>

_Static_assert(SYS_openat2==437,"Python openat2 syscall number");
_Static_assert(AT_FDCWD==-100,"Python openat2 directory constant");
_Static_assert(RESOLVE_NO_MAGICLINKS==0x02,"Python magic-link resolution flag");
_Static_assert(RESOLVE_NO_SYMLINKS==0x04,"Python no-symlink resolution flag");
_Static_assert(sizeof(struct open_how)==24,"Python open_how ABI size");
_Static_assert(offsetof(struct open_how,flags)==0&&offsetof(struct open_how,mode)==8&&
               offsetof(struct open_how,resolve)==16,"Python open_how ABI offsets");

static void join(char out[MAX_PATH],const char *base,const char *name) {
  int n=snprintf(out,MAX_PATH,"%s/%s",base,name);assert(n>0&&n<MAX_PATH);
}
int main(void) {
  assert(getuid()!=0);
  char base[]="/var/tmp/foldgpt-c-runtime-paths-XXXXXX";assert(mkdtemp(base));
  char file[MAX_PATH],alias[MAX_PATH],missing[MAX_PATH],ambiguous[MAX_PATH],resolved[MAX_PATH];
  join(file,base,"file");join(alias,base,"alias");join(missing,base,"missing");join(ambiguous,base,"value (deleted)");
  int fd=open(file,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(fd>=0);assert(write(fd,"real",4)==4);close(fd);
  assert(symlink(file,alias)==0);
  assert(resolve_runtime_object(file,0,resolved)==0&&!strcmp(resolved,file));
  assert(resolve_runtime_object(file,1,resolved)==0&&!strcmp(resolved,file));
  assert(resolve_runtime_object(alias,0,resolved)==0&&!strcmp(resolved,file));
  assert(resolve_runtime_object(alias,1,resolved)==0&&!strcmp(resolved,alias));
  assert(resolve_runtime_object(missing,0,resolved)==-1&&errno==ENOENT);
  assert(resolve_runtime_object(missing,1,resolved)==-1&&errno==ENOENT);
  cfg.grants=1;cfg.runtime[0]=base;
  assert(runtime_object(alias,0,resolved)==1);
  assert(unlink(alias)==0&&symlink("/usr/bin/true",alias)==0);
  assert(runtime_object(alias,0,resolved)==-1&&errno==EACCES);
  assert(runtime_object(alias,1,resolved)==1); /* metadata of the link, not its target */
  assert(unlink(alias)==0&&symlink(missing,alias)==0);
  assert(resolve_runtime_object(alias,0,resolved)==-1&&errno==ENOENT);
  assert(resolve_runtime_object(alias,1,resolved)==0&&!strcmp(resolved,alias));
  fd=open(file,O_PATH|O_CLOEXEC);assert(fd>=0);
  char proc[80];snprintf(proc,sizeof(proc),"/proc/self/fd/%d",fd);
  assert(resolve_runtime_object(proc,0,resolved)==-1&&errno==ELOOP);
  assert(unlink(alias)==0&&symlink(proc,alias)==0);
  assert(resolve_runtime_object(alias,0,resolved)==-1&&errno==ELOOP);
  char moved[MAX_PATH];join(moved,base,"moved");
  assert(rename(file,moved)==0);
  assert(runtime_descriptor_path(fd,0,resolved)==0&&!strcmp(resolved,moved));
  int replacement=open(file,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(replacement>=0);close(replacement);
  assert(runtime_descriptor_path(fd,0,resolved)==0&&!strcmp(resolved,moved));
  assert(unlink(moved)==0);
  assert(runtime_descriptor_path(fd,0,resolved)==-1&&errno==ENOENT);close(fd);
  assert(unlink(file)==0);
  assert(runtime_descriptor_path(fd,0,resolved)==-1&&errno==EBADF);
  fd=open(ambiguous,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(fd>=0);close(fd);
  assert(resolve_runtime_object(ambiguous,0,resolved)==-1&&errno==EINVAL);
  assert(!runtime_name("relative")&&!runtime_name("//usr")&&!runtime_name("/usr/")&&
         !runtime_name("/usr/../usr")&&!runtime_name("/usr/./bin")&&!runtime_name("/a\nb"));
  char restricted[MAX_PATH],nested[MAX_PATH];join(restricted,base,"restricted");join(nested,restricted,"file");
  assert(mkdir(restricted,0700)==0);
  fd=open(nested,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);assert(fd>=0);close(fd);
  assert(chmod(restricted,0)==0);
  assert(resolve_runtime_object(nested,0,resolved)==-1&&errno==EACCES);
  assert(resolve_runtime_object(nested,1,resolved)==-1&&errno==EACCES);
  assert(chmod(restricted,0700)==0&&unlink(nested)==0&&rmdir(restricted)==0);
  assert(unlink(ambiguous)==0&&unlink(alias)==0&&rmdir(base)==0);
  puts("PASS actual C follow/nofollow, containment, missing/dangling, magic links, renamed/deleted/closed FD, ambiguous names, actual search denial; nonroot; Samsung SELinux untested");
  return 0;
}
