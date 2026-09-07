#define _GNU_SOURCE
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <dlfcn.h>
#include <sys/wait.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <errno.h>
extern char **environ;
extern int review_primary(void);
#ifndef REVIEW_PLUGIN
#error missing actual plugin filename
#endif
int main(int argc,char**argv){
 if(environ[0])return 80;
 void *p=dlopen(REVIEW_PLUGIN,RTLD_NOW|RTLD_LOCAL);if(!p){fprintf(stderr,"%s\n",dlerror());return 81;}
 int(*value)(void)=(int(*)(void))dlsym(p,"review_plugin");if(!value||value()!=42||review_primary()!=42)return 82;
 if(argc>1){puts("child empty-environment dynamic+transitive+dlopen=42");return 0;}
 char executable[4096];ssize_t n=readlink("/proc/self/exe",executable,sizeof(executable)-1);if(n<0)return 83;executable[n]=0;
 pid_t pid=fork();if(pid<0)return 84;if(!pid){char *args[]={executable,"child",NULL};char *env[]={NULL};execve(executable,args,env);_exit(85);}
 int status;if(waitpid(pid,&status,0)!=pid||!WIFEXITED(status)||WEXITSTATUS(status))return 86;
 puts("parent empty-environment dynamic+transitive+dlopen=42");return 0;
}
