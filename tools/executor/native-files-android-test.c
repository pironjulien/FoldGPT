/* Fixed, debug-only integration fixture for the production native file helper. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static void require(int ok,const char *stage) { if(!ok) { perror(stage); exit(1); } }
static int invoke(const char *helper,int root,const char *operation,const char *path,
                  const char *input,const char *declared,const char *expected) {
    int in[2],out[2]; require(pipe(in)==0 && pipe(out)==0,"pipes");
    pid_t child=fork(); require(child>=0,"fork");
    if(!child) {
        require(dup2(in[0],0)==0 && dup2(out[1],1)==1,"stdio");
        close(in[0]); close(in[1]); close(out[0]); close(out[1]);
        char descriptor[32]; snprintf(descriptor,sizeof(descriptor),"%d",root);
        execl(helper,helper,operation,descriptor,path,declared,(char *)NULL);
        _exit(127);
    }
    close(in[0]); close(out[1]);
    if(input) require(write(in[1],input,strlen(input))==(ssize_t)strlen(input),"input");
    close(in[1]);
    char bytes[1024]; size_t length=0;
    for(;;) {
        ssize_t n=read(out[0],bytes+length,sizeof(bytes)-length);
        if(n<0 && errno==EINTR) continue;
        require(n>=0,"output"); if(!n) break; length+=(size_t)n;
        require(length<sizeof(bytes),"bounded output");
    }
    close(out[0]); int status; require(waitpid(child,&status,0)==child,"wait");
    if(expected) require(length==strlen(expected) && !memcmp(bytes,expected,length),"actual native bytes");
    else require(length==0,"no unsuccessful data output");
    return WIFEXITED(status)?WEXITSTATUS(status):128;
}
int main(int argc,char **argv) {
    require(argc==3,"fixed fixture arguments");
    printf("uid=%u seccomp=%d\n",getuid(),prctl(PR_GET_SECCOMP,0,0,0,0));
    char work[PATH_MAX],helper[PATH_MAX];
    require(snprintf(work,sizeof(work),"%s/foldgpt-native-files-XXXXXX",argv[1])<(int)sizeof(work),"work path");
    require(snprintf(helper,sizeof(helper),"%s/libfoldgpt-native-files.so",argv[2])<(int)sizeof(helper),"helper path");
    require(mkdtemp(work)!=NULL,"new private workspace");
    int root=open(work,O_RDONLY|O_DIRECTORY|O_NOFOLLOW); require(root>=3,"workspace fd");
    require(invoke(helper,root,"write","value","native-file-rpc","15",NULL)==0,"native file create");
    require(invoke(helper,root,"read","value",NULL,"0","native-file-rpc")==0,"native file read");
    struct stat before,after; require(fstatat(root,"value",&before,AT_SYMLINK_NOFOLLOW)==0,"original inode");
    require(invoke(helper,root,"write","value","second","6",NULL)==0,"native file overwrite");
    require(fstatat(root,"value",&after,AT_SYMLINK_NOFOLLOW)==0 && before.st_ino==after.st_ino,"same inode");
    require(symlinkat("value",root,"alias")==0,"symlink fixture");
    require(invoke(helper,root,"write","alias","BAD","3",NULL)!=0,"symlink refused");
    require(invoke(helper,root,"write","../outside","BAD","3",NULL)!=0,"escape refused");
    require(invoke(helper,root,"write","value","short","100",NULL)!=0,"truncated write refused");
    require(invoke(helper,root,"read","value",NULL,"0","second")==0,"denials preserved actual file");
    printf("PASS native read/write/overwrite, same inode, symlink and escape refusal, incomplete write refusal\nevidence=%s\n",work);
    close(root); return 0;
}
