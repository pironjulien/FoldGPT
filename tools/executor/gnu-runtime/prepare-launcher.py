"""Reproduce the diagnostic derivative from its explicitly hash-pinned base."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1] / 'probe-landlock-codex.c'
source = BASE.read_text(encoding='utf-8')
base_hash = hashlib.sha256(BASE.read_bytes()).hexdigest()
if base_hash != '6f9ea3840a51a0e3ecf8487cd08e324eea139bcf686733634c6eca10cc202d73':
    raise RuntimeError('Reviewed native diagnostic base changed; re-review the derivative before regeneration')

def replace(old, new):
    global source
    if source.count(old) != 1:
        raise RuntimeError(f'Expected one exact source region: {old[:80]}')
    source = source.replace(old, new)

start = source.index('/* FIXED OFFLINE OFFICIAL CODEX EXPERIMENT:')
end = source.index('\n#if defined(__aarch64__)', start)
source = source[:start] + '''/* Fixed GNU Python project diagnostic, derived from probe-landlock-codex.c.
 * The native supervisor applies Landlock BEFORE native strict PRoot, including
 * a default-deny file read policy. Only runtime program trees and the private
 * experiment paths are admitted. No global root/proc/home read grant exists.
 * Native USER_NOTIF owns the listener and brokers scratch writes/mode changes.
 * PRoot translates GNU ABI/path calls; it is never the isolation boundary.
 * This fixed test is not a production command executor or managed-policy engine.
 * Android: APP_DATA_DIR APK_NATIVE_DIR. Linux: PARENT PROOT ROOTFS.
 */
''' + source[end:]
replace('#include "probe-codex-offline.generated.h"', '#include "gnu-project.generated.h"')
replace('#include <linux/seccomp.h>', '#include <linux/seccomp.h>\n#include <linux/sched.h>')
replace('''        ALLOW_SYSCALL(SYS_clone),
#ifdef SYS_clone3
        ALLOW_SYSCALL(SYS_clone3),
#endif''', '''        /* Ordinary fork/threads only. No namespace flags, CLONE_PARENT,
         * CLONE_PTRACE or CLONE_UNTRACED. clone3's pointer flags cannot be
         * inspected by classic BPF: return ENOSYS for libc's native clone
         * fallback, as in the existing native-runner profile. */
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_clone, 0, 9),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0]) + 4),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 0, 6),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP | BPF_JSET | BPF_K,
            (uint32_t)~(CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD |
            CLONE_SYSVSEM | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID |
            CLONE_CHILD_SETTID | CLONE_VFORK | 0xff), 4, 0),
        BPF_STMT(BPF_ALU | BPF_AND | BPF_K, 0xff),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, 0, 1, 0),
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SIGCHLD, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | EPERM),
        BPF_STMT(BPF_LD | BPF_W | BPF_ABS, offsetof(struct seccomp_data, nr)),
#ifdef SYS_clone3
        BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, SYS_clone3, 0, 1),
        BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ERRNO | ENOSYS),
#endif''')
start = source.index('static void landlock_read_only(void) {')
end = source.index('\n#define ALLOW_SYSCALL', start)
source = source[:start] + '''static void grant_path(int ruleset, const char *path, uint64_t rights, int optional) {
    int fd = open(path, O_PATH | O_CLOEXEC);
    if (optional && fd < 0 && errno == ENOENT) return;
    require(fd >= 0, "open explicit Landlock runtime grant");
    struct stat info;
    require(fstat(fd, &info) == 0, "inspect explicit Landlock grant");
    if (!S_ISDIR(info.st_mode)) rights &= ~(LANDLOCK_ACCESS_FS_READ_DIR);
    struct landlock_path_beneath_attr rule = {.allowed_access = rights, .parent_fd = fd};
    require(syscall(SYS_landlock_add_rule, ruleset, LANDLOCK_RULE_PATH_BENEATH, &rule, 0) == 0,
            "install explicit Landlock grant");
    close(fd);
}

static void landlock_read_only(void) {
    const uint64_t reads = LANDLOCK_ACCESS_FS_EXECUTE | LANDLOCK_ACCESS_FS_READ_FILE
                         | LANDLOCK_ACCESS_FS_READ_DIR;
    const uint64_t writes = LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR
        | LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR
        | LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG
        | LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO
        | LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM
        | LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE | LANDLOCK_ACCESS_FS_IOCTL_DEV;
    struct probe_landlock_ruleset attributes = {
        .handled_access_fs = reads | writes, .scoped = LANDLOCK_SCOPE_SIGNAL | 1ULL};
    int ruleset = (int)syscall(SYS_landlock_create_ruleset, &attributes, sizeof(attributes), 0);
    require(ruleset >= 0, "create default-deny file read/write Landlock ruleset");
    /* Program/runtime trees only. In particular no /, /proc, /home, /data or
     * entire guest-root grant. This profile exposes ordinary path metadata:
     * Landlock does not claim stat/readlink confidentiality. */
    const char *runtime[] = {"usr", "lib", "lib64", "bin"};
    for (unsigned i = 0; i < sizeof(runtime)/sizeof(runtime[0]); i++) {
        char path[PATH_MAX];
        int length = snprintf(path, sizeof(path), "%s/%s", rootfs_path, runtime[i]);
        require(length > 0 && length < PATH_MAX, "runtime grant path length");
        grant_path(ruleset, path, reads, 1);
    }
#ifdef __ANDROID__
    const char *native[] = {"/apex/com.android.runtime/bin", "/apex/com.android.runtime/lib64",
        "/apex/com.android.i18n/lib64", "/apex/com.android.art/lib64",
        "/apex/com.android.tethering/lib64",
        "/system/bin", "/system/lib64"};
    for (unsigned i = 0; i < sizeof(native)/sizeof(native[0]); i++)
        grant_path(ruleset, native[i], reads, 0);
#else
    grant_path(ruleset, "/lib", reads, 0);
    grant_path(ruleset, "/lib64", reads, 1);
#endif
    /* Each program is pinned by pathname in this fixed immutable input set. */
    grant_path(ruleset, proot_path, LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE, 0);
    grant_path(ruleset, loader_path, LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE, 0);
    grant_path(ruleset, loader32_path, LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_EXECUTE, 0);
#ifdef __ANDROID__
    char talloc[PATH_MAX];
    const char *last = strrchr(proot_path, '/');
    int length = snprintf(talloc, sizeof(talloc), "%.*s/libtalloc.so", (int)(last-proot_path), proot_path);
    require(length > 0 && length < PATH_MAX, "talloc grant path length");
    grant_path(ruleset, talloc, LANDLOCK_ACCESS_FS_READ_FILE, 0);
    length = snprintf(talloc, sizeof(talloc), "%.*s/libandroid-shmem.so", (int)(last-proot_path), proot_path);
    require(length > 0 && length < PATH_MAX, "shared memory runtime grant path length");
    grant_path(ruleset, talloc, LANDLOCK_ACCESS_FS_READ_FILE, 0);
    grant_path(ruleset, "/linkerconfig/ld.config.txt", LANDLOCK_ACCESS_FS_READ_FILE, 0);
#endif
    grant_path(ruleset, workspace_path, reads, 0);
    grant_path(ruleset, scratch_path, reads | writes, 0);
    grant_path(ruleset, "/dev/null", LANDLOCK_ACCESS_FS_READ_FILE, 0);
    grant_path(ruleset, "/dev/urandom", LANDLOCK_ACCESS_FS_READ_FILE, 0);
    require(prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) == 0, "set no_new_privs");
    require(syscall(SYS_landlock_restrict_self, ruleset, 0) == 0, "enforce default-deny Landlock");
    close(ruleset);
}
''' + source[end:]
replace('"libproot.so"', '"libfoldgpt-strict-proot.so"')
replace('"-r", rootfs_path, "-w", "/foldgpt-fixture",', '"--strict-sandbox", "-r", rootfs_path, "-w", "/foldgpt-fixture",')
replace('''#ifdef __ANDROID__
          "--kill-on-exit",
#endif''', '          "--kill-on-exit",')
replace('codex_offline_script, (char *)NULL', 'gnu_project_script, (char *)NULL')
replace('''    worker_check("outside_mode_fd_open", mode_fd >= 0, errno);
    mode_result = syscall(SYS_fchmod, mode_fd, 0777);
    worker_check("outside_fchmod_denied", mode_result < 0 && errno == EPERM, errno);
    close(mode_fd);''', '''    worker_check("outside_read_denied", mode_fd < 0 && errno == EACCES, errno);
    /* No outside FD exists: the denied read must not be replaced by a fake FD. */''')
replace('''    verify_file(workspace, "normal.txt", appended_marker);
    verify_file(workspace, "src/normal.txt", marker);
    verify_file(workspace, ".gitignore", marker);''', '''    verify_file(scratch_directory, "project/dist/result.txt", "native GNU project: 42\\n");''')
replace('''    require(broker_grants == 4 && descendant_workspace_grants == 4
            && broker_denials - unsupported_denials >= 11,
            "expected official Codex fixture grants and path denial lower bound");''', '''    require(scratch_grants > 0 && scratch_mode_changes > 0,
            "actual GNU project and native scratch operations observed");''')
replace('scope=fixed offline official Codex command/exec via PRoot; not complete Codex policy',
        'scope=real Bash/GNU Python project under default-deny Landlock and seccomp; no Desktop or managed-policy routing')
source = source.replace('foldgpt-codex-offline-XXXXXX', 'foldgpt-gnu-project-XXXXXX')
replace('''    setbuf(stdout, NULL);''', '''    setbuf(stdout, NULL);
    require(getuid() != 0 && getuid() == geteuid() && getgid() == getegid(),
            "ordinary nonroot identity required");''')
# Constants now unused by the project's independent verification.
replace('static const char appended_marker[] = "FoldGPT native shell write\\nFoldGPT appended\\n";\n', '')
(HERE / 'gnu-project.c').write_text(source, encoding='utf-8', newline='\n')
script = (HERE / 'project.py').read_text(encoding='utf-8')
header = 'static const char gnu_project_script[] =\n' + '\n'.join(json.dumps(line, ensure_ascii=True) for line in script.splitlines(keepends=True)) + ';\n'
(HERE / 'gnu-project.generated.h').write_text(header, encoding='ascii', newline='\n')
(HERE / 'derivation.json').write_text(json.dumps({'base':BASE.relative_to(HERE.parents[2]).as_posix(), 'baseSha256':base_hash,
    'launcherSha256':hashlib.sha256((HERE/'gnu-project.c').read_bytes()).hexdigest(),
    'projectSha256':hashlib.sha256((HERE/'project.py').read_bytes()).hexdigest()}, indent=2)+'\n', encoding='utf-8', newline='\n')
print('Prepared fixed GNU runtime launcher and embedded project.')
