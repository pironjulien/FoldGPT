# Native session-bound file streaming

`NativeFileStreamsBackend` adds the official `fs/open`, `fs/readBlock` and
`fs/close` RPCs to the nine methods of `NativeFilesBackend`. File acquisition and
block reads execute in a trusted native helper. The supervisor holds actual
readonly descriptors between requests, including for files above the existing
16 MiB whole-file limit. This addition does not implement process execution or
connect a production Codex client.

## Reviewed contract

The source reference is official Codex tag `rust-v0.153.4`, commit
`042fb41b7c813ac7999105e886b2b7aa715b5081`:

- `codex-rs/exec-server-protocol/src/protocol.rs`: `FsOpenParams`,
  `FsOpenResponse`, `FsReadBlockParams`, `FsReadBlockResponse`, `FsCloseParams`,
  and the transparent base64-string `ByteChunk`.
- `codex-rs/exec-server/src/file_read.rs`: connection-local handle map, 128 open
  handles, duplicate rejection, idempotent close, read-error cleanup and EOF.
- `codex-rs/file-system/src/lib.rs`: `FILE_READ_CHUNK_SIZE = 1024 * 1024`.
- `codex-rs/exec-server/src/server/file_system_handler.rs`: maximum handle ID
  length of 32 UTF-8 bytes and native I/O error mapping.

| Method | Parameters | Successful result |
| --- | --- | --- |
| `fs/open` | `handleId`, absolute guest file URI `path`, full admitted `sandbox` | `{"handleId":"client-id"}` |
| `fs/readBlock` | `handleId`, unsigned 64-bit `offset`, integer `len` from 1 through 1,048,576 | `{"chunk":"BASE64","eof":false}` |
| `fs/close` | `handleId` | `{}` |

The official wire shape permits an absent sandbox, but this backend requires
its complete managed policy before any acquisition. Unsupported policy fields,
aliases and file kinds fail admission. Handle lifecycle requests cannot supply
a replacement policy. Empty IDs are valid upstream; the length limit is bytes,
not Unicode code points. An unknown read returns NotFound (`-32004`), while an
unknown valid close succeeds. A duplicate open never replaces the old handle.

`eof` means fewer bytes were read than requested. A full final block returns
`false`; a subsequent block at the end returns an empty base64 string and `true`.
The helper repeats `pread` through short reads/EINTR until the requested length,
EOF or an actual I/O error. Offsets above the native signed `off_t` range return
`EINVAL`; they do not wrap, return invented data, or keep a failed read handle.

## Acquisition and lifetime

The supervisor first snapshots and validates `PolicyIntent` with the actual
session, request and method, resolves the complete managed policy, checks the
requested guest read grant, and admits the existing private workspace through
the inherited four-value `_inspect(policy)` contract. This is the same ordinary,
exclusively leased workspace scope documented in [native-files.md](native-files.md).

The native helper receives only the pinned workspace FD and one endpoint of a
private `AF_UNIX/SOCK_SEQPACKET` socketpair. It checks socket type and
`SO_PEERCRED` against its parent PID and UID. Its open operation uses:

```text
openat2(ROOT_FD, relative_path,
    O_PATH | O_NOFOLLOW | O_CLOEXEC,
    RESOLVE_BENEATH | RESOLVE_NO_SYMLINKS | RESOLVE_NO_XDEV)
```

It requires a private directory owned by the nonroot supervisor, a regular
single-link file owned by that UID, and the exact admitted device/inode. It
then reopens the pinned inode through `/proc/self/fd` with
`O_RDONLY | O_NONBLOCK | O_CLOEXEC`, rechecks its identity, and sends one FD via
`SCM_RIGHTS`. No guest program executes in this helper.

The 48-byte little-endian packet is `FGFDv1\0\0`, followed by five unsigned
64-bit values: device, inode, mode, UID and link count. The receiver uses
`MSG_CMSG_CLOEXEC`, rejects truncated or malformed transfers, requires exactly
one descriptor, and checks the actual FD metadata, readonly status and
close-on-exec flag. Any received or queued excess rights are closed when the
transfer fails. Linux echoes `MSG_CMSG_CLOEXEC` in the returned flags even on
EOF; it is not an extra packet.

A frozen record binds the client ID, session, complete immutable policy,
readonly FD and inode identity. `readBlock` passes only that descriptor to the
native block helper. It never resolves the pathname again: rename, unlink,
replacement at the old path and mode changes leave the already acquired handle
on its original inode. Concurrent changes to the original inode's content remain
visible, as with an ordinary upstream open file; a handle is not a content snapshot.

The C helper allocates only the requested block, bounded at 1 MiB. Supervisor
stdout collection is bounded by the requested size and stderr by 512 bytes.
Helpers run with an empty environment and exact inherited FD allowlists. A
30-second execution deadline, RPC cancellation and disconnect all initiate
termination and reap the helper before releasing ownership. Cleanup is shielded from repeated
cancellation. After termination it drains any stopped pipe in bounded chunks,
so a malformed helper cannot retain a paused full asyncio pipe. A failed read
drops its handle. Close/disconnect close the actual FD; disconnect also releases
the workspace lease after all pending operations have cleaned up.
The 30-second deadline starts termination; it is not a promise that a process
stuck in uninterruptible kernel I/O can be collected within 30 seconds.

As in the underlying backend, the exclusive workspace contract excludes an
unconfined concurrent writer with the same native authority. The socketpair and
UID checks are a private trusted-helper channel, not isolation between hostile
programs already running under that UID.

## Build and host evidence

Run from WSL/Linux:

```bash
cd /mnt/c/Dev/FoldGPT
bash tools/executor/native-file-streams-build.sh
```

The build snapshots all tested source files, compiles the Linux helpers with
`-Wall -Wextra -Werror`, cross-compiles the new Android ARM64 helper using NDK
29/API 35 with 16 KiB LOAD alignment, and runs tests under `nobody` when the
build shell is root. No test executes as root. Artifacts, exact source snapshots,
compiler versions, ELF inspection, test identity and SHA-256 manifest are copied
to an ignored `downloads/native-file-streams/foldgpt-file-streams-*` directory.

Verified snapshot on 2026-09-06:
`downloads/native-file-streams/foldgpt-file-streams-w6dq4e0Y`.
All **64 tests pass**, under UID/GID 65534: 22 streaming/descriptor tests,
34 existing native file tests and eight complete-policy tests. The streaming
checks include a real sparse file of 37 MiB + 17 bytes; exact EOF and offsets;
readonly/CLOEXEC and inode retention; policy rejection before spawning; complete
handle binding; 128 handles and UTF-8 boundaries; session separation; repeated
open/close without FD leaks; strict malformed diagnostics; actual malformed
SCM_RIGHTS peers including 253 supplied FDs; helper stdout/stderr floods;
registration failure; cancellation during actual spawn completion, after queued
FD transfer and during read; and active-disconnect reaping/lease release.

The test suite executes real binaries and kernel IPC. Its fault-injection peers
are separate Python processes exercising the real Unix socket protocol. One
spawn-race test delays the return of a real `create_subprocess_exec` call to
exercise the cancellation boundary deterministically; no native I/O success is
simulated.

Android helper:
`libfoldgpt_file_handle.so`, SHA-256
`7516c73bac522e74867861336b3a0f54196cd00d1017ca1ffd1137653e4ae972`.
It is a static Bionic ARM64 executable packaged with a `.so` filename, without
an interpreter or dynamic dependencies; every LOAD segment is aligned to
`0x4000`. This snapshot proves cross-compilation and host execution. The later
Android checkpoint below uses a different, explicitly hashed helper; it does
not retroactively qualify this older binary.

## Actual Android bridge evidence

The integrated v2 debug fixture passed **53 RPC responses across two sessions**
on the Fold, UID/GID 10412, with the real GNU ARM64 guest bridge under PRoot and
the Android/Bionic broker and helper outside it. Both sessions advertise only
`sandboxedFileStreaming`. They read an ordinary **37 MiB + 13 byte** binary file
at offsets 0, 16 MiB + 17, the final 13 bytes, and the exact end. Eight successful
block responses contain the exact bytes and EOF flags. Close, denied private
read, missing path and old-session handle refusals are checked. The fixture
observes one actual broker FD per open and zero after close/disconnect, including
a handle left open by the client; reconnect gets a different session and the
workspace lease is released.

The executed helper is `libfoldgpt_file_handle.so`, SHA-256
`a57eff0d42d8996c0a370c18184dc4e9ef4086c7cd7e8abc8ece1712be13a312`, in APK
`373aa5c8f4e54fb9256d599fde2f7b30f1acd34eebfce1a49db169518f37bcf4`.
Independent collection pins that installed APK before and after, compares all
28 installed native libraries and eight private source assets, verifies the
complete transcript and physical file hash/size, preserved metadata/private
fixture bytes, absent refused targets/socket and empty stderr. The large file's
SHA-256 is `3b9956d06f64e0071deaf9207deb0468304f5a381a4799d420ba8e03d0569cad`.
See [the exact Android artifacts and scope](private-exec-android.md). This device
sequence does not exercise every host fault case or connect a production model
task; `process/start` remains explicitly unsupported.

## Integration interface

```python
from tools.executor.native_file_streams import NativeFileStreamsBackend

backend = NativeFileStreamsBackend(
    native_file_helper_path,
    supervisor_owned_workspace,
    handle_helper=native_file_handle_helper_path,
    guest_workspace="/workspace",
)
```

The new subclass advertises `sandboxedFileStreaming` together with all three
implemented methods. The original backend keeps its own capability set; loading
this module alone advertises nothing. `ExecServer` already verifies the complete
method prerequisite before accepting this capability. Integration must select
the subclass and deploy its real helper, never just add a capability string.

The Android debug integration now stages `native_file_streams.py` alongside the
existing executor modules, packages `libfoldgpt_file_handle.so` as an executable
APK native library and passes its installed absolute path as `handle_helper`.
Production integration still requires the actual Desktop/environment routing
and trusted policy lifecycle; the diagnostic service is not that route.

This work changes neither Android root state, bootloader, SELinux policy,
seccomp filters nor device security settings. It uses ordinary app-owned files,
the existing native runtime, native OS descriptors and normal process cleanup.
