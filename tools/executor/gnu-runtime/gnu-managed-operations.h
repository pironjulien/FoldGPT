/* Native GNU syscall mediation; no SECCOMP_USER_NOTIF_FLAG_CONTINUE. */
#include <sys/sysmacros.h>
static int gnu_reply(int listener,uint64_t id,int error) {
    if(error)return mg_deny(listener,id,error);
    struct seccomp_notif_resp reply={.id=id,.val=0};
    if(ioctl(listener,SECCOMP_IOCTL_NOTIF_SEND,&reply)<0&&errno!=ENOENT)return -1;
    mg_grants++;return 0;
}
static const char *gnu_below(const char *path,const char *root) {
    size_t n=strlen(root);return !strncmp(path,root,n)&&path[n]=='/'?path+n+1:NULL;
}
static int gnu_clean_path(char path[PATH_MAX]) {
    char normalized[PATH_MAX];size_t used=0;const char *p=path;
    if(*p=='/')normalized[used++]='/';
    while(*p){while(*p=='/')p++;if(!*p)break;const char *end=strchr(p,'/');size_t n=end?(size_t)(end-p):strlen(p);
        if(n==2&&!memcmp(p,"..",2))return 0;
        if(!(n==1&&*p=='.')){if(used&&normalized[used-1]!='/')normalized[used++]='/';memcpy(normalized+used,p,n);used+=n;}
        p+=n;}
    normalized[used]=0;strcpy(path,normalized);return used>0;
}
static int gnu_relative(const char *p) {
    if(!p||!*p||*p=='/')return 0;
    for(;;){const char *s=strchr(p,'/');size_t n=s?(size_t)(s-p):strlen(p);
        if(!n||(n==1&&p[0]=='.')||(n==2&&!memcmp(p,"..",2)))return 0;
        if(!s)return 1;
        p=s+1;}
}
static int gnu_pin_parent(int root,const char *relative,char leaf[NAME_MAX+1]) {
    if(!gnu_relative(relative)){errno=EPERM;return -1;}
    char parent[PATH_MAX];strcpy(parent,relative);char *slash=strrchr(parent,'/');
    const char *name=slash?slash+1:relative;if(strlen(name)>NAME_MAX){errno=ENAMETOOLONG;return -1;}
    strcpy(leaf,name);if(slash)*slash=0;else strcpy(parent,".");
    struct open_how how={.flags=O_PATH|O_DIRECTORY|O_CLOEXEC,
        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    return (int)syscall(SYS_openat2,root,parent,&how,sizeof(how));
}
static int gnu_inject(int listener,const struct seccomp_notif *r,int fd,uint64_t flags) {
    int valid=mg_valid(listener,r->id);if(valid<=0){close(fd);return valid;}
    struct seccomp_notif_addfd add={.id=r->id,.flags=SECCOMP_ADDFD_FLAG_SEND,.srcfd=(uint32_t)fd,
        .newfd_flags=(flags&O_CLOEXEC)?O_CLOEXEC:0};
    int result=ioctl(listener,SECCOMP_IOCTL_NOTIF_ADDFD,&add),saved=errno;close(fd);
    if(result<0)return saved==ENOENT?0:mg_deny(listener,r->id,saved);
    mg_grants++;return 0;
}
static int gnu_scratch_open(int listener,const struct seccomp_notif *r,const char *path,uint64_t flags,uint64_t mode) {
    if((pid_t)r->pid!=mg_leader||mg_reaped)return mg_deny(listener,r->id,EACCES);
    const char *relative=gnu_below(path,gnu_scratch_path);
    const uint64_t allowed=O_ACCMODE|O_CREAT|O_TRUNC|O_APPEND|O_EXCL|O_CLOEXEC|O_NOFOLLOW|O_NONBLOCK|O_LARGEFILE;
    if(!relative||!gnu_relative(relative)||(flags&~allowed)||(mode&~0777ULL))return mg_deny(listener,r->id,EPERM);
    struct open_how how={.flags=flags|O_CLOEXEC|O_NOFOLLOW,.mode=(flags&O_CREAT)?mode:0,
        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    int fd=(int)syscall(SYS_openat2,gnu_scratch,relative,&how,sizeof(how));
    if(fd<0)return mg_deny(listener,r->id,errno);
    struct stat info;if(!mg_ordinary(fd,&info,0)){close(fd);return mg_deny(listener,r->id,EPERM);}
    return gnu_inject(listener,r,fd,flags);
}
static int gnu_workspace_open(int listener,const struct seccomp_notif *r,char path[PATH_MAX],uint64_t flags,uint64_t mode,int temporary) {
    if(temporary){const char *relative=gnu_below(path,gnu_tmp_path);if(!gnu_relative(relative))return mg_deny(listener,r->id,EPERM);
        memmove(path,relative,strlen(relative)+1);}
    const uint64_t allowed=O_ACCMODE|O_APPEND|O_CLOEXEC|O_CREAT|O_EXCL|O_TRUNC|O_NOFOLLOW|O_NONBLOCK|O_LARGEFILE;
    if((flags&~allowed)||(flags&O_ACCMODE)==O_ACCMODE||((flags&O_TRUNC)&&(flags&O_ACCMODE)==O_RDONLY)||
       (mode&~0777ULL)||!mg_relative(path))return mg_deny(listener,r->id,EOPNOTSUPP);
    if(!(flags&O_CREAT))mode=0;
    struct mg_decision decision={0};
    gnu_policy_tmp=temporary;
    int status=mg_decide(r,r->data.args[1],path,flags,mode,&decision);gnu_policy_tmp=0;
    if(status<0)return -1;
    if(!decision.allow)return mg_deny(listener,r->id,EACCES);
    int valid=mg_valid(listener,r->id);if(valid<=0)return valid;
    int fd=mg_open_file(temporary?gnu_tmp:mg_root,path,flags,mode,&decision);
    return fd<0?mg_deny(listener,r->id,errno):gnu_inject(listener,r,fd,flags);
}
static int gnu_mode(int listener,const struct seccomp_notif *r) {
    if((pid_t)r->pid!=mg_leader||mg_reaped)return mg_deny(listener,r->id,EACCES);
    char path[PATH_MAX];uint64_t mode;int fd=-1,error=0;
    if(r->data.nr==SYS_fchmod){
        if(r->data.args[0]>INT_MAX)return mg_deny(listener,r->id,EINVAL);
        mode=r->data.args[1];char proc[80];snprintf(proc,sizeof(proc),"/proc/%u/fd/%d",r->pid,(int)r->data.args[0]);
        fd=open(proc,O_RDONLY|O_NONBLOCK|O_CLOEXEC);if(fd<0)return mg_deny(listener,r->id,errno);
        snprintf(proc,sizeof(proc),"/proc/self/fd/%d",fd);ssize_t n=readlink(proc,path,sizeof(path)-1);
        if(n<1||n>=(ssize_t)sizeof(path)-1){close(fd);return mg_deny(listener,r->id,EPERM);}path[n]=0;
    }else{
        int arg=1;
#ifdef SYS_chmod
        if(r->data.nr==SYS_chmod)arg=0;
#endif
        mode=r->data.args[arg+1];error=mg_copy((pid_t)r->pid,r->data.args[arg],path,sizeof(path),1);
        if(error)return mg_deny(listener,r->id,error);
    }
    const char *relative=gnu_below(path,gnu_scratch_path);
    if(!relative||!gnu_relative(relative)||(mode&~0777ULL)){if(fd>=0)close(fd);return mg_deny(listener,r->id,EPERM);}
    struct open_how how={.flags=O_RDONLY|O_NONBLOCK|O_CLOEXEC,
        .resolve=RESOLVE_BENEATH|RESOLVE_NO_SYMLINKS|RESOLVE_NO_XDEV};
    int proof=(int)syscall(SYS_openat2,gnu_scratch,relative,&how,sizeof(how));
    struct stat a,b;
    if(proof<0||fstat(proof,&a)<0||a.st_uid!=getuid()||(!S_ISDIR(a.st_mode)&&(!S_ISREG(a.st_mode)||a.st_nlink!=1))||
       (fd>=0&&(fstat(fd,&b)<0||a.st_dev!=b.st_dev||a.st_ino!=b.st_ino)))error=EPERM;
    int valid=error?1:mg_valid(listener,r->id);
    if(!error&&valid>0&&fchmod(proof,(mode_t)mode)<0)error=errno;
    if(proof>=0)close(proof);
    if(fd>=0)close(fd);
    return valid<=0?valid:gnu_reply(listener,r->id,error);
}
static int gnu_decide_mutation(const struct seccomp_notif *r,const char *operation,const char *path,const char *to,int temporary) {
    char hex[2*PATH_MAX+1],dest[2*PATH_MAX+1],frame[MG_FRAME],reply[256];
    const char *digits="0123456789abcdef";const char *paths[]={path,to};char *outputs[]={hex,dest};
    for(int j=0;j<2;j++){size_t n=strlen(paths[j]);for(size_t i=0;i<n;i++){unsigned char b=paths[j][i];outputs[j][2*i]=digits[b>>4];outputs[j][2*i+1]=digits[b&15];}outputs[j][2*n]=0;}
    int n=snprintf(frame,sizeof(frame),"{\"type\":\"%s\",\"id\":%"PRIu64",\"operation\":\"%s\",\"pathHex\":\"%s\",\"destinationHex\":\"%s\"}",temporary?"mutationTmp":"mutation",(uint64_t)r->id,operation,hex,dest);
    if(n<0||n>=(int)sizeof(frame)||mg_packet(mg_channel,frame,(size_t)n)<0)return -1;
    n=mg_receive(mg_channel,reply,sizeof(reply));if(n<0)return -1;
    struct parser *p=calloc(1,sizeof(*p));if(!p)return -1;
    p->cursor=(unsigned char *)reply;p->end=(unsigned char *)reply+n;
    int root=value(p,0);space(p);uint64_t id=0,allow=0;const char *fields[]={"id","allow"};
    int okay=root>=0&&p->cursor==p->end&&keys(p,root,fields,2)==0&&number_field(p,root,"id",0,UINT64_MAX,&id)==0&&id==r->id&&number_field(p,root,"allow",0,1,&allow)==0;
    for(int i=1;i<=p->used;i++)if(p->nodes[i].type==STRING)free(p->nodes[i].string);
    free(p);
    if(!okay){errno=EPROTO;return -1;}return (int)allow;
}
static int gnu_mutation(int listener,const struct seccomp_notif *r,const char *operation,uint64_t pointer,uint64_t destination,uint64_t flags,uint64_t mode) {
    char path[PATH_MAX],target[PATH_MAX]="";int error=mg_copy((pid_t)r->pid,pointer,path,sizeof(path),1);
    if(!error&&destination)error=mg_copy((pid_t)r->pid,destination,target,sizeof(target),1);
    if(error)return mg_deny(listener,r->id,error);
    if(!gnu_clean_path(path)||(destination&&!gnu_clean_path(target)))return mg_deny(listener,r->id,EPERM);
#ifdef GNU_DIAGNOSTIC
    int debug=openat(gnu_scratch,"operations.log",O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC,0600);
    if(debug>=0){dprintf(debug,"op=%s path=%s target=%s root=%s flags=%llu mode=%llu\n",operation,path,target,mg_root_path,(unsigned long long)flags,(unsigned long long)mode);close(debug);}
#endif
    const char *relative=gnu_below(path,mg_root_path),*to=destination?gnu_below(target,mg_root_path):"";
    int root=mg_root,is_workspace=relative!=NULL,temporary=0;
    if(!relative){relative=gnu_below(path,gnu_tmp_path);root=gnu_tmp;to=destination?gnu_below(target,gnu_tmp_path):"";temporary=relative!=NULL;}
    if(!relative){
        if((pid_t)r->pid!=mg_leader||mg_reaped)return mg_deny(listener,r->id,EACCES);
        relative=gnu_below(path,gnu_scratch_path);root=gnu_scratch;to=destination?gnu_below(target,gnu_scratch_path):"";
    }
    if(!gnu_relative(relative)||(destination&&!gnu_relative(to))||(mode&~0777ULL)||flags>1)return mg_deny(listener,r->id,EPERM);
    if(is_workspace||temporary){int allowed=gnu_decide_mutation(r,operation,relative,to,temporary);if(allowed<0)return -1;if(!allowed)return mg_deny(listener,r->id,EACCES);}
    int valid=mg_valid(listener,r->id);if(valid<=0)return valid;
    char leaf[NAME_MAX+1],newleaf[NAME_MAX+1];int parent=gnu_pin_parent(root,relative,leaf),newparent=-1,result=-1;
    if(parent<0)return mg_deny(listener,r->id,errno);
    if(!strcmp(operation,"mkdir"))result=mkdirat(parent,leaf,(mode_t)mode);
    else if(!strcmp(operation,"unlink")||!strcmp(operation,"rmdir"))result=unlinkat(parent,leaf,!strcmp(operation,"rmdir")?AT_REMOVEDIR:0);
    else if(!strcmp(operation,"rename")){
        newparent=gnu_pin_parent(root,to,newleaf);
        if(newparent>=0)result=(int)syscall(SYS_renameat2,parent,leaf,newparent,newleaf,(unsigned)flags);
    }else errno=EOPNOTSUPP;
    error=result<0?errno:0;if(newparent>=0)close(newparent);close(parent);return gnu_reply(listener,r->id,error);
}
static int gnu_notification(int listener,const struct seccomp_notif *r) {
    if(r->flags||r->data.arch!=MG_ARCH)return mg_deny(listener,r->id,EPERM);
    int valid=mg_valid(listener,r->id);if(valid<=0)return valid;
    int nr=r->data.nr;
#ifdef GNU_DIAGNOSTIC
    int debug=openat(gnu_scratch,"syscalls.log",O_WRONLY|O_CREAT|O_APPEND|O_CLOEXEC,0600);
    if(debug>=0){dprintf(debug,"nr=%d args=%llu,%llu,%llu,%llu\n",nr,(unsigned long long)r->data.args[0],(unsigned long long)r->data.args[1],(unsigned long long)r->data.args[2],(unsigned long long)r->data.args[3]);close(debug);}
#endif
    if(nr==SYS_fchmod||nr==SYS_fchmodat
#ifdef SYS_chmod
       ||nr==SYS_chmod
#endif
    )return gnu_mode(listener,r);
    if(nr==SYS_mkdirat)return gnu_mutation(listener,r,"mkdir",r->data.args[1],0,0,r->data.args[2]);
    if(nr==SYS_unlinkat){if(r->data.args[2]!=0&&r->data.args[2]!=AT_REMOVEDIR)return mg_deny(listener,r->id,EINVAL);
        return gnu_mutation(listener,r,r->data.args[2]?"rmdir":"unlink",r->data.args[1],0,0,0);}
    if(nr==SYS_renameat||nr==SYS_renameat2)return gnu_mutation(listener,r,"rename",r->data.args[1],r->data.args[3],nr==SYS_renameat2?r->data.args[4]:0,0);
#ifdef SYS_mkdir
    if(nr==SYS_mkdir)return gnu_mutation(listener,r,"mkdir",r->data.args[0],0,0,r->data.args[1]);
    if(nr==SYS_unlink||nr==SYS_rmdir)return gnu_mutation(listener,r,nr==SYS_rmdir?"rmdir":"unlink",r->data.args[0],0,0,0);
    if(nr==SYS_rename)return gnu_mutation(listener,r,"rename",r->data.args[0],r->data.args[1],0,0);
#endif
    if(nr==SYS_openat){
        char path[PATH_MAX];int error=mg_copy((pid_t)r->pid,r->data.args[1],path,sizeof(path),1);
        if(error)return mg_deny(listener,r->id,error);
        if(!gnu_clean_path(path))return mg_deny(listener,r->id,EPERM);
        if(gnu_below(path,gnu_scratch_path))return gnu_scratch_open(listener,r,path,r->data.args[2],r->data.args[3]);
        if(!strcmp(path,"/dev/null")&&!(r->data.args[2]&~(uint64_t)(O_ACCMODE|O_CLOEXEC|O_LARGEFILE|O_CREAT|O_EXCL|O_TRUNC|O_APPEND|O_NOFOLLOW|O_NONBLOCK))&&
           (r->data.args[2]&O_ACCMODE)!=O_ACCMODE&&!(r->data.args[3]&~0777ULL)){
            /* Shell redirects use O_CREAT|O_TRUNC even for this existing null
             * device. Open the actual node and verify its kernel identity;
             * no pathname replacement or ordinary-file create is admitted. */
            int fd=open("/dev/null",(int)r->data.args[2]|O_CLOEXEC|O_NOFOLLOW,(mode_t)r->data.args[3]);struct stat info;
            if(fd<0)return mg_deny(listener,r->id,errno);
            if(fstat(fd,&info)<0||!S_ISCHR(info.st_mode)||info.st_rdev!=makedev(1,3)){close(fd);return mg_deny(listener,r->id,EPERM);}
            return gnu_inject(listener,r,fd,r->data.args[2]);}
        return gnu_workspace_open(listener,r,path,r->data.args[2],r->data.args[3],gnu_below(path,gnu_tmp_path)!=NULL);
    }
    return mg_deny(listener,r->id,EPERM);
}
