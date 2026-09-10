# Native runtime acquisition

Startup-only contract `foldgpt.native-runtime.v1`. This is not an ExecServer or
app-server RPC and cannot be selected by model requests.

The trusted Android owner starts its installed Python backend through run-as.
The backend creates one AF_UNIX/SOCK_SEQPACKET listener in the app-private
endpoint directory, outside every model workspace. The Android owner publishes
the canonical socket pathname and actual child PID/UID/GID in a private startup
manifest. The controller checks directory/file ownership and SO_PEERCRED against
that owner-supplied identity. Both peers enable SO_PASSCRED before admission.
The native owner accepts only the app UID, and pins the client's actual kernel
PID/UID/GID for all three channels. No reconnect or replacement is implicit.

One exact controller packet, without descriptors:

```json
{"type":"acquire","schema":"foldgpt.native-runtime.v1"}
```

The native owner replies with this exact packet plus one SCM_CREDENTIALS and
exactly three SCM_RIGHTS, in the listed order:

```json
{"type":"channels","schema":"foldgpt.native-runtime.v1","workspaceRoot":"file:///actual/owned/root","fdRoles":["exec","config","host"]}
```

The descriptors connect directly to the native owner: an anonymous duplex
SOCK_STREAM for ExecServer, and two separate anonymous SOCK_SEQPACKET socketpairs
for configuration reads and host/UI files. The actual child credentials are
checked on acquisition and each config/UI packet. A Java byte relay is absent.
All received descriptors become CLOEXEC immediately. Any extra descriptor,
ancillary record, truncation, unknown/duplicate JSON field or wrong socket type
closes acquisition with all received descriptors closed.

The controller initializes ExecServer on `exec` using the ordinary protocol.
Only after that real initialization chooses the real ExecServer session does
the native owner issue configuration and host authorities and send the second
acquisition packet, with credentials and **no descriptors**:

```json
{"type":"ready","schema":"foldgpt.native-runtime.v1","sessionId":"actual-execserver-session","workspaceRoot":"file:///actual/owned/root"}
```

Configuration and host clients must require this exact session identity and
root in their own ready messages. The first packet never invents a session or
initializes the model connection on the client's behalf.

The acquisition socket remains open as a lifetime channel. EOF or any further
packet stops admission and cancels the three tasks. Their native cleanup is
awaited by the existing owner; only its actual reaping clears ownership.
Independent Binder cancellation continues to arrive at FD3. A lost transport
does not assert cleanup. A quarantined owner remains alive.

Acquisition packets are at most4096 bytes. Native startup and acquisition waits
are bounded; the limits do not convert timeout into cleanup. Sharing the root
with the GNU controller must be measured separately before choosing `Shared`.
This document specifies implementation under construction, not device success.

## Production CLI manifest

The separate engine accepts `codex app-server --foldgpt-native-bootstrap PATH`
and the standalone app-server accepts the same startup flag. Other app-server
tooling subcommands reject it. The official application receives our launcher
through its existing executable override; the official executable is intact.

`PATH` is a canonical owner-private regular file, outside the model workspace,
with this exact object (`controllerRoots` are disjoint from `workspaceRoot`):

```json
{"schema":"foldgpt.native-startup.v1","socketPath":"/actual/private/owner.sock","peer":{"pid":12345,"uid":10412,"gid":10412},"workspaceRoot":"file:///actual/project","sharedPaths":[{"path":"file:///actual/project","device":1,"inode":123}],"controllerRoots":["file:///home/foldgpt","file:///tmp"],"parentEnvironment":{"PATH":"/actual/runtime/bin:/system/bin","HOME":"/actual/project","TMPDIR":"/actual/project/.foldgpt-tmp","SHELL":"/actual/installed/libfoldgpt_bash.so","LANG":"C.UTF-8"}}
```

Numbers above illustrate the shape; the Android owner must publish actual
values. `sharedPaths` contains the native device/inode of the workspace and
each additional shared runtime root used by environment metadata. The controller
compares its actual canonical files to these identities. It then reserves a new
temporary proof file inside W, asks the real native host authority to write
random bytes, and reads those exact bytes through the controller filesystem.
The initial reservation is empty, so it cannot manufacture the successful read.
Only after that proof and the native environment path checks is the runtime
registered with the app-server. The bootstrap removes only its own verified
proof file. A failure may leave that file as diagnostic evidence.

PRoot intentionally maps libc UID and stat-owner UID together. Manifest and
endpoint ownership checks compare those two controller-visible values, while
`/proc/self/status`, SO_PEERCRED and packet credentials separately require the
real nonroot application UID and exact native PID/GID. The relevant PRoot
source is `vendor/proot/src/extension/fake_id0/stat.c`: it substitutes ownership
only for files owned by its actual UID. No kernel identity is inferred from
the virtual libc UID.

The production CLI retains normal plugin startup, configuration, session source,
authentication and analytics options. A private lifetime monitor revokes the
runtime and asks app-server to enter its normal connection/thread cleanup path
on owner loss. Normal app-server exit explicitly disconnects configuration,
host files, exec and the lifetime channel; it never reports native reaping from
that alone.


## Installed production owner

`foldgpt_native_bootstrap.main([APK, UID, PARENT, NONCE, LAUNCH])` runs only after
`libfoldgpt_native_bootstrap.so --native-runtime-v1 UID DATA PARENT NONCE APK LAUNCH`
has admitted the real run-as identity, private Python data and installed ELF
inventory. Its import root is `APK/assets/foldgpt-executor`.

The app writes E/NONCE/launch.json before launch with exactly:

```json
{"schema":"foldgpt.native-launch.v1","workspace":"/data/user/0/app.foldgpt/files/projects","socketPath":"/data/user/0/app.foldgpt/app_foldgpt_exec/NONCE/owner.sock","manifestPath":"/data/user/0/app.foldgpt/app_foldgpt_exec/NONCE/startup.json","controllerRoots":["file:///home/foldgpt","file:///tmp"]}
```

NONCE is the actual fresh32hex launch nonce. E is the actual app-private
`app_foldgpt_exec` directory. The global owner lock and persistent process marker
remain at E, so choosing another nonce cannot bypass a quarantined session.
Python publishes the actual listener and startup.json, fsyncs them, then sends
the existing exact `foldgpt.shizuku.session.v1` ready record on FD2. FD3 remains
independent cancellation. No worker uses Java's stdin/stdout pipes.

The startup manifest also contains `parentEnvironment`, copied from the native
backend's immutable inheritance snapshot. The GNU controller resolves ordinary
command/exec shell policy and exact nullable overrides from this native snapshot.
It must not substitute its GNU PATH/HOME/TMPDIR. Model unified-exec retains the
upstream executor environment-policy transfer; controller package PATH prepends
and controller shell snapshot files do not belong to an injected native runtime.

The producer measures W, the production Python root R, and actual installed
nativeLibraryDir N. The controller must share W:W, R:R, N:N and E:E with their
actual canonical spellings. The manifest covers the native Bash path through N,
and native HOME/temp through W. The GNU controller and native Bionic workers
remain distinct execution domains with shared factual file identities.
