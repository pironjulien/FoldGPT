/* Fixed, bounded kernel-mechanism qualification. No command/eval input.
 * Run only through the real supervisor in a dedicated disposable workspace.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <pthread.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <unistd.h>
#ifdef __ANDROID__
#define QUALIFICATION_UID 2000
#else
#define QUALIFICATION_UID 65534
#endif

static int fail(const char *stage,int number) {
    printf("{\"type\":\"kernel-qualification\",\"success\":false,\"stage\":\"%s\",\"errno\":%d}\n",stage,number);
    return 70;
}
#define NEED(condition,stage) do {if(!(condition))return fail(stage,errno);}while(0)
struct entry {uint64_t inode;int64_t offset;unsigned short length;unsigned char type;char name[];};

static int mechanisms(void) {
    /* This open requires the supervisor to read this actual pointer through
     * its pinned /proc/TID/mem FD, then inject a real file descriptor. */
    int file=(int)syscall(SYS_openat,AT_FDCWD,"input",O_RDONLY|O_CLOEXEC,0);
    NEED(file>=0,"memory-path-read-and-addfd");
    NEED(ioctl(file,FIONCLEX)==0,"descriptor-inheritance-clear");
    int flags=fcntl(file,F_GETFD);
    NEED(flags>=0&&!(flags&FD_CLOEXEC),"descriptor-inheritance-cleared-value");
    NEED(ioctl(file,FIOCLEX)==0,"descriptor-inheritance-set");
    flags=fcntl(file,F_GETFD);
    NEED(flags>=0&&(flags&FD_CLOEXEC),"descriptor-inheritance-set-value");
    /* A raw syscall retains bits that libc ioctl may truncate on Android. */
    errno=0;
    NEED(syscall(SYS_ioctl,file,(UINT64_C(1)<<32)|FIOCLEX,0)==-1&&errno==EPERM,
         "descriptor-inheritance-high-bits-set-refused");
    errno=0;
    NEED(syscall(SYS_ioctl,file,(UINT64_C(1)<<32)|FIONCLEX,0)==-1&&errno==EPERM,
         "descriptor-inheritance-high-bits-clear-refused");
    int available=0;errno=0;
    NEED(ioctl(0,FIONREAD,&available)==-1&&errno==EPERM,"unrelated-ioctl-refused");
    char input[32]={0};ssize_t bytes=read(file,input,sizeof(input));int closed=close(file);
    NEED(bytes==14&&!memcmp(input,"pin-memory-ok\n",14)&&closed==0,"real-file-content");
    /* newfstatat is USER_NOTIF, unlike plain fstat: this stat result must be
     * written into this process by the supervisor through pinned memory. */
    struct stat metadata;memset(&metadata,0xa5,sizeof(metadata));
    NEED(syscall(SYS_newfstatat,AT_FDCWD,"input",&metadata,AT_SYMLINK_NOFOLLOW)==0,"memory-metadata-write");
    NEED(S_ISREG(metadata.st_mode)&&metadata.st_size==14&&metadata.st_uid==getuid(),"real-metadata-value");
    int directory=(int)syscall(SYS_openat,AT_FDCWD,"directory",O_RDONLY|O_DIRECTORY|O_CLOEXEC,0);
    NEED(directory>=0,"open-directory");
    unsigned markers=0,calls=0,total=0;int shared_offset=0;
    for(;;){
        _Alignas(struct entry) unsigned char buffer[256];
        ssize_t count=syscall(SYS_getdents64,directory,buffer,sizeof(buffer));
        NEED(count>=0,"pidfd-getfd-directory-read");
        if(!count)break;
        NEED(++calls<=16,"bounded-directory-stream");
        size_t cursor=0;int64_t last=0;
        while(cursor<(size_t)count){
            struct entry *entry=(struct entry*)(void*)(buffer+cursor);
            NEED((size_t)count-cursor>=offsetof(struct entry,name)+1&&entry->length>=offsetof(struct entry,name)+1&&
                 entry->length<=(size_t)count-cursor&&memchr(entry->name,0,entry->length - offsetof(struct entry,name)),"directory-record");
            if(!strcmp(entry->name,"marker"))markers++;
            else NEED(!strcmp(entry->name,".")||!strcmp(entry->name,".."),"unexpected-directory-entry");
            cursor+=entry->length;last=entry->offset;total++;
        }
        /* A /proc/fd reopen creates a fresh offset and fails this check.
         * pidfd_getfd must duplicate the actual open file description. */
        off_t observed=lseek(directory,0,SEEK_CUR);
        NEED(observed>=0&&observed==last&&observed!=0,"shared-directory-offset");
        shared_offset=1;
    }
    NEED(close(directory)==0&&markers==1&&total==3&&shared_offset,"complete-directory-stream");
    errno=0;file=open("private/secret",O_RDONLY|O_CLOEXEC);
    if(file>=0){close(file);return fail("private-read-was-admitted",0);}
    NEED(errno==EACCES||errno==EPERM,"private-read-denial-errno");
    errno=0;file=open(".git/config",O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC,0600);
    if(file>=0){close(file);return fail("protected-write-was-admitted",0);}
    NEED(errno==EACCES||errno==EPERM,"protected-write-denial-errno");
    errno=0;NEED(syscall(SYS_chdir,".")==-1&&errno==EPERM,"raw-chdir-denial");
    errno=0;int endpoint=socket(AF_INET,SOCK_STREAM,0);
    if(endpoint>=0){close(endpoint);return fail("network-was-admitted",0);}
    NEED(errno==EPERM||errno==EACCES,"network-denial-errno");
    errno=0;NEED(ioctl(0,0,0)==-1&&errno==EPERM,"ioctl-denial");
    errno=0;file=open("/dev/binder",O_RDONLY|O_CLOEXEC);
    if(file>=0){close(file);return fail("binder-was-admitted",0);}
    NEED(errno==EPERM||errno==EACCES,"binder-denial-errno");
    return 0;
}
static void *thread_mechanisms(void *ignored) {
    (void)ignored;return (void *)(intptr_t)mechanisms();
}
int main(int argc,char **argv) {
    (void)argv;
    uid_t real,effective,saved;gid_t greal,geffective,gsaved;
    if(argc!=1||getresuid(&real,&effective,&saved)<0||getresgid(&greal,&geffective,&gsaved)<0||
       real!=QUALIFICATION_UID||real!=effective||real!=saved||
       greal!=QUALIFICATION_UID||greal!=geffective||greal!=gsaved||
       prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)!=1||prctl(PR_GET_SECCOMP,0,0,0,0)!=2)
        return fail("required-enforcement",EPERM);
    int result=mechanisms();if(result)return result;
    /* The host's default pthread stack can consume the complete data limit
     * (GitHub: 16MiB each). Reserve half of the actual allowance for this one
     * secondary thread and retain the other half for the main worker/heap. */
    struct rlimit data_limit;
    NEED(getrlimit(RLIMIT_DATA,&data_limit)==0&&data_limit.rlim_cur!=RLIM_INFINITY,"thread-data-budget");
    size_t stack_bytes=(size_t)(data_limit.rlim_cur/2);
    NEED(stack_bytes>=(size_t)PTHREAD_STACK_MIN,"thread-stack-budget");
    pthread_attr_t attributes;int configured=pthread_attr_init(&attributes);
    if(configured)return fail("thread-attributes",configured);
    configured=pthread_attr_setstacksize(&attributes,stack_bytes);
    if(configured){pthread_attr_destroy(&attributes);return fail("thread-stack-attributes",configured);}
    pthread_t thread;int created=pthread_create(&thread,&attributes,thread_mechanisms,NULL);
    pthread_attr_destroy(&attributes);
    if(created)return fail("create-real-secondary-thread",created);
    void *thread_result=NULL;int joined=pthread_join(thread,&thread_result);
    if(joined)return fail("join-real-secondary-thread",joined);
    if(thread_result)return (int)(intptr_t)thread_result;
    puts("{\"type\":\"kernel-qualification\",\"success\":true,\"memoryRead\":true,\"memoryWrite\":true,\"pidfdGetfd\":true,\"sharedOffset\":true,\"privateReadDenied\":true,\"protectedWriteDenied\":true,\"rawChdirDenied\":true,\"networkDenied\":true,\"ioctlDenied\":true,\"binderDenied\":true,\"threadMemory\":true,\"threadPidfdGetfd\":true}");
    return 0;
}
