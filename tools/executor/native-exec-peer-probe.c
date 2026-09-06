/* SPDX-License-Identifier: GPL-3.0-only
 * Fixed exec/peer isolation experiment. No shell, PRoot, account or model.
 * Reuse the earlier real-syscall fixture helpers without modifying that probe.
 */
#define main native_abc_reference_main
#include "native-abc-probe.c"
#undef main
#include <dirent.h>
#include <sys/mman.h>
#include <sys/ptrace.h>
#include <sys/uio.h>
#include <linux/capability.h>

#define LL_EXECUTE (1ULL << 0)
#define LL_READ_DIR (1ULL << 3)
#define PEER_MAGIC UINT32_C(0x45585037)
#define SECRET_SIZE 32
#define MAX_TRACKED 8
enum { READY = 1, ABC_DONE, VICTIM_READY, ALLOW_ACK, ATTACK_DONE };
enum { GO = 1, ALLOW, STOP };
static volatile unsigned char parent_secret[SECRET_SIZE];
static volatile unsigned long fork_marker;
static char victim_data[BUFFER_SIZE];
static pid_t tracked[MAX_TRACKED];

struct peer_attempt { int64_t result; int32_t error; int32_t length; char bytes[BUFFER_SIZE]; };
struct packet {
    uint32_t magic;
    int32_t kind, stage, error, policy, descriptors, dumpable, seccomp;
    int32_t pid, data_fd;
    uint64_t address;
    struct report abc;
    struct peer_attempt memory, trace, descriptor;
};
struct command { int32_t kind, pid; };
struct child { pid_t pid; int input, output; };

static int read_deadline(int fd, void *bytes, size_t size)
{
    int64_t started = monotonic_ms();
    if (started < 0) return -1;
    size_t received = 0;
    while (received < size) {
        int64_t now = monotonic_ms();
        if (now < 0 || now - started >= WORKER_TIMEOUT_MS) { errno = ETIMEDOUT; return -1; }
        struct pollfd event = {.fd = fd, .events = POLLIN};
        int ready = poll(&event, 1, (int)(WORKER_TIMEOUT_MS - (now - started)));
        if (ready < 0 && errno == EINTR) continue;
        if (ready <= 0) { if (!ready) errno = ETIMEDOUT; return -1; }
        ssize_t n = read(fd, (char *)bytes + received, size - received);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) { if (!n) errno = EPIPE; return -1; }
        received += (size_t)n;
    }
    return 0;
}

static int send_packet(struct packet *packet)
{
    packet->magic = PEER_MAGIC;
    return write_all(STDOUT_FILENO, packet, sizeof(*packet));
}

static int receive_packet(struct child child, int kind, struct packet *packet)
{
    memset(packet, 0, sizeof(*packet));
    if (read_deadline(child.output, packet, sizeof(*packet)) < 0) return -1;
    if (packet->magic != PEER_MAGIC || packet->kind != kind || packet->error) {
        fprintf(stderr, "worker protocol/setup failure: pid=%d kind=%d stage=%d error=%d\n",
                child.pid, packet->kind, packet->stage, packet->error);
        errno = EPROTO;
        return -1;
    }
    return 0;
}

static int send_command(struct child child, int kind, pid_t pid)
{
    struct command command = {.kind = kind, .pid = pid};
    return write_all(child.input, &command, sizeof(command));
}

static int unprivileged(void)
{
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct caps[2] = {{0}, {0}};
    if (geteuid() == 0 || syscall(SYS_capget, &header, caps) < 0) return 0;
    return !(caps[0].effective | caps[1].effective | caps[0].permitted | caps[1].permitted);
}

static int restrict_exec(int policy, const char *executable, const char *target, const char *control)
{
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) return -1;
    if (policy == -1) return 0; /* Explicit positive-control process only. */
    struct ll_ruleset attr = {.handled_access_fs = LL_FS_THROUGH_ABI5, .scoped = LL_SCOPE_SIGNAL};
    int fd = (int)syscall(SYS_landlock_create_ruleset, &attr, sizeof(attr), 0);
    if (fd < 0) return -1;
    uint64_t rights = policy == 0 ? LL_READ_FILE | LL_WRITE_FILE | LL_TRUNCATE : LL_READ_FILE;
    int result = 0;
    if (add_exact_file(fd, executable, LL_EXECUTE | LL_READ_FILE) < 0 ||
        add_exact_file(fd, "/proc/self/fd", LL_READ_DIR) < 0 ||
        add_exact_file(fd, control, LL_READ_FILE) < 0 ||
        (policy != 2 && add_exact_file(fd, target, rights) < 0) ||
        syscall(SYS_landlock_restrict_self, fd, 0) < 0) result = -1;
    int saved = errno;
    close(fd);
    errno = saved;
    return result;
}

static int inspect_exec_image(struct packet *packet)
{
    extern char **environ;
    if (fork_marker || (environ && environ[0]) || !unprivileged()) { errno = EINVAL; return -1; }
    for (size_t i = 0; i < sizeof(parent_secret); i++)
        if (parent_secret[i]) { errno = EINVAL; return -1; }
    packet->dumpable = prctl(PR_GET_DUMPABLE, 0, 0, 0, 0);
    packet->seccomp = prctl(PR_GET_SECCOMP, 0, 0, 0, 0);
    if (packet->dumpable != 1 || packet->seccomp != 0) { errno = ENOTSUP; return -1; }
    DIR *directory = opendir("/proc/self/fd");
    if (!directory) return -1;
    int scanner = dirfd(directory), count = 0, ok = 1;
    errno = 0;
    struct dirent *entry;
    while ((entry = readdir(directory))) {
        if (!strcmp(entry->d_name, ".") || !strcmp(entry->d_name, "..")) continue;
        char *end;
        long fd = strtol(entry->d_name, &end, 10);
        if (*end || (fd != 0 && fd != 1 && fd != scanner)) { ok = 0; break; }
        if (fd == 0 || fd == 1) count++;
    }
    if (errno) ok = 0;
    closedir(directory);
    struct stat input, output;
    if (fstat(0, &input) < 0 || fstat(1, &output) < 0 ||
        !S_ISFIFO(input.st_mode) || !S_ISFIFO(output.st_mode)) ok = 0;
    packet->descriptors = count;
    if (!ok || count != 2) { errno = EINVAL; return -1; }
    return 0;
}

/* Parent scans actual user-readable mappings while an exec'ed child is waiting.
 * Kernel-generated vvar/vsyscall mappings are identified explicitly; a failure
 * to read any other readable mapping is diagnostic failure, never an absence.
 */
static int scan_private_token(pid_t pid, int expect_present, uint64_t *scanned)
{
    char path[64];
    snprintf(path, sizeof(path), "/proc/%d/maps", pid);
    FILE *maps = fopen(path, "r");
    if (!maps) return -1;
    char line[PATH_MAX + 256];
    unsigned char buffer[4096 + SECRET_SIZE - 1], token[SECRET_SIZE];
    for (int i = 0; i < SECRET_SIZE; i++) token[i] = parent_secret[i];
    int found = 0, failure = 0;
    *scanned = 0;
    while (fgets(line, sizeof(line), maps)) {
        unsigned long long low, high;
        char permissions[5];
        if (sscanf(line, "%llx-%llx %4s", &low, &high, permissions) != 3) { failure = EPROTO; break; }
        if (permissions[0] != 'r') continue;
        if (strstr(line, "[vvar]\n") || strstr(line, "[vvar_vclock]\n") || strstr(line, "[vsyscall]\n")) continue;
        if (high < low || high - low > 128ULL * 1024 * 1024) { failure = EOVERFLOW; break; }
        size_t overlap = 0;
        for (uint64_t address = low; address < high;) {
            size_t size = high - address > 4096 ? 4096 : (size_t)(high - address);
            struct iovec local = {.iov_base = buffer + overlap, .iov_len = size};
            struct iovec remote = {.iov_base = (void *)(uintptr_t)address, .iov_len = size};
            ssize_t n = syscall(SYS_process_vm_readv, pid, &local, 1UL, &remote, 1UL, 0UL);
            if (n != (ssize_t)size) { failure = n < 0 ? errno : EIO; break; }
            if (memmem(buffer, overlap + size, token, sizeof(token))) found = 1;
            *scanned += size;
            address += size;
            size_t total = overlap + size;
            overlap = total < SECRET_SIZE - 1 ? total : SECRET_SIZE - 1;
            memmove(buffer, buffer + total - overlap, overlap);
        }
        if (failure) break;
    }
    if (ferror(maps)) failure = EIO;
    fclose(maps);
    memset(buffer, 0, sizeof(buffer));
    memset(token, 0, sizeof(token));
    if (failure || found != expect_present) {
        fprintf(stderr, "memory scan failed: pid=%d found=%d expected=%d errno=%d bytes=%llu\n",
                pid, found, expect_present, failure, (unsigned long long)*scanned);
        errno = failure ? failure : EIO;
        return -1;
    }
    return 0;
}

static struct child spawn_exec(const char *executable, const char *role, int policy,
                               struct fixture_file files[3], const struct packet *victim)
{
    struct child result = {.pid = -1, .input = -1, .output = -1};
    int input[2], output[2], slot;
    for (slot = 0; slot < MAX_TRACKED && tracked[slot]; slot++);
    if (slot == MAX_TRACKED) { errno = EBUSY; return result; }
    if (pipe2(input, O_CLOEXEC) < 0) return result;
    if (pipe2(output, O_CLOEXEC) < 0) { close(input[0]); close(input[1]); return result; }
    fflush(NULL);
    pid_t pid = fork();
    if (!pid) {
        struct packet failure = {.kind = READY, .stage = 1};
        if (dup2(input[0], 0) < 0 || dup2(output[1], 1) < 0) _exit(120);
        close(2);
        if (syscall(SYS_close_range, 3U, UINT_MAX, 0U) < 0) goto failed;
        failure.stage = 2;
        if (restrict_exec(policy, executable, files[0].path, files[1].path) < 0) goto failed;
        char policy_text[16], pid_text[32], fd_text[32], address_text[32];
        snprintf(policy_text, sizeof(policy_text), "%d", policy);
        snprintf(pid_text, sizeof(pid_text), "%d", victim ? victim->pid : 0);
        snprintf(fd_text, sizeof(fd_text), "%d", victim ? victim->data_fd : -1);
        snprintf(address_text, sizeof(address_text), "%llu", victim ? (unsigned long long)victim->address : 0ULL);
        char *arguments[] = {(char *)executable, "--worker", (char *)role, policy_text,
            files[0].path, files[1].path, files[2].path, pid_text, fd_text, address_text, NULL};
        char *environment[] = {NULL};
        failure.stage = 3;
        execve(executable, arguments, environment);
failed:
        failure.error = errno;
        (void)send_packet(&failure);
        _exit(121);
    }
    close(input[0]); close(output[1]);
    if (pid < 0) { close(input[1]); close(output[0]); return result; }
    tracked[slot] = pid;
    result.pid = pid; result.input = input[1]; result.output = output[0];
    return result;
}

static int reap_child(pid_t pid, int expect_success)
{
    int status = 0;
    int64_t started = monotonic_ms();
    while (started >= 0) {
        pid_t result = waitpid(pid, &status, WNOHANG);
        if (result == pid) {
            for (int i = 0; i < MAX_TRACKED; i++) if (tracked[i] == pid) tracked[i] = 0;
            if (expect_success && (!WIFEXITED(status) || WEXITSTATUS(status))) { errno = ECHILD; return -1; }
            return 0;
        }
        if (result < 0 && errno != EINTR) return -1;
        int64_t now = monotonic_ms();
        if (now < 0 || now - started >= REAP_TIMEOUT_MS) break;
        (void)poll(NULL, 0, 10);
    }
    errno = ETIMEDOUT;
    return -1;
}

static int finish_child(struct child *child)
{
    close(child->input); close(child->output);
    child->input = child->output = -1;
    return reap_child(child->pid, 1);
}

static int ready_child(struct child child)
{
    struct packet packet;
    uint64_t scanned = 0;
    if (child.pid < 0 || receive_packet(child, READY, &packet) < 0 ||
        packet.descriptors != 2 || packet.dumpable != 1 || packet.seccomp != 0 ||
        scan_private_token(child.pid, 0, &scanned) < 0) return -1;
    printf("exec pid=%d: only two protocol pipes; empty environment; fresh image; parent token absent from %llu user-readable bytes\n",
           child.pid, (unsigned long long)scanned);
    return 0;
}

static struct peer_attempt try_memory(pid_t victim, uintptr_t address)
{
    struct peer_attempt result = {0};
    struct iovec local = {.iov_base = result.bytes, .iov_len = BUFFER_SIZE};
    struct iovec remote = {.iov_base = (void *)address, .iov_len = BUFFER_SIZE};
    errno = 0;
    result.result = syscall(SYS_process_vm_readv, victim, &local, 1UL, &remote, 1UL, 0UL);
    result.error = result.result < 0 ? errno : 0;
    if (result.result > 0) result.length = (int32_t)result.result;
    return result;
}

static struct peer_attempt try_trace(pid_t victim, uintptr_t address)
{
    struct peer_attempt result = {0};
    errno = 0;
    result.result = ptrace(PTRACE_ATTACH, victim, NULL, NULL);
    if (result.result < 0) { result.error = errno; return result; }
    int status = 0, stopped = 0;
    int64_t started = monotonic_ms();
    while (started >= 0) {
        pid_t waited = waitpid(victim, &status, WNOHANG | __WALL);
        if (waited == victim) { stopped = WIFSTOPPED(status); break; }
        if (waited < 0 && errno != EINTR) break;
        int64_t now = monotonic_ms();
        if (now < 0 || now - started >= WORKER_TIMEOUT_MS) break;
        (void)poll(NULL, 0, 1);
    }
    if (!stopped) { result.error = ETIMEDOUT; return result; }
    errno = 0;
    long word = ptrace(PTRACE_PEEKDATA, victim, (void *)address, NULL);
    if (word == -1 && errno) result.error = errno;
    else { memcpy(result.bytes, &word, sizeof(word)); result.length = sizeof(word); }
    if (ptrace(PTRACE_DETACH, victim, NULL, NULL) < 0 && !result.error) result.error = errno;
    return result;
}

static struct peer_attempt try_descriptor(pid_t victim, int victim_fd)
{
    struct peer_attempt result = {0};
    int pidfd = (int)syscall(SYS_pidfd_open, victim, 0U);
    if (pidfd < 0) { result.result = -2; result.error = errno; return result; }
    errno = 0;
    int stolen = (int)syscall(SYS_pidfd_getfd, pidfd, victim_fd, 0U);
    result.result = stolen;
    result.error = stolen < 0 ? errno : 0;
    if (stolen >= 0) {
        ssize_t n = pread(stolen, result.bytes, sizeof(result.bytes), 0);
        if (n < 0) result.error = errno;
        else result.length = (int32_t)n;
        close(stolen);
    }
    close(pidfd);
    return result;
}

static int worker_main(char **argv)
{
    const char *role = argv[2], *target = argv[4], *control = argv[5], *excluded = argv[6];
    int policy = atoi(argv[3]);
    struct packet packet = {.kind = READY, .stage = 4, .policy = policy, .pid = getpid()};
    if (inspect_exec_image(&packet) < 0) goto failed;
    if (send_packet(&packet) < 0) return 120;
    struct command command;
    if (read_deadline(0, &command, sizeof(command)) < 0 || command.kind != GO) return 121;
    if (!strcmp(role, "abc")) {
        packet.kind = ABC_DONE;
        packet.abc.control_read = attempt_read(control);
        packet.abc.target_read = attempt_read(target);
        packet.abc.target_write = attempt_write(target, policy == 0 ? "exec policy A write\n" : violation_bytes);
        packet.abc.excluded_read = attempt_read(excluded);
        packet.abc.excluded_write = attempt_write(excluded, violation_bytes);
        return send_packet(&packet) < 0 ? 122 : 0;
    }
    if (!strcmp(role, "victim")) {
        packet.kind = VICTIM_READY;
        packet.abc.target_read = attempt_read(target);
        packet.data_fd = open(target, O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
        if (packet.data_fd < 0) goto failed;
        ssize_t size = pread(packet.data_fd, victim_data, sizeof(victim_data), 0);
        if (size < 0) goto failed;
        packet.address = (uintptr_t)victim_data;
        if (send_packet(&packet) < 0) return 123;
        while (read_deadline(0, &command, sizeof(command)) == 0) {
            if (command.kind == STOP) { close(packet.data_fd); return 0; }
            if (command.kind != ALLOW || command.pid <= 0) return 124;
            packet.kind = ALLOW_ACK;
            /* Exception only for this disposable target and exact live test PID.
             * No PR_SET_PTRACER_ANY, global Yama change, or capability elevation.
             */
            if (prctl(PR_SET_PTRACER, command.pid, 0, 0, 0) < 0) goto failed;
            if (send_packet(&packet) < 0) return 125;
        }
        return 126;
    }
    if (!strcmp(role, "attacker")) {
        packet.kind = ATTACK_DONE;
        pid_t victim = (pid_t)strtol(argv[7], NULL, 10);
        int victim_fd = atoi(argv[8]);
        uintptr_t address = (uintptr_t)strtoull(argv[9], NULL, 10);
        packet.abc.control_read = attempt_read(control);
        packet.abc.target_read = attempt_read(target);
        packet.memory = try_memory(victim, address);
        packet.trace = try_trace(victim, address);
        packet.descriptor = try_descriptor(victim, victim_fd);
        return send_packet(&packet) < 0 ? 127 : 0;
    }
    return 128;
failed:
    packet.error = errno ? errno : EINVAL;
    (void)send_packet(&packet);
    return 129;
}

static int peer_denied(struct peer_attempt attempt)
{
    return attempt.result == -1 && attempt.length == 0 &&
        (attempt.error == EPERM || attempt.error == EACCES);
}

int main(int argc, char **argv)
{
    if (argc == 10 && !strcmp(argv[1], "--worker")) return worker_main(argv);
    if (argc != 2 || argv[1][0] != '/') {
        fprintf(stderr, "Usage: %s /absolute/disposable-fixture-parent (non-root, no capabilities)\n", argv[0]); return 2;
    }
    signal(SIGPIPE, SIG_IGN);
    int abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0, LL_VERSION);
    if (abi < 6 || !unprivileged()) {
        fprintf(stderr, "FAIL: requires Landlock ABI >= 6 and non-root without effective/permitted capabilities; abi=%d uid=%d\n", abi, geteuid()); return 1;
    }
    char executable[PATH_MAX], root[PATH_MAX], location[PATH_MAX];
    if (!realpath(argv[0], executable) || !realpath(argv[1], root)) { perror("realpath"); return 1; }
    int length = snprintf(location, sizeof(location), "%s/foldgpt-exec-peer-XXXXXX", root);
    if (length < 0 || (size_t)length >= sizeof(location) || !mkdtemp(location)) { perror("mkdtemp"); return 1; }
    int directory = open(location, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    struct fixture_file files[3] = {
        {.name = "value.txt", .initial = "initial target bytes\n"},
        {.name = "permitted-control.txt", .initial = control_bytes},
        {.name = "excluded-sibling.txt", .initial = excluded_bytes},
    };
    int result = 1, secret_fd = -1;
    struct child live = {.pid = -1, .input = -1, .output = -1};
    struct child victim = live;
    if (directory < 0) goto cleanup;
    unsigned char random[SECRET_SIZE];
    if (syscall(SYS_getrandom, random, sizeof(random), 0) != sizeof(random)) goto cleanup;
    for (int i = 0; i < SECRET_SIZE; i++) parent_secret[i] = random[i];
    fork_marker = 0x61726337;
    secret_fd = (int)syscall(SYS_memfd_create, "foldgpt-parent-private-fixture", 0U);
    if (secret_fd < 0 || write_all(secret_fd, random, sizeof(random)) < 0 ||
        setenv("FOLDGPT_EXEC_PARENT_ONLY", "must not survive exec", 1) < 0) goto cleanup;
    /* The descriptor intentionally lacks CLOEXEC. close_range must remove it. */
    uint64_t scanned;
    if (scan_private_token(getpid(), 1, &scanned) < 0) goto cleanup;
    printf("positive memory scanner control: parent token found; ABI=%d uid=%d; no effective/permitted capabilities\n", abi, geteuid());
    for (int i = 0; i < 3; i++) {
        length = snprintf(files[i].path, sizeof(files[i].path), "%s/%s", location, files[i].name);
        if (length < 0 || (size_t)length >= sizeof(files[i].path)) goto cleanup;
        int fd = openat(directory, files[i].name, O_CREAT | O_EXCL | O_WRONLY | O_NOFOLLOW | O_CLOEXEC, 0600);
        if (fd < 0) goto cleanup;
        files[i].created = 1;
        int ok = write_all(fd, files[i].initial, strlen(files[i].initial)) == 0 && fsync(fd) == 0 && fstat(fd, &files[i].identity) == 0;
        close(fd);
        if (!ok) goto cleanup;
    }
    const int policies[] = {0, 1, 2, 0};
    const char *labels[] = {"A1", "B", "C", "A2"};
    const char *expected = files[0].initial;
    for (int i = 0; i < 4; i++) {
        struct packet packet;
        int policy = policies[i];
        live = spawn_exec(executable, "abc", policy, files, NULL);
        if (ready_child(live) < 0 || send_command(live, GO, 0) < 0 || receive_packet(live, ABC_DONE, &packet) < 0 || finish_child(&live) < 0) goto cleanup;
        int ok = read_matches(packet.abc.control_read, control_bytes) && denied(packet.abc.excluded_read) && denied(packet.abc.excluded_write);
        ok = ok && (policy == 2 ? denied(packet.abc.target_read) : read_matches(packet.abc.target_read, expected));
        if (policy == 0) {
            expected = "exec policy A write\n";
            ok = ok && packet.abc.target_write.opened && !packet.abc.target_write.error && packet.abc.target_write.transferred == (int32_t)strlen(expected);
        } else ok = ok && denied(packet.abc.target_write);
        for (int j = 0; j < 3; j++) if (verify_file(directory, &files[j], j ? files[j].initial : expected) < 0) ok = 0;
        printf("exec %s: read_errno=%d write_errno=%d parent bytes/inode and controls=%s\n", labels[i], packet.abc.target_read.error, packet.abc.target_write.error, ok ? "PASS" : "FAIL");
        if (!ok) goto cleanup;
    }
    struct packet target;
    victim = spawn_exec(executable, "victim", 0, files, NULL);
    if (ready_child(victim) < 0 || send_command(victim, GO, 0) < 0 || receive_packet(victim, VICTIM_READY, &target) < 0 ||
        !read_matches(target.abc.target_read, expected) || target.pid != victim.pid || target.data_fd < 2 || !target.address) goto cleanup;
    for (int policy = -1; policy <= 2; policy += 3) {
        struct packet packet, ack;
        live = spawn_exec(executable, "attacker", policy, files, &target);
        if (ready_child(live) < 0 || send_command(victim, ALLOW, live.pid) < 0 || receive_packet(victim, ALLOW_ACK, &ack) < 0 ||
            send_command(live, GO, 0) < 0 || receive_packet(live, ATTACK_DONE, &packet) < 0 || finish_child(&live) < 0) goto cleanup;
        int ok = read_matches(packet.abc.control_read, control_bytes);
        if (policy == -1) {
            ok = ok && read_matches(packet.abc.target_read, expected) &&
                packet.memory.result == BUFFER_SIZE && !packet.memory.error && !memcmp(packet.memory.bytes, expected, strlen(expected)) &&
                packet.trace.result == 0 && !packet.trace.error && packet.trace.length == sizeof(long) && !memcmp(packet.trace.bytes, expected, sizeof(long)) &&
                packet.descriptor.result >= 0 && !packet.descriptor.error && packet.descriptor.length == (int32_t)strlen(expected) && !memcmp(packet.descriptor.bytes, expected, strlen(expected));
        } else ok = ok && denied(packet.abc.target_read) && peer_denied(packet.memory) && peer_denied(packet.trace) && peer_denied(packet.descriptor);
        printf("concurrent %s -> A: process_vm_readv=%lld/%d ptrace=%lld/%d pidfd_getfd=%lld/%d result=%s\n",
               policy == -1 ? "unconfined positive control" : "C", (long long)packet.memory.result, packet.memory.error,
               (long long)packet.trace.result, packet.trace.error, (long long)packet.descriptor.result, packet.descriptor.error, ok ? "PASS" : "FAIL");
        if (!ok) {
            if (policy == -1) fprintf(stderr, "INCONCLUSIVE: positive peer control failed; no subsequent denial can establish our Landlock boundary\n");
            goto cleanup;
        }
        for (int j = 0; j < 3; j++) if (verify_file(directory, &files[j], j ? files[j].initial : expected) < 0) goto cleanup;
    }
    if (send_command(victim, STOP, 0) < 0 || finish_child(&victim) < 0) goto cleanup;
    result = 0;
cleanup:
    if (result) perror("exec/peer diagnostic");
    if (live.input >= 0) close(live.input);
    if (live.output >= 0) close(live.output);
    if (victim.input >= 0) close(victim.input);
    if (victim.output >= 0) close(victim.output);
    for (int i = 0; i < MAX_TRACKED; i++) if (tracked[i]) {
        pid_t pid = tracked[i];
        (void)kill(pid, SIGKILL);
        if (reap_child(pid, 0) < 0) { fprintf(stderr, "FAIL: cleanup/reap pid=%d errno=%d\n", pid, errno); result = 1; }
    }
    if (secret_fd >= 0) close(secret_fd);
    for (int i = 0; i < SECRET_SIZE; i++) parent_secret[i] = 0;
    if (directory >= 0) {
        for (int i = 0; i < 3; i++) if (files[i].created && unlinkat(directory, files[i].name, 0) < 0) result = 1;
        close(directory);
    }
    if (rmdir(location) < 0) result = 1;
    puts(result ? "FAIL: native exec/peer diagnostic" : "PASS: real exec A/B/C/A, parent memory/FD separation, and independently controlled concurrent peer denial; no Android execution");
    return result;
}
