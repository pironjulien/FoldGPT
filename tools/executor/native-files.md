# Native filesystem RPC integration

`NativeFilesBackend` connects `fs/readFile` and `fs/writeFile` from the audited
Codex exec-server protocol to actual native file operations. It retains each
request's complete portable policy, resolves the supported policy semantics,
and checks access before starting `native-files`. It does not flatten a deny
rule or protected metadata into a writable-root grant.

The supervisor configures one guest workspace mapping and owns its physical
directory FD. Requests cannot select a host path, root FD or a wider mapping.
The helper receives that FD through explicit descriptor inheritance; it resolves
relative paths with openat2 BENEATH/NO_SYMLINKS/NO_XDEV. Existing files are pinned
with O_PATH, checked for regular type, owner and one link, then reopened by the
helper's own /proc/self/fd entry. New files use exclusive creation. The helper
never executes caller code and is only the native half of this trusted backend;
calling the helper directly is not policy authorization or a process sandbox.

Writes verify the complete declared input length before opening the target,
then preserve the existing inode and propagate truncate/write/fsync failures.
They are not atomic replacements or rollback transactions. Cancellation after
mutation starts can leave that mutation; the backend terminates and waits for
the helper before releasing its workspace. Read/write data is bounded to 16 MiB.

Admission currently requires an exclusively owned ordinary workspace. An
advisory lease serializes cooperating backend sessions. Symlinks, hardlinks,
special files and gitdir worktrees are rejected before an operation; aliases
are not silently followed under a weaker policy. Nested existing .git/.agents
directories are protected, while explicit narrower write exceptions retain
their meaning. Scans are bounded to 100,000 entries and depth 64. An unconfined
concurrent writer is outside this contract: a scan/advisory lock alone would
not provide exclusion against it. Command workers therefore cannot be admitted
into this workspace until their native mutation boundary is connected.

This backend advertises no process, TTY, network, filesystem streaming or
session-resumption capability. The default CLI server still uses the refusing
backend; the real file backend is injected in its integration tests. The guest
bridge and native supervisor transport are not yet an Android product service.

Run `bash tools/executor/native-files-build.sh` under Linux/WSL. It builds the
host helper and two Android debug executables, records hashes, and runs 26 real
transport/native tests as a nonroot user. Tests include A/B/C/A decisions on one
inode, unchanged denied bytes, explicit metadata exceptions, aliases, malformed
policies and incomplete write input.

On 2026-09-06, `NativeRunnerProbeService` also ran the same native file helper
under Android's actual Zygote UID and inherited seccomp filter. File creation,
read, same-inode overwrite, symlink/escape refusal and incomplete-write refusal
passed. This establishes native file semantics on Android, not the complete
Python policy RPC path there or arbitrary-command confinement.

Separately, `verify_official_environment.py` connected the untouched official
Codex 0.153.4 executable (SHA-256
`4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6`)
to `exec_server.py` on the Fold. The official app-server returned matching
environment metadata and `ready`; it then exited normally. The test used a
new temporary CODEX_HOME with no account and sent only initialize,
environment/info and environment/status. It made no model request and proves
transport compatibility only.
