/* Fixed, debug-only integration fixture for the production native file helper. */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

static void require(int ok,const char *stage) { if(!ok) { perror(stage); exit(1); } }
static int invoke_full(const char *helper,int root,const char *operation,const char *path,
                  const char *input,const char *declared,const char *expected,
                  const char *device,const char *inode,char *observed,size_t capacity) {
    int in[2],out[2]; require(pipe(in)==0 && pipe(out)==0,"pipes");
    pid_t child=fork(); require(child>=0,"fork");
    if(!child) {
        require(dup2(in[0],0)==0 && dup2(out[1],1)==1,"stdio");
        close(in[0]); close(in[1]); close(out[0]); close(out[1]);
        char descriptor[32]; snprintf(descriptor,sizeof(descriptor),"%d",root);
        if(device && inode) execl(helper,helper,operation,descriptor,path,declared,device,inode,(char *)NULL);
        else execl(helper,helper,operation,descriptor,path,declared,(char *)NULL);
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
    if(observed) {
        require(length<capacity,"bounded observed result");
        memcpy(observed,bytes,length); observed[length]=0;
    } else if(expected) require(length==strlen(expected) && !memcmp(bytes,expected,length),"actual native bytes");
    else require(length==0,"no unsuccessful data output");
    return WIFEXITED(status)?WEXITSTATUS(status):128;
}
static int invoke(const char *helper,int root,const char *operation,const char *path,
                  const char *input,const char *declared,const char *expected) {
    return invoke_full(helper,root,operation,path,input,declared,expected,NULL,NULL,NULL,0);
}
static int make_directory(const char *helper,int root,const char *operation,const char *path,
                          unsigned missing,const struct stat *parent,int wrong_parent) {
    char count[32],device[32],inode[32];
    snprintf(count,sizeof(count),"%u",missing);
    snprintf(device,sizeof(device),"%" PRIu64,(uint64_t)parent->st_dev);
    snprintf(inode,sizeof(inode),"%" PRIu64,(uint64_t)parent->st_ino+(wrong_parent?1:0));
    return invoke_full(helper,root,operation,path,NULL,count,NULL,device,inode,NULL,0);
}
static void check_metadata(const char *helper,int root,const char *operation,const char *path) {
    struct stat independent;
    require(fstatat(root,path,&independent,AT_SYMLINK_NOFOLLOW)==0,"independent metadata");
    char output[512],directory[6],file[6]; uint64_t size; int64_t created,modified; int consumed=0;
    require(invoke_full(helper,root,operation,path,NULL,"0",NULL,NULL,NULL,output,sizeof(output))==0,"native statx metadata");
    int fields=sscanf(output,"{\"isDirectory\":%5[a-z],\"isFile\":%5[a-z],\"isSymlink\":false,\"size\":%" SCNu64
        ",\"createdAtMs\":%" SCNd64 ",\"modifiedAtMs\":%" SCNd64 "}\n%n",
        directory,file,&size,&created,&modified,&consumed);
    require(fields==5 && consumed==(int)strlen(output),"complete metadata record");
    require(!strcmp(directory,S_ISDIR(independent.st_mode)?"true":"false") &&
        !strcmp(file,S_ISREG(independent.st_mode)?"true":"false"),"actual metadata kinds");
    require(size==(uint64_t)independent.st_size && modified==
        (int64_t)independent.st_mtim.tv_sec*1000+independent.st_mtim.tv_nsec/1000000,"actual metadata size/time");
    require(created>=0 && created<=modified,"new fixture birth time");
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
    check_metadata(helper,root,"metadata","value");
    check_metadata(helper,root,"metadata-nofollow","value");
    check_metadata(helper,root,"metadata",".");
    require(invoke(helper,root,"canonicalize","value",NULL,"0",NULL)==0,"existing canonical file");
    require(invoke(helper,root,"canonicalize",".",NULL,"0",NULL)==0,"existing canonical root");
    require(invoke(helper,root,"canonicalize","missing",NULL,"0",NULL)!=0,"missing canonical file refused");
    require(invoke(helper,root,"metadata","missing",NULL,"0",NULL)!=0,"missing metadata refused");
    require(invoke(helper,root,"metadata","alias",NULL,"0",NULL)!=0,"metadata alias refused");
    require(invoke(helper,root,"canonicalize","alias",NULL,"0",NULL)!=0,"canonical alias refused");
    struct stat parent,child; require(fstat(root,&parent)==0,"directory plan root");
    require(make_directory(helper,root,"mkdirs","nested/child",2,&parent,0)==0,"recursive native directory");
    require(fstatat(root,"nested/child",&child,AT_SYMLINK_NOFOLLOW)==0 && S_ISDIR(child.st_mode) &&
        (child.st_mode&0777)==0700,"actual private directory");
    check_metadata(helper,root,"metadata","nested/child");
    require(invoke(helper,root,"canonicalize","nested/child",NULL,"0",NULL)==0,"canonical directory");
    require(make_directory(helper,root,"mkdir","single",1,&parent,0)==0,"single native directory");
    require(fstatat(root,"single",&child,AT_SYMLINK_NOFOLLOW)==0 && S_ISDIR(child.st_mode) &&
        (child.st_mode&0777)==0700,"actual single private directory");
    require(make_directory(helper,root,"mkdir","absent/child",2,&parent,0)!=0,"nonrecursive ancestors refused");
    require(fstatat(root,"absent",&child,AT_SYMLINK_NOFOLLOW)<0 && errno==ENOENT,"no refused partial ancestor");
    require(make_directory(helper,root,"mkdirs","stale/child",2,&parent,1)!=0,"stale directory identity refused");
    require(fstatat(root,"stale",&child,AT_SYMLINK_NOFOLLOW)<0 && errno==ENOENT,"stale plan preserved absence");
    printf("PASS native read/write/overwrite, same inode, symlink and escape refusal, incomplete write refusal\nevidence=%s\n",work);
    printf("PASS native metadata/canonicalize and recursive/nonrecursive directories; real kinds, size, time, mode and denied-plan preservation\n");
    close(root); return 0;
}
