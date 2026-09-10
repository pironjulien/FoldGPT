/* SPDX-License-Identifier: GPL-3.0-only
 * Native path/FD half of the trusted executor's file RPC backend.
 * The caller must authorize the request against its immutable policy first.
 * This helper never runs guest code. See native-files.md for admission limits.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <limits.h>
#include <linux/openat2.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <unistd.h>

#define MAX_DATA (16U * 1024U * 1024U)
#define MAX_DEPTH 64U
#define MAX_ENTRIES 100000U

struct node { char *path; uint64_t device,inode,mode,size; int64_t mtime,ctime; uint64_t mns,cns; };
struct plan { struct node *nodes; size_t count; char *data; };

static int error(const char *stage) {
    fprintf(stderr,"{\"stage\":\"%s\",\"errno\":%d}\n",stage,errno);
    return 1;
}
static int valid_relative(const char *path) {
    if (!path[0] || path[0]=='/' || strlen(path)>=PATH_MAX) return 0;
    const char *p=path;
    for (;;) {
        const char *end=strchr(p,'/'); size_t n=end?(size_t)(end-p):strlen(p);
        if (!n || (n==1 && p[0]=='.') || (n==2 && p[0]=='.' && p[1]=='.')) return 0;
        if (!end) return 1;
        p=end+1;
    }
}
static int open_beneath(int root,const char *path,int flags,int mode) {
    struct open_how how={.flags=(uint64_t)flags,.mode=(uint64_t)mode,
        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    return (int)syscall(SYS_openat2,root,path,&how,sizeof(how));
}
static int ordinary(int fd) {
    struct stat st;
    if (fstat(fd,&st)<0) return 0;
    if (!S_ISREG(st.st_mode) || st.st_uid!=getuid() || st.st_nlink!=1) { errno=EPERM; return 0; }
    return 1;
}
static int pinned_open(int root,const char *path,int writing) {
    int pin=open_beneath(root,path,O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
    if (pin<0) {
        if (!writing || errno!=ENOENT) return -1;
        // Never open a racing replacement: this branch exclusively creates a
        // new ordinary file. EEXIST stays an error, not a retry with truncation.
        return open_beneath(root,path,O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    }
    if (!ordinary(pin)) { int saved=errno; close(pin); errno=saved; return -1; }
    // Reopen the pinned inode, not a second lookup of an attacker-changeable
    // pathname. /proc/self/fd is internal control data, never a request path.
    char proc[64]; snprintf(proc,sizeof(proc),"/proc/self/fd/%d",pin);
    int fd=open(proc,(writing?O_WRONLY:O_RDONLY)|O_CLOEXEC|O_NONBLOCK);
    int saved=errno;
    struct stat before,after;
    if (fd>=0 && (fstat(pin,&before)<0 || fstat(fd,&after)<0 ||
            before.st_dev!=after.st_dev || before.st_ino!=after.st_ino || !ordinary(fd))) {
        saved=errno?errno:ESTALE; close(fd); fd=-1;
    }
    close(pin); errno=saved; return fd;
}
static int write_all(int fd,const void *buffer,size_t length) {
    const unsigned char *p=buffer;
    while(length) {
        ssize_t n=write(fd,p,length);
        if(n<0 && errno==EINTR) continue;
        if(n<=0) { if(!n) errno=EIO; return -1; }
        p+=n; length-=(size_t)n;
    }
    return 0;
}
static int decimal(const char *text,uint64_t *value) {
    if(!text[0]) return 0;
    for(const char *p=text;*p;p++) if(*p<'0' || *p>'9') return 0;
    char *end; errno=0;
    unsigned long long number=strtoull(text,&end,10);
    if(errno || *end) return 0;
    *value=(uint64_t)number;
    return 1;
}
static int empty_input(void) {
    unsigned char unexpected;
    ssize_t received;
    do { received=read(STDIN_FILENO,&unexpected,1); } while(received<0 && errno==EINTR);
    if(received<0) return error("input");
    if(received) { errno=EMSGSIZE; return error("input-length"); }
    return 0;
}
static int64_t timestamp_ms(int64_t seconds,uint32_t nanoseconds,int nofollow) {
    /* Match the two reviewed upstream conversions: default/follow metadata
     * maps pre-epoch or unrepresentable times to zero; Linux no-follow
     * metadata uses signed, saturating millisecond arithmetic.
     */
    int64_t milliseconds;
    if(!nofollow && seconds<0) return 0;
    if(seconds>INT64_MAX/1000) {
        if(!nofollow) return 0;
        milliseconds=INT64_MAX;
    } else if(seconds<INT64_MIN/1000) milliseconds=INT64_MIN;
    else milliseconds=seconds*1000;
    int64_t fraction=nanoseconds/1000000;
    if(milliseconds>INT64_MAX-fraction) return nofollow?INT64_MAX:0;
    return milliseconds+fraction;
}
static int inspect_path(int root,const char *operation,const char *path) {
    /* O_PATH never activates a special file. The native lookup, type, owner
     * and link checks are required even after trusted workspace admission.
     * Canonicalization returns success only after this real object lookup;
     * the caller maps its already canonical components back to a guest URI.
     */
    int pin=open_beneath(root,path,O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
    if(pin<0) return error("open");
    struct stat st;
    if(fstat(pin,&st)<0) return error("metadata");
    if(st.st_uid!=getuid() || (!S_ISDIR(st.st_mode) && !S_ISREG(st.st_mode)) ||
            (S_ISREG(st.st_mode) && st.st_nlink!=1)) {
        errno=EPERM; return error("file-kind");
    }
    if(strcmp(operation,"canonicalize")) {
        struct statx sx;
        unsigned required=STATX_TYPE|STATX_MODE|STATX_NLINK|STATX_UID|STATX_INO|STATX_SIZE|STATX_MTIME;
        if(syscall(SYS_statx,pin,"",AT_EMPTY_PATH|AT_SYMLINK_NOFOLLOW,
                required|STATX_BTIME,&sx)<0) return error("metadata");
        if((sx.stx_mask&required)!=required || sx.stx_ino!=(uint64_t)st.st_ino ||
                sx.stx_uid!=getuid() || (sx.stx_mode&S_IFMT)!=(st.st_mode&S_IFMT) ||
                (S_ISREG(st.st_mode) && sx.stx_nlink!=1) ||
                sx.stx_mtime.tv_nsec>=1000000000U ||
                ((sx.stx_mask&STATX_BTIME) && sx.stx_btime.tv_nsec>=1000000000U)) {
            errno=ESTALE; return error("metadata");
        }
        int nofollow=!strcmp(operation,"metadata-nofollow");
        int64_t created=(sx.stx_mask&STATX_BTIME)?timestamp_ms(sx.stx_btime.tv_sec,sx.stx_btime.tv_nsec,nofollow):0;
        int64_t modified=timestamp_ms(sx.stx_mtime.tv_sec,sx.stx_mtime.tv_nsec,nofollow);
        char result[256];
        int length=snprintf(result,sizeof(result),
            "{\"isDirectory\":%s,\"isFile\":%s,\"isSymlink\":false,\"size\":%" PRIu64
            ",\"createdAtMs\":%" PRId64 ",\"modifiedAtMs\":%" PRId64 "}\n",
            S_ISDIR(st.st_mode)?"true":"false",S_ISREG(st.st_mode)?"true":"false",
            (uint64_t)sx.stx_size,created,modified);
        if(length<0 || (size_t)length>=sizeof(result)) { errno=EOVERFLOW; return error("metadata"); }
        if(write_all(STDOUT_FILENO,result,(size_t)length)<0) return error("output");
    }
    if(close(pin)<0) return error("close");
    return 0;
}
static char *field(char **cursor,char *end) {
    if(*cursor>=end) return NULL;
    char *value=*cursor,*zero=memchr(value,0,(size_t)(end-value));
    if(!zero) return NULL;
    *cursor=zero+1; return value;
}
static int signed_decimal(const char *text,int64_t *number) {
    if(!text || !text[0]) return 0;
    const char *digits=text[0]=='-'?text+1:text;
    if(!digits[0]) return 0;
    for(const char *p=digits;*p;p++) if(*p<'0' || *p>'9') return 0;
    char *end; errno=0; long long value=strtoll(text,&end,10);
    if(errno || *end) return 0;
    *number=(int64_t)value; return 1;
}
static struct node *find_node(struct plan *plan,const char *path) {
    size_t lo=0,hi=plan->count;
    while(lo<hi) {
        size_t mid=lo+(hi-lo)/2; int comparison=strcmp(path,plan->nodes[mid].path);
        if(!comparison) return &plan->nodes[mid];
        if(comparison<0) hi=mid; else lo=mid+1;
    }
    return NULL;
}
static int read_plan(const char *length_text,struct plan *plan) {
    uint64_t length;
    if(!decimal(length_text,&length) || !length || length>MAX_DATA) { errno=EINVAL; return -1; }
    plan->data=malloc((size_t)length); plan->nodes=calloc(MAX_ENTRIES+1,sizeof(struct node));
    if(!plan->data || !plan->nodes) return -1;
    size_t received=0;
    while(received<length) {
        ssize_t n=read(STDIN_FILENO,plan->data+received,(size_t)length-received);
        if(n<0 && errno==EINTR) continue;
        if(n<=0) { if(!n) errno=EMSGSIZE; return -1; }
        received+=(size_t)n;
    }
    unsigned char extra; ssize_t n;
    do { n=read(STDIN_FILENO,&extra,1); } while(n<0 && errno==EINTR);
    if(n!=0) { if(n>0) errno=EMSGSIZE; return -1; }
    char *cursor=plan->data,*end=cursor+length;
    while(cursor<end) {
        if(plan->count==MAX_ENTRIES+1) { errno=E2BIG; return -1; }
        struct node *item=&plan->nodes[plan->count];
        char *parts[9];
        for(unsigned i=0;i<9;i++) if(!(parts[i]=field(&cursor,end))) { errno=EINVAL; return -1; }
        item->path=parts[0];
        if((!valid_relative(item->path) && strcmp(item->path,".")) ||
                (plan->count && strcmp(plan->nodes[plan->count-1].path,item->path)>=0) ||
                !decimal(parts[1],&item->device) || !decimal(parts[2],&item->inode) ||
                !decimal(parts[3],&item->mode) || !decimal(parts[4],&item->size) ||
                !signed_decimal(parts[5],&item->mtime) || !decimal(parts[6],&item->mns) ||
                !signed_decimal(parts[7],&item->ctime) || !decimal(parts[8],&item->cns) ||
                item->mode>UINT32_MAX || item->mns>=1000000000U || item->cns>=1000000000U ||
                (!S_ISDIR(item->mode) && !S_ISREG(item->mode))) { errno=EINVAL; return -1; }
        plan->count++;
    }
    if(!find_node(plan,".")) { errno=EINVAL; return -1; }
    return 0;
}
static int same_node(int fd,const struct node *expected,int full) {
    struct stat st;
    if(fstat(fd,&st)<0) return 0;
    if(!expected || st.st_uid!=getuid() || (uint64_t)st.st_dev!=expected->device ||
            (uint64_t)st.st_ino!=expected->inode || (uint64_t)st.st_mode!=expected->mode ||
            (S_ISREG(st.st_mode) && st.st_nlink!=1) ||
            (full && ((uint64_t)st.st_size!=expected->size || st.st_mtim.tv_sec!=expected->mtime ||
                (uint64_t)st.st_mtim.tv_nsec!=expected->mns || st.st_ctim.tv_sec!=expected->ctime ||
                (uint64_t)st.st_ctim.tv_nsec!=expected->cns))) { errno=ESTALE; return 0; }
    return 1;
}
static int verify_tree(int root,struct plan *plan,const char *path,unsigned depth,size_t *seen) {
    if(depth>MAX_DEPTH+1 || ++*seen>MAX_ENTRIES+1) { errno=E2BIG; return -1; }
    int fd=open_beneath(root,path,O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
    if(fd<0) return -1;
    struct node *expected=find_node(plan,path);
    if(!same_node(fd,expected,1)) { close(fd); return -1; }
    int directory=S_ISDIR(expected->mode); close(fd);
    if(!directory) return 0;
    if(depth>MAX_DEPTH) { errno=E2BIG; return -1; }
    fd=open_beneath(root,path,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0);
    if(fd<0) return -1;
    if(!same_node(fd,expected,1)) { close(fd); return -1; }
    DIR *stream=fdopendir(fd);
    if(!stream) { close(fd); return -1; }
    struct dirent *item; int result=0;
    for(;;) {
        errno=0; item=readdir(stream);
        if(!item) { if(errno) result=-1; break; }
        if(!strcmp(item->d_name,".") || !strcmp(item->d_name,"..")) continue;
        char child[PATH_MAX];
        int length=!strcmp(path,".")?snprintf(child,sizeof(child),"%s",item->d_name):snprintf(child,sizeof(child),"%s/%s",path,item->d_name);
        if(length<0 || (size_t)length>=sizeof(child)) { errno=ENAMETOOLONG; result=-1; break; }
        if(verify_tree(root,plan,child,depth+1,seen)<0) { result=-1; break; }
    }
    int saved=errno; closedir(stream); errno=saved; return result;
}
static int within(const char *parent,const char *path) {
    if(!strcmp(parent,".")) return 1;
    size_t length=strlen(parent);
    return !strncmp(parent,path,length) && (!path[length] || path[length]=='/');
}
static int parent_fd(int root,const char *path,char *leaf) {
    char parent[PATH_MAX]; strcpy(parent,path); char *slash=strrchr(parent,'/');
    if(slash) { strcpy(leaf,slash+1); *slash=0; }
    else { strcpy(leaf,path); strcpy(parent,"."); }
    return open_beneath(root,parent,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0);
}
static int remove_plan(int root,struct plan *plan,const char *path,int recursive,int force) {
    struct node *target=find_node(plan,path);
    if(!target) {
        int pin=open_beneath(root,path,O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
        if(pin>=0) { close(pin); errno=ESTALE; return error("tree-state"); }
        if(errno==ENOENT && force) return 0;
        return error("open");
    }
    if(S_ISDIR(target->mode) && !recursive) {
        for(size_t i=0;i<plan->count;i++) if(strcmp(path,plan->nodes[i].path) && within(path,plan->nodes[i].path)) {
            errno=ENOTEMPTY; return error("remove");
        }
    }
    // Reverse lexical order visits every child before its directory. The full
    // tree was compared with the authorized snapshot before the first unlink.
    for(size_t i=plan->count;i>0;i--) {
        struct node *item=&plan->nodes[i-1]; if(!within(path,item->path)) continue;
        char leaf[PATH_MAX]; int parent=parent_fd(root,item->path,leaf);
        if(parent<0) return error("open");
        int pin=open_beneath(parent,leaf,O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
        if(pin<0 || !same_node(pin,item,S_ISREG(item->mode))) { if(pin>=0) close(pin); close(parent); return error("tree-state"); }
        if(unlinkat(parent,leaf,S_ISDIR(item->mode)?AT_REMOVEDIR:0)<0) return error("remove");
        if(fsync(parent)<0) return error("directory-sync");
        close(pin); close(parent);
    }
    return 0;
}
static int copy_directory(int root,const char *path) {
    char components[PATH_MAX]; strcpy(components,path); char prefix[PATH_MAX]="";
    char *part=components;
    for(;;) {
        char *slash=strchr(part,'/'); if(slash) *slash=0;
        if(prefix[0]) strcat(prefix,"/");
        strcat(prefix,part);
        int fd=open_beneath(root,prefix,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0);
        if(fd<0) {
            if(errno!=ENOENT) return -1;
            char leaf[PATH_MAX]; int parent=parent_fd(root,prefix,leaf);
            if(parent<0) return -1;
            if(mkdirat(parent,leaf,0700)<0) { close(parent); return -1; }
            fd=open_beneath(parent,leaf,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0);
            if(fd<0 || fsync(parent)<0) { close(parent); return -1; }
            close(parent); if(fsync(fd)<0) { close(fd); return -1; }
        }
        struct stat st;
        if(fstat(fd,&st)<0 || st.st_uid!=getuid() || !S_ISDIR(st.st_mode)) { close(fd); errno=EPERM; return -1; }
        close(fd); if(!slash) break; part=slash+1;
    }
    return 0;
}
static int copy_file(int root,struct node *source,const char *destination) {
    int input=pinned_open(root,source->path,0);
    if(input<0) return error("open");
    if(!same_node(input,source,1)) return error("tree-state");
    unsigned char *bytes=malloc((size_t)source->size+1);
    if(!bytes) return error("allocation");
    size_t size=0;
    while(size<=source->size) {
        ssize_t received=read(input,bytes+size,(size_t)source->size+1-size);
        if(received<0 && errno==EINTR) continue;
        if(received<0) return error("read");
        if(!received) break;
        size+=(size_t)received;
    }
    if(size!=source->size || !same_node(input,source,1)) { errno=ESTALE; return error("tree-state"); }
    int output=pinned_open(root,destination,1);
    if(output<0) return error("open");
    if(!ordinary(output)) return error("file-kind");
    if(ftruncate(output,0)<0 || write_all(output,bytes,size)<0 || fchmod(output,(mode_t)source->mode&0777)<0 || fsync(output)<0) return error("copy");
    char leaf[PATH_MAX]; int parent=parent_fd(root,destination,leaf);
    if(parent<0 || fsync(parent)<0) return error("directory-sync");
    close(parent); close(input); close(output); free(bytes); return 0;
}
static int copy_plan(int root,struct plan *plan,const char *source,const char *destination,int recursive) {
    struct node *target=find_node(plan,source);
    if(!target) { errno=ENOENT; return error("open"); }
    if(within(source,destination) || within(destination,source)) { errno=EINVAL; return error("copy"); }
    if(S_ISDIR(target->mode) && !recursive) { errno=EINVAL; return error("copy"); }
    uint64_t total=0,new_count=0;
    // Complete semantic/type/size preflight before making a directory or
    // truncating any file. The Python side separately authorizes all mappings.
    for(size_t i=0;i<plan->count;i++) {
        struct node *item=&plan->nodes[i]; if(!within(source,item->path)) continue;
        char path[PATH_MAX]; int length=snprintf(path,sizeof(path),"%s%s",destination,item->path+strlen(source));
        if(length<0 || (size_t)length>=sizeof(path) || !valid_relative(path)) { errno=ENAMETOOLONG; return error("copy"); }
        unsigned depth=1;
        for(const char *p=path;*p;p++) if(*p=='/') depth++;
        if(depth>MAX_DEPTH+(S_ISREG(item->mode)?1U:0U)) { errno=E2BIG; return error("copy"); }
        struct node *existing=find_node(plan,path);
        if(existing && ((existing->mode&S_IFMT)!=(item->mode&S_IFMT))) { errno=EINVAL; return error("copy"); }
        if(!existing) new_count++;
        if(S_ISREG(item->mode)) {
            if(item->size>MAX_DATA || total>MAX_DATA-item->size || (item->mode&07000)) { errno=E2BIG; return error("copy"); }
            total+=item->size;
        }
        char ancestor[PATH_MAX]; strcpy(ancestor,path); char *slash;
        while((slash=strrchr(ancestor,'/'))) {
            *slash=0; struct node *parent=find_node(plan,ancestor);
            if(parent && !S_ISDIR(parent->mode)) { errno=ENOTDIR; return error("copy"); }
            if(!parent && item==target && S_ISDIR(target->mode)) new_count++;
        }
    }
    if(plan->count-1+new_count>MAX_ENTRIES) { errno=E2BIG; return error("copy"); }
    umask(0077);
    for(size_t i=0;i<plan->count;i++) {
        struct node *item=&plan->nodes[i]; if(!within(source,item->path)) continue;
        char path[PATH_MAX]; snprintf(path,sizeof(path),"%s%s",destination,item->path+strlen(source));
        if(S_ISDIR(item->mode)) { if(copy_directory(root,path)<0) return error("copy"); }
        else { int failure=copy_file(root,item,path); if(failure) return failure; }
    }
    return 0;
}
static int planned_operation(int root,char **argv) {
    struct plan plan={0};
    if(read_plan(argv[4],&plan)<0) return error("tree-plan");
    size_t seen=0;
    if(verify_tree(root,&plan,".",0,&seen)<0 || seen!=plan.count) { if(seen!=plan.count) errno=ESTALE; return error("tree-state"); }
    if(!strcmp(argv[1],"tree")) {
        if(!find_node(&plan,argv[3])) { errno=ENOENT; return error("open"); }
        return 0;
    }
    if(!strcmp(argv[1],"remove")) return remove_plan(root,&plan,argv[3],!strcmp(argv[5],"1"),!strcmp(argv[6],"1"));
    return copy_plan(root,&plan,argv[3],argv[5],!strcmp(argv[6],"1"));
}
static int create_directories(int root,char **argv) {
    /* The trusted policy side authorizes EVERY missing suffix component and
     * supplies the identity of the last existing directory it inspected.
     * Recheck that immutable plan before the first mutation. Neither an
     * unexpected existing object nor a missing ancestor is adopted/retried.
     */
    uint64_t missing,device,inode;
    if(!decimal(argv[4],&missing) || missing>MAX_DEPTH ||
            !decimal(argv[5],&device) || !decimal(argv[6],&inode)) {
        errno=EINVAL; return error("directory-state");
    }
    char path[PATH_MAX]; strcpy(path,argv[3]);
    char *components[MAX_DEPTH]; unsigned count=0;
    if(strcmp(path,".")) {
        char *next=path;
        for(;;) {
            if(count==MAX_DEPTH) { errno=E2BIG; return error("directory-state"); }
            components[count++]=next;
            char *slash=strchr(next,'/');
            if(slash) *slash=0;
            if(strlen(next)>NAME_MAX) { errno=ENAMETOOLONG; return error("directory-state"); }
            if(!slash) break;
            next=slash+1;
        }
    }
    if(missing>count) { errno=EINVAL; return error("directory-state"); }
    int recursive=!strcmp(argv[1],"mkdirs");
    if(!recursive && missing>1) { errno=ENOENT; return error("open"); }
    /* A request body is never interpreted as more directory authorizations. */
    int input_error=empty_input();
    if(input_error) return input_error;

    unsigned existing=count-(unsigned)missing;
    char prefix[PATH_MAX]="";
    for(unsigned i=0;i<existing;i++) {
        if(i) strcat(prefix,"/");
        strcat(prefix,components[i]);
    }
    int directory=existing?open_beneath(root,prefix,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0):dup(root);
    if(directory<0) return error("open");
    struct stat st;
    if(fstat(directory,&st)<0) return error("directory-state");
    if(!S_ISDIR(st.st_mode) || st.st_uid!=getuid() ||
            (uint64_t)st.st_dev!=device || (uint64_t)st.st_ino!=inode) {
        errno=ESTALE; return error("directory-state");
    }
    if(!missing) {
        if(!recursive) { errno=EEXIST; return error("mkdir"); }
        if(close(directory)<0) return error("close");
        return 0;
    }
    int check=open_beneath(directory,components[existing],O_PATH|O_CLOEXEC|O_NOFOLLOW,0);
    if(check>=0) { close(check); errno=EEXIST; return error("directory-state"); }
    if(errno!=ENOENT) return error("open");
    umask(0077);
    for(unsigned i=existing;i<count;i++) {
        if(mkdirat(directory,components[i],0700)<0) return error("mkdir");
        int child=open_beneath(directory,components[i],O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW,0);
        if(child<0) return error("open");
        if(fstat(child,&st)<0) return error("directory-state");
        if(!S_ISDIR(st.st_mode) || st.st_uid!=getuid() || (st.st_mode&0777)!=0700) {
            errno=EPERM; return error("directory-state");
        }
        if(fsync(child)<0 || fsync(directory)<0) return error("directory-sync");
        if(close(directory)<0) return error("close");
        directory=child;
    }
    if(close(directory)<0) return error("close");
    return 0;
}
int main(int argc,char **argv) {
    int planned=(argc==5 && !strcmp(argv[1],"tree")) ||
        (argc==7 && (!strcmp(argv[1],"remove") || !strcmp(argv[1],"copy")));
    int making=argc==7 && (!strcmp(argv[1],"mkdir") || !strcmp(argv[1],"mkdirs"));
    int inspecting=argc==5 && (!strcmp(argv[1],"metadata") ||
        !strcmp(argv[1],"metadata-nofollow") || !strcmp(argv[1],"canonicalize"));
    if((!making && !inspecting && !planned && (argc!=5 || (strcmp(argv[1],"read") && strcmp(argv[1],"write")))) ||
            (!valid_relative(argv[3]) && !((making || inspecting || (planned && !strcmp(argv[1],"tree"))) && !strcmp(argv[3],".")))) {
        errno=EINVAL; return error("invocation");
    }
    char *end;
    errno=0; long descriptor=strtol(argv[2],&end,10);
    if(errno || !argv[2][0] || *end || descriptor<3 || descriptor>INT_MAX) { errno=EINVAL; return error("root-fd"); }
    int root=(int)descriptor;
    struct stat root_stat;
    if(fstat(root,&root_stat)<0 || !S_ISDIR(root_stat.st_mode) || root_stat.st_uid!=getuid() || (root_stat.st_mode&0077)) {
        errno=EPERM; return error("root-ownership");
    }
    if(planned) {
        if(argc==7 && ((strcmp(argv[6],"0") && strcmp(argv[6],"1")) ||
                (!strcmp(argv[1],"remove") && strcmp(argv[5],"0") && strcmp(argv[5],"1")) ||
                (!strcmp(argv[1],"copy") && !valid_relative(argv[5])))) { errno=EINVAL; return error("invocation"); }
        return planned_operation(root,argv);
    }
    if(making) return create_directories(root,argv);
    if(inspecting) {
        if(strcmp(argv[4],"0")) { errno=EINVAL; return error("length"); }
        int input_error=empty_input();
        if(input_error) return input_error;
        return inspect_path(root,argv[1],argv[3]);
    }
    errno=0; unsigned long expected=strtoul(argv[4],&end,10);
    if(errno || !argv[4][0] || *end || expected>MAX_DATA || argv[4][0]=='-') { errno=EINVAL; return error("length"); }
    int writing=!strcmp(argv[1],"write");
    unsigned char *data=malloc(MAX_DATA+1);
    if(!data) return error("allocation");
    size_t length=0;
    // Collect a complete bounded write before opening the destination. A
    // truncated transport or an oversized request cannot truncate a file.
    if(writing) {
        while(length<=MAX_DATA) {
            ssize_t n=read(STDIN_FILENO,data+length,MAX_DATA+1-length);
            if(n<0 && errno==EINTR) continue;
            if(n<0) return error("input");
            if(!n) break;
            length+=(size_t)n;
        }
        if(length!=expected) { errno=EMSGSIZE; return error("input-length"); }
    }
    int fd=pinned_open(root,argv[3],writing);
    if(fd<0) return error("open");
    if(!ordinary(fd)) return error("file-kind");
    if(writing) {
        if(ftruncate(fd,0)<0 || write_all(fd,data,length)<0 || fsync(fd)<0) return error("write");
        // Sync the actual containing directory so creation also survives a
        // normal restart. No recursive operation or policy widening is used.
        char parent[PATH_MAX]; strcpy(parent,argv[3]); char *slash=strrchr(parent,'/');
        int directory;
        if(slash) { *slash=0; directory=open_beneath(root,parent,O_RDONLY|O_DIRECTORY|O_CLOEXEC,0); }
        else directory=dup(root);
        if(directory<0 || fsync(directory)<0) return error("directory-sync");
        close(directory);
    } else {
        while(length<=MAX_DATA) {
            ssize_t n=read(fd,data+length,MAX_DATA+1-length);
            if(n<0 && errno==EINTR) continue;
            if(n<0) return error("read");
            if(!n) break;
            length+=(size_t)n;
        }
        if(length>MAX_DATA) { errno=EFBIG; return error("read-bound"); }
        if(write_all(STDOUT_FILENO,data,length)<0) return error("output");
    }
    if(close(fd)<0) return error("close");
    close(root); free(data); return 0;
}
