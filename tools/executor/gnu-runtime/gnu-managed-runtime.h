/* GNU runtime constructor inputs are supervisor-owned, before any guest runs.
 * argv: __foldgpt_gnu_v1 ROOTFS LOADER LOADER32 SCRATCH GUEST_TMP FD_CAPACITY GUEST_CWD -- COMMAND...
 * Runtime roots are read/execute grants; the real workspace's write policy is
 * still decided by NativeProcessPolicy over the original complete context.
 */
static char gnu_scratch_path[PATH_MAX],gnu_tmp_path[PATH_MAX],gnu_rootfs[PATH_MAX];
static int gnu_scratch=-1,gnu_tmp=-1;
static char *gnu_argv[MAX_ARGS+1], *gnu_environment[8];
static char gnu_f2fs_environment[]="PROOT_F2FS_WORKAROUND=0";

/* Preserve PRoot's actual cross-process F2FS case-sensitivity test while the
 * trusted launcher still has its private scratch FDs. The usual PRoot helper
 * is a different PID, so giving it post-confinement scratch authority would
 * weaken the leader-only rule. This is a measured result, never a forced 0.
 * Runs only after supervisor identity acknowledgement, under its owned process
 * group. Any inconclusive probe is a setup failure before the GNU command. */
static int gnu_f2fs_probe(void) {
    char path[PATH_MAX];int n=snprintf(path,sizeof(path),"%s/f2fs-check-XXXXXX",gnu_scratch_path);
    if(n<1||n>=PATH_MAX||!mkdtemp(path))return -1;
    int directory=open(path,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW),fd=-1,result=-1,saved=0;
    if(directory<0)goto done;
    fd=openat(directory,"aa",O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    if(fd<0)goto done;
    close(fd);fd=-1;
    fd=openat(directory,"Aa",O_WRONLY|O_CREAT|O_EXCL|O_CLOEXEC|O_NOFOLLOW,0600);
    if(fd<0){if(errno==EEXIST)result=0;goto done;}
    close(fd);fd=-1;
    if(faccessat(directory,"aA",F_OK,0)==0){errno=EIO;goto done;}
    if(errno!=ENOENT)goto done;
    pid_t child=fork();
    if(child<0)goto done;
    if(!child){
        int created=openat(directory,"aA",O_WRONLY|O_CREAT|O_CLOEXEC|O_NOFOLLOW,0600);
        if(created<0)_exit(errno==EEXIST?1:2);
        close(created);_exit(0);
    }
    int status=0;pid_t observed;
    do{observed=waitpid(child,&status,0);}while(observed<0&&errno==EINTR);
    if(observed!=child||!WIFEXITED(status)||WEXITSTATUS(status)>1){errno=EIO;goto done;}
    result=WEXITSTATUS(status);
done:
    saved=errno;
    if(fd>=0)close(fd);
    if(directory>=0){
        const char *names[]={"aa","Aa","aA"};
        for(unsigned i=0;i<3;i++)if(unlinkat(directory,names[i],0)<0&&errno!=ENOENT){result=-1;saved=errno;}
        close(directory);
    }
    if(rmdir(path)<0){result=-1;saved=errno;}
    if(result>=0)gnu_f2fs_environment[sizeof(gnu_f2fs_environment)-2]=(char)('0'+result);
    errno=saved;return result<0?-1:0;
}
static int gnu_dynamic_elf(int fd) {
    Elf64_Ehdr h;
    if(pread(fd,&h,sizeof(h),0)!=(ssize_t)sizeof(h)||memcmp(h.e_ident,ELFMAG,SELFMAG)||
       h.e_ident[EI_CLASS]!=ELFCLASS64||h.e_ident[EI_DATA]!=ELFDATA2LSB||
       (h.e_type!=ET_EXEC&&h.e_type!=ET_DYN)||h.e_phentsize!=sizeof(Elf64_Phdr)||!h.e_phnum||h.e_phnum>128){errno=ENOEXEC;return -1;}
#if defined(__aarch64__)
    if(h.e_machine!=EM_AARCH64){errno=ENOEXEC;return -1;}
#else
    if(h.e_machine!=EM_X86_64){errno=ENOEXEC;return -1;}
#endif
    for(unsigned i=0;i<h.e_phnum;i++) {
        Elf64_Phdr p;uint64_t at=h.e_phoff+(uint64_t)i*sizeof(p);
        if(at>INT64_MAX||pread(fd,&p,sizeof(p),(off_t)at)!=(ssize_t)sizeof(p)||
           (p.p_type==PT_LOAD&&(p.p_flags&(PF_W|PF_X))==(PF_W|PF_X))){errno=ENOEXEC;return -1;}
    }
    return 0;
}
static int gnu_grant(struct config *c,const char *path,uint64_t rights,int optional) {
    if(c->count>=MAX_GRANTS){errno=E2BIG;return -1;}
    int fd=open(path,O_PATH|O_CLOEXEC);
    if(fd<0)return optional&&errno==ENOENT?0:-1;
    struct stat info;
    if(fstat(fd,&info)<0){close(fd);return -1;}
    if(!S_ISDIR(info.st_mode))rights&=~LL_READ_DIR;
    c->grants[c->count++]=(struct grant){.fd=fd,.rights=rights};return 0;
}
static int gnu_argument(int *n,char *value) {
    if(*n>=MAX_ARGS){errno=E2BIG;return -1;}gnu_argv[(*n)++]=value;return 0;
}
static int gnu_prepare(struct config *c,const char *proot) {
    if(!c->argv[0]||strcmp(c->argv[0],"__foldgpt_gnu_v1")||!c->argv[9]||strcmp(c->argv[8],"--")) {errno=EINVAL;return -1;}
    char *root=c->argv[1],*loader=c->argv[2],*loader32=c->argv[3],*scratch=c->argv[4],*tmp=c->argv[5],*cwd=c->argv[7];
    char *end=NULL;errno=0;unsigned long long descriptor_capacity=strtoull(c->argv[6],&end,10);
    struct rlimit inherited;
    if(errno||!*c->argv[6]||*end||descriptor_capacity<c->fds||getrlimit(RLIMIT_NOFILE,&inherited)<0||
       descriptor_capacity>inherited.rlim_cur||descriptor_capacity>inherited.rlim_max){errno=EINVAL;return -1;}
    c->fds=descriptor_capacity;
    if(!canonical(root)||!canonical(loader)||!canonical(loader32)||!canonical(scratch)||
       !canonical(tmp)||forbidden_tree(scratch)||forbidden_tree(tmp)||
       beneath(scratch,mg_root_path)||beneath(mg_root_path,scratch)||
       beneath(tmp,mg_root_path)||beneath(mg_root_path,tmp)||beneath(scratch,tmp)||beneath(tmp,scratch)||cwd[0]!='/') {errno=EPERM;return -1;}
    strcpy(gnu_scratch_path,scratch);strcpy(gnu_tmp_path,tmp);strcpy(gnu_rootfs,root);
    gnu_scratch=open(scratch,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
    gnu_tmp=open(tmp,O_RDONLY|O_DIRECTORY|O_CLOEXEC|O_NOFOLLOW);
    unsigned objects=0;if(gnu_scratch<0||gnu_tmp<0||scan_workspace(gnu_scratch,&objects,0)<0||scan_workspace(gnu_tmp,&objects,0)<0)return -1;
    const uint64_t reads=LL_EXECUTE|LL_READ_FILE|LL_READ_DIR;
    const char *parts[]={"usr","lib","lib64","bin"};
    for(unsigned i=0;i<4;i++){char path[PATH_MAX];int n=snprintf(path,sizeof(path),"%s/%s",root,parts[i]);
        if(n<1||n>=PATH_MAX||gnu_grant(c,path,reads,1)<0)return -1;}
    char configuration[PATH_MAX];int length=snprintf(configuration,sizeof(configuration),"%s/etc",root);
    if(length<1||length>=PATH_MAX||gnu_grant(c,configuration,LL_READ_FILE|LL_READ_DIR,0)<0)return -1;
#ifdef __ANDROID__
    const char *system[]={"/apex/com.android.runtime/bin","/apex/com.android.runtime/lib64",
        "/apex/com.android.i18n/lib64","/apex/com.android.art/lib64","/apex/com.android.tethering/lib64",
        "/system/bin","/system/lib64"};
    for(unsigned i=0;i<sizeof(system)/sizeof(system[0]);i++)if(gnu_grant(c,system[i],reads,0)<0)return -1;
    if(gnu_grant(c,"/linkerconfig/ld.config.txt",LL_READ_FILE,0)<0)return -1;
#else
    if(gnu_grant(c,"/lib",reads,0)<0||gnu_grant(c,"/lib64",reads,1)<0)return -1;
#endif
    if(gnu_grant(c,loader,LL_EXECUTE|LL_READ_FILE,0)<0||gnu_grant(c,loader32,LL_EXECUTE|LL_READ_FILE,0)<0||
       gnu_grant(c,mg_root_path,LL_READ_FILE|LL_READ_DIR,0)<0||gnu_grant(c,scratch,reads,0)<0||
       gnu_grant(c,tmp,LL_READ_FILE|LL_READ_DIR,0)<0||
       gnu_grant(c,"/dev/null",LL_READ_FILE,0)<0||gnu_grant(c,"/dev/urandom",LL_READ_FILE,0)<0)return -1;
    char *native_dir=strdup(proot),*last=native_dir?strrchr(native_dir,'/'):NULL;
    if(!last){errno=ENOMEM;return -1;}*last=0;
#ifdef __ANDROID__
    const char *libraries[]={"libtalloc.so","libandroid-shmem.so"};
    for(unsigned i=0;i<2;i++){char path[PATH_MAX];snprintf(path,sizeof(path),"%s/%s",native_dir,libraries[i]);
        if(gnu_grant(c,path,LL_READ_FILE,0)<0)return -1;}
#endif
    if(asprintf(&gnu_environment[0],"PROOT_TMP_DIR=%s",scratch)<0||
       asprintf(&gnu_environment[1],"PROOT_LOADER=%s",loader)<0||
       asprintf(&gnu_environment[2],"PROOT_LOADER_32=%s",loader32)<0||
       asprintf(&gnu_environment[3],"LD_LIBRARY_PATH=%s:%s",scratch,native_dir)<0)return -1;
    gnu_environment[4]="PROOT_NO_SECCOMP=1";
    unsigned environment_count=5;
#ifdef __ANDROID__
    /* Load the actual immutable APK library by path. Its DT_SONAME satisfies
     * PRoot's libtalloc.so.2 dependency without a writable compatibility alias. */
    if(asprintf(&gnu_environment[5],"LD_PRELOAD=%s/libtalloc.so",native_dir)<0)return -1;
    environment_count=6;
#endif
    gnu_environment[environment_count++]=gnu_f2fs_environment;
    char *workbind=NULL,*tmpbind=NULL;
    if(asprintf(&workbind,"%s:%s",mg_root_path,cwd)<0||asprintf(&tmpbind,"%s:/tmp",tmp)<0)return -1;
    int n=0;
#define GARG(v) do{if(gnu_argument(&n,(char *)(v))<0)return -1;}while(0)
    GARG(proot);GARG("--strict-sandbox");GARG("--kill-on-exit");GARG("-r");GARG(root);
#ifdef GNU_DIAGNOSTIC
    GARG("-v");GARG("9");
#endif
    GARG("-w");GARG(cwd);GARG("-b");GARG(workbind);GARG("-b");GARG(tmpbind);
    GARG("-b");GARG("/proc");GARG("-b");GARG("/dev");
#ifdef __ANDROID__
    GARG("-b");GARG("/system");GARG("-b");GARG("/apex");
#endif
    GARG("-b");GARG("/dev/null:/etc/ld.so.preload");GARG("/usr/bin/env");GARG("-i");GARG("--");
    for(int i=0;c->env[i];i++)GARG(c->env[i]);
    for(int i=9;c->argv[i];i++)GARG(c->argv[i]);
    memset(c->argv,0,sizeof(c->argv));memcpy(c->argv,gnu_argv,(size_t)n*sizeof(char *));
    memset(c->env,0,sizeof(c->env));memcpy(c->env,gnu_environment,environment_count*sizeof(char *));
#undef GARG
    return 0;
}
