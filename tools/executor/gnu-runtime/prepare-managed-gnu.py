"""Freeze an opt-in GNU derivative; never change the native static runner."""
import hashlib
import json
from pathlib import Path

here = Path(__file__).resolve().parent
base = here.parent/'native-managed-runner.c'
source = base.read_text()
changes = [
    ('static int mg_channel=-1, mg_root=-1, mg_exec=-1;', 'static int mg_channel=-1, mg_root=-1, mg_exec=-1;\nstatic int gnu_policy_tmp;'),
    ('#include "native-runner.c"', '#include "../native-runner.c"'),
    ('#include "native-managed-filter.h"', '#include "../native-managed-filter.h"\n#include "gnu-managed-filter.h"'),
    ('static int mg_static_elf(int fd)', 'static int mg_static_reference_elf(int fd)'),
    ('static void mg_launch(struct config *c,', '#include "gnu-managed-runtime.h"\n\nstatic void mg_launch(struct config *c,'),
    ('int listener=mg_notification_filter();', 'int listener=gnu_notification_filter();'),
    ('dup2(error,2)<0||ptrace(PTRACE_TRACEME,', 'dup2(error,2)<0||gnu_f2fs_probe()<0||ptrace(PTRACE_TRACEME,'),
    ('if(nr_install_seccomp()<0)goto failed;', '/* The opt-in GNU filter above is complete; the static filter is a different profile. */'),
    ('static int mg_notification(int listener,', 'static int mg_workspace_notification(int listener,'),
    ('static int mg_supervise(struct config *c)', '#include "gnu-managed-operations.h"\n\nstatic int mg_supervise(struct config *c)'),
    ('else if(mg_notification(listener,request)<0)', 'else if(gnu_notification(listener,request)<0)'),
    ('mg_static_elf(mg_exec)<0', 'gnu_dynamic_elf(mg_exec)<0'),
    ('for(int i=arg_start;i<argc;i++)c.argv[i-arg_start]=argv[i];', 'for(int i=arg_start;i<argc;i++)c.argv[i-arg_start]=argv[i];\n    if(gnu_prepare(&c,argv[3])<0)return fail("gnu-runtime-admission");'),
    ('int main(int argc,char **argv) {', 'int main(int argc,char **argv) {\n    (void)mg_notification_filter; /* Preserve reference source, never install the static profile here. */'),
]
for old,new in changes:
    if source.count(old)!=1: raise RuntimeError(f'Base changed at {old}')
    source=source.replace(old,new)
# Retain the original admission routine visibly without compiler noise.
source=source.replace('static int mg_static_reference_elf(', 'static __attribute__((unused)) int mg_static_reference_elf(')
source=source.replace('static int mg_workspace_notification(', 'static __attribute__((unused)) int mg_workspace_notification(')
# Two independently pinned roots share the exact same policy protocol. The
# source discriminator selects a root projection, never a different policy.
source=source.replace(r'\"type\":\"open\",', r'\"type\":\"%s\",')
source=source.replace('id,nr,flags,mode,hexpath,request->pid,address,how_address);',
    'gnu_policy_tmp?"openTmp":"open",id,nr,flags,mode,hexpath,request->pid,address,how_address);')
source=source.replace('static int mg_open_file(const char *relative,', 'static int mg_open_file(int root_fd,const char *relative,')
source=source.replace('SYS_openat2,mg_root,parent_path,', 'SYS_openat2,root_fd,parent_path,')
source=source.replace('mg_open_file(path,flags,mode,&decision)', 'mg_open_file(mg_root,path,flags,mode,&decision)')
(here/'gnu-managed-runner.c').write_text(source)
probe=(here/'gnu-project.c').read_text()
start=probe.index('#define ALLOW_SYSCALL')
end=probe.index('\nstatic void worker_check',start)
filter=probe[start:end].replace('notification_filter(void)','gnu_notification_filter(void)').replace('PROBE_AUDIT_ARCH','MG_ARCH')
filter=filter.replace('        ALLOW_SYSCALL(SYS_setsid),\n','').replace('        ALLOW_SYSCALL(SYS_setpgid),\n','')
# Namespace operations and every mode/path mutation are mediated by the native
# supervisor. Runtime metadata queries and reads stay kernel Landlock bounded.
for name in ('unlinkat','mkdirat','renameat','renameat2','linkat','symlinkat','unlink','rmdir','mkdir','rename','link','symlink'):
    filter=filter.replace(f'        ALLOW_SYSCALL(SYS_{name}),', f'        MG_ACQUIRE({name}),')
filter=filter.replace('        ALLOW_SYSCALL(SYS_execve),','        ALLOW_SYSCALL(SYS_execve),\n        ALLOW_SYSCALL(SYS_execveat),')
filter=filter.replace('        ALLOW_SYSCALL(SYS_ptrace),',
    '        /* PRoot child stacks a scope-only Landlock domain before guest code.\n'
    '         * These calls can only add restrictions to the inherited domain. */\n'
    '        ALLOW_SYSCALL(SYS_landlock_create_ruleset),\n'
    '        ALLOW_SYSCALL(SYS_landlock_restrict_self),\n'
    '        ALLOW_SYSCALL(SYS_ptrace),')
for syscall,arg in (('ptrace',1),('process_vm_readv',0),('process_vm_writev',0)):
    filter=filter.replace(f'        ALLOW_SYSCALL(SYS_{syscall}),', f'''        /* The immutable, single-threaded PRoot leader cannot be inspected or
         * modified by guests in this Landlock domain. PID is captured before
         * exec and remains owned/unreaped until descendant cleanup finishes. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_{syscall}, 0, 5),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[{arg}])),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, (uint32_t)getpid(), 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),''')
filter=filter.replace('SYS_ioctl, 0, 11)', 'SYS_ioctl, 0, 15)').replace('        ALLOW_SYSCALL(FIONBIO),',
    '        ALLOW_SYSCALL(FIONBIO),\n        /* glibc fopen uses FIOCLEX; both match already permitted F_SETFD. */\n        ALLOW_SYSCALL(FIOCLEX),\n        ALLOW_SYSCALL(FIONCLEX),')
(here/'gnu-managed-filter.h').write_text('/* Separate GNU syscall profile, frozen from the real Android GNU test. */\n'+filter)
(here/'managed-derivation.json').write_text(json.dumps({'baseSha256':hashlib.sha256(base.read_bytes()).hexdigest(),
    'gnuProbeSha256':hashlib.sha256((here/'gnu-project.c').read_bytes()).hexdigest(),
    'runnerSha256':hashlib.sha256((here/'gnu-managed-runner.c').read_bytes()).hexdigest()},indent=2)+'\n')
print('Prepared separate GNU lifecycle runner; original static runner unchanged.')
