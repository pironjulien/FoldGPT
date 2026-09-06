# Native filesystem RPC integration

`NativeFilesBackend` connects `fs/readFile`, `fs/writeFile`,
`fs/createDirectory`, `fs/getMetadata` and `fs/canonicalize` from the audited
Codex exec-server protocol to actual native
file operations. It retains each
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

Directory creation follows the reviewed upstream default: absent or null
`recursive` means true. Recursive creation succeeds for an existing admitted
directory without replacing its inode; nonrecursive creation reports failure
if the target already exists or its parent is absent. The workspace root can
be the existing recursive target. Every request still requires a writable
target and the complete supported sandbox context. `followSymlinks` is preserved
and type-checked, but a workspace containing any symlink remains inadmissible
under either option value.

Before starting the helper, the backend inventories the exclusively owned
workspace and authorizes **every missing directory component**, including all
missing ancestors. A writable leaf grant never grants implicit creation rights
to a read-only or denied ancestor. An existing ancestor requires no new creation
right, so an explicit child write can override its broader deny. Existing
metadata protection and explicit exceptions are checked for each creation.
The complete plan is rejected before mutation if it would exceed 64 directory
levels or the 100,000-entry workspace admission bound.

The additional native invocations are:

```text
native-files mkdir  ROOT_FD RELATIVE_PATH MISSING_COUNT PARENT_DEVICE PARENT_INODE
native-files mkdirs ROOT_FD RELATIVE_PATH MISSING_COUNT PARENT_DEVICE PARENT_INODE
```

`mkdir` is nonrecursive; `mkdirs` is recursive. `MISSING_COUNT` is the exact
number of trailing components authorized for creation. The last two fields
identify the nearest existing directory from the trusted inventory. They are
consistency checks, not authentication or standalone policy authorization.
Directory, metadata and canonicalization operations accept `.` to refer to the
already pinned workspace root. Directory stdin must reach EOF with no body. All numeric fields,
component lengths and depths are checked before any mutation.

The helper opens the existing prefix with openat2
BENEATH/NO_SYMLINKS/NO_XDEV, verifies its actual device and inode and checks that
the first planned component is still missing. Unexpected existing objects,
missing prefixes and replacement inodes fail; they are never adopted through
a retry. It creates each component by `mkdirat` relative to a held directory
FD, opens the child without following links, checks owner/type/exact 0700 mode,
and synchronizes child and parent before proceeding. A syscall, cancellation
or synchronization failure can leave already created directories: this is a
bounded filesystem operation, not an atomic recursive transaction. The existing
exclusion of unconfined outside writers remains necessary throughout the call.

Metadata and canonicalization require the effective **read** permission on
the requested object. A deny rule is checked before lookup and is never
reported as NotFound; a genuinely missing admitted path returns the reviewed
`-32004` error. Both operations can address the existing workspace root.
An explicit readable child can override a denied existing parent. The same
complete workspace admission and per-session lease apply; these calls do not
make arbitrary outside paths or concurrent unconfined writers admissible.

Their native invocations are:

```text
native-files metadata          ROOT_FD RELATIVE_PATH 0
native-files metadata-nofollow ROOT_FD RELATIVE_PATH 0
native-files canonicalize      ROOT_FD RELATIVE_PATH 0
```

These operations also accept `.` for the pinned workspace root. The final
argument must be exactly `0`, and stdin must reach EOF with no body. Each
operation resolves the actual object using openat2 and O_PATH, then checks its
type, owner and regular-file link count. A FIFO or device is never activated
to discover its type. A symlink, hardlink, special file, escape or absent
object cannot produce successful metadata or canonicalization.

Metadata comes from `statx(AT_EMPTY_PATH)` on that pinned descriptor, including
the real size, kind, modification time and birth time when the filesystem
provides one. Missing required kernel fields or a refused statx syscall are
errors. The response must contain exactly the six official fields with their
proper boolean, u64 and i64 types; malformed or duplicate native fields fail
closed. No metadata cache spans requests or changes in policy.

The timestamp conversions match the reviewed upstream implementation at
`rust-v0.153.4`, commit `042fb41b7c813ac7999105e886b2b7aa715b5081`:
`exec-server/src/local_file_system.rs:1148,1258` and
`exec-server/src/no_follow/unix.rs:195,250`. Missing birth time is represented
as zero by upstream. With default/true `followSymlinks`, pre-epoch or
unrepresentable timestamps likewise become zero; explicit false uses Linux's
signed saturating conversion. These are protocol semantics, not invented
success values. All option values still reject workspace aliases under the
current admission contract.

Canonicalization emits no native path or metadata. Only after the native
lookup succeeds does the backend return the normalized guest URI corresponding
to the resolved object. This is valid because the admitted mapping has no
symlinks, hardlinks or dot components and excludes namespace mutation by
outside writers. An absent path is never accepted by lexical normalization
alone. `followSymlinks` is not a canonicalization parameter in the reviewed
wire protocol, and is rejected rather than ignored.

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
host helper and two Android debug executables, records hashes, and runs 48 real
transport/native tests as a nonroot user. Tests include A/B/C/A decisions on one
inode, unchanged denied bytes, explicit metadata exceptions, aliases, malformed
policies and incomplete write input. Ten directory regressions additionally
cover recursive/nonrecursive behavior, Unicode paths, effective ancestor rights,
metadata exceptions, depth bounds, invalid native plans and a real parent
replacement. A separate server subprocess receives the actual stdio handshake,
creates directories, writes/reads real bytes and rejects a denied intermediate
component without creating its permitted ancestor. EOF releases the real lease.

Seven additional tests cover real metadata against independent filesystem
observations (including birth time from coreutils stat), updates to the same
inode, pre-epoch timestamp option semantics, per-request read/deny decisions,
normalized Unicode/escaped guest URIs, missing paths, invalid input and
independent native refusal of symlinks, hardlinks and FIFOs. The same real
stdio server test now also obtains metadata, canonicalizes an existing object,
rejects both operations under a deny policy, and checks missing-path behavior.
No synthetic native success backend is used.

The 6 September 2026 metadata/canonicalization increment passed all 48 tests
under WSL UID `nobody` with no skips. Evidence is in
`downloads/native-files/foldgpt-native-files-build-ykxHtGxq/tests.txt` and
`SHA256SUMS`. The tested Linux helper SHA-256 is
`04b600c5ad5b4e7caacaec9cbf88ec067dfc210d251a68b5fb67a6bdd81e040d`;
the compiled Android helper SHA-256 is
`975142224df084eee72f14a25d15819ee5f67cca23ae45611ee92b8e4c08a8e1`.
The subsequent Android fixture below establishes native statx availability;
these operations have not yet been used through the full RPC path by a real
model request on Android.

The 6 September 2026 directory increment passed all 41 tests under WSL UID
`nobody` with no skips. Evidence is in
`downloads/native-files/foldgpt-native-files-build-QtGKBx57/tests.txt` and its
`SHA256SUMS`. The tested Linux helper SHA-256 is
`0e8c385d7f43debf6f5c1d190ed357142385986e1ef5a62ecdeeb70f78249714`;
the compiled Android helper SHA-256 is
`62d91fec93464e4301e43657d2902ec1a2c114209cf8da7f1d4ab71f2da234c9`.
The subsequent Android fixture below also exercises directory operations.
Remaining filesystem methods, the Android broker transport and
managed arbitrary processes remain unimplemented integration requirements.

On 2026-09-06, `NativeRunnerProbeService` also ran the same native file helper
under Android's actual Zygote UID and inherited seccomp filter. File creation,
read, same-inode overwrite, symlink/escape refusal and incomplete-write refusal
passed. This establishes native file semantics on Android, not the complete
Python policy RPC path there or arbitrary-command confinement.

The expanded fixture then passed under Zygote UID 10412, inherited seccomp 2,
in APK `2e3a7def075f572d23b57c8a4dd97315351cdacaf3cd45dce5034b8348fbd943`.
It compares metadata kind, size and modification time with independent
`fstatat`, verifies existing/missing/alias canonicalization, and checks actual
recursive and single directories and mode 0700. Rejected nonrecursive and
stale-parent plans leave no partial ancestor. Birth time is only bounded in
this Android fixture; independent birth-time comparison remains host evidence.
The fixture SHA-256 is
`af211a7e4c3d1a1c501b01041007c01a74fe257b4f9c9f2ae9dc6be3850aab27`.
Its final host build reran all 48 tests successfully in
`downloads/native-files/foldgpt-native-files-build-8ybJWRUv`; actual Android logs
are in `downloads/native-files/android-20260906-metadata/`. The separate limited
native runner also repeated its eight checks successfully in that APK.

Separately, `verify_official_environment.py` connected the untouched official
Codex 0.153.4 executable (SHA-256
`4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6`)
to `exec_server.py` on the Fold. The official app-server returned matching
environment metadata and `ready`; it then exited normally. The test used a
new temporary CODEX_HOME with no account and sent only initialize,
environment/info and environment/status. It made no model request and proves
transport compatibility only.
