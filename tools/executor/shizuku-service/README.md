# Authenticated Shizuku executor transport

This independent Android library hosts a **fixed, installed Python/Bionic
ExecServer backend**. It is an integration component, not a new sandbox and not
an assertion that general FoldGPT execution already works. The caller never
supplies a privileged executable, service argv, environment, native pathname or
backend selection. The command and full policy remain structured ExecServer RPC
inputs to the installed backend.

No main FoldGPT files, Shizuku lab files or official ChatGPT files are modified
by this project. Building it does not install or launch anything on the phone.

## Boundary and interface

`ExecutorService` is an official Shizuku `UserService`, constructed with its
installed application Context. It requires UID 2000 and authenticates every
Binder operation against the actual application UID. The provider disables
automatic Sui initialization before its superclass starts. There is no root
backend, arbitrary `exec(String)`, ADB bootstrap, wireless-debugging setting,
WRITE_SECURE_SETTINGS grant or expiration change.

Bind with `new Shizuku.UserServiceArgs(new ComponentName(context,
ExecutorService.class))`, `.daemon(false)`, an application-version-specific
tag/version, and `.debuggable(false)`. Only bind after the ordinary official
Shizuku permission is already granted and `Shizuku.getUid() == 2000`. Retain the
binding until `status.cleanupComplete` is true; destroying an active service
requests cancellation and refuses destruction while native ownership remains.
An application Activity's destruction is not permission to destroy the owner.

`IExecutorService.open(IBinder owner)` returns one `IExecutorSession`:

- `takeInput()` transfers the RPC stdin write end exactly once.
- `takeOutput()` transfers the RPC stdout read end exactly once.
- `cancel()` requests session cancellation over an independent lifetime pipe.
- `status()` distinguishes ready, cancellation, real bootstrap reaping,
  cleanup, transport failure and retained ownership.

The client supplies a new Binder token retained for the connection lifetime.
Its death requests cancellation. Transferred `ParcelFileDescriptor`s belong to
the client; its stdin close is the actual RPC EOF, with no hidden duplicate
write end in the service. There is no timeout pretending that EOF occurred.
The pipes preserve arbitrary bytes with kernel backpressure. No Binder message
contains the command output or a large JSON RPC. The model's stdout/stderr,
process exit and stream events remain separate fields/events inside ExecServer;
the wrapper never infers cleanup by matching model output.

The JNI launcher duplicates selected descriptors before `fork`, then performs
only async-signal-safe `dup2`, `close_range`, `chdir`, `execve` or `_exit` in the
child. It passes an empty environment and only descriptors 0, 1, 2, 3:

| FD | Purpose | Ownership |
| --- | --- | --- |
| 0 | Client ExecServer NDJSON input | Client owns the sole external write end. |
| 1 | ExecServer NDJSON output | Client owns the external read end. |
| 2 | Private lifecycle reports | Service alone reads; workers never inherit it. |
| 3 | Service lifetime/control | Service owns sole external write end; EOF cancels. |

`foldgpt_shizuku_bootstrap.py` makes FD 3 non-inheritable immediately. The
qualified backend must also close inherited descriptors on every worker spawn;
the existing `NativeExecutorBackend` process implementation already uses
`close_fds` and explicit descriptors. The bootstrap retains the real backend,
workspace lease and marker after unknown cleanup. Session cancellation is
independent of stalled client stdin and stdout. No PID-based forced destruction
or automatic restart is used. `waitpid` reaps only the actual direct child.

## Immutable deployment inputs

The application must package the native library from this AAR and its real
Python CLI in extracted, APK-owned `nativeLibraryDir`. The interpreter's default
home must match the admitted Python distribution; `-I -S -u` excludes external
environment, cwd and site initialization. The interpreter SHA-256 is checked
against the installed configuration before launch. Code is imported directly
from the installed APK's `assets/foldgpt-executor` zip prefix, including the
fixed backend factory. No executable bootstrap source is copied into a shell
writable directory.

The packager must provide the installed asset
`foldgpt-executor-deployment.json` with exactly:

| Field | Meaning |
| --- | --- |
| `schema` | `foldgpt.shizuku.deployment.v1` |
| `packageName` | The application's installed package name. |
| `pythonLibrary` | Packaged basename such as `libfoldgpt_python_cli.so`. |
| `pythonSha256` | Actual lowercase SHA-256 of that packaged interpreter. |
| `brokerDirectory` | Canonical, precreated owner-only shell directory for lock/marker. |
| `workspace` | Actual fixed workspace whose identity is persisted before backend entry. |
| `backendFactory` | Installed `module:function`; callable returns the qualified backend. |
| `backendOptions` | Complete trusted construction options, never RPC-selected. |
| `environmentInfo` | Exact ExecServer environment metadata, matching pinned cwd. |

Run `python pack-assets.py --deployment <reviewed-json> --backend-sources
<reviewed-source-root>` to create the exclusive build output
`build/installed-assets`. Add that directory to the containing application's
assets source set. The script copies the existing executor/policy modules,
compiles Python source for syntax and records SHA-256 for the packaged sources.
An existing generated deployment is not overwritten. The backend factory is
supplied by the actual qualified runtime integration; the transport does not
silently select the failed legacy Android process route when it is absent.
`open` refuses missing deployment/interpreter inputs before native fork.

The backend must implement `supported_methods`, `capabilities`, `mount.uri`,
`handle`, `close`, and `processes.quarantined`, matching
`NativeExecutorBackend`. Full nested policy data is passed to `ExecServer`
without reinterpretation or removal. A factory that raises after entry is
quarantined because partially created processes cannot be ruled out. It must
therefore perform its validation before acquiring resources and reliably own
any resources it does acquire.

`PrivateListener` supplies existing lock, socket and persistent session-marker
semantics. No connection is accepted on that socket: all RPC travels through
authenticated Binder-transferred pipes. Stale markers or socket paths refuse
new sessions and need independent recovery evidence; PID absence alone never
authorizes marker removal.

## Qualification and limitations

Verified on PC on 2026-09-07:

- Independent Android ARM64 AAR builds with AGP 9.3.1, API 37, NDK r29 and Java
  17 source on JDK 21. C builds with warnings as errors and 16 KiB ELF alignment.
- Ten actual production-state reducer tests pass: caller authentication,
  independent report/wait evidence, death without cleanup, cancellation,
  malformed/coerced/duplicate reports, quarantine and pre-fork admission.
- `verify-native-host.py`, run in Linux as UID 65534, compiles and executes the
  actual JNI C/Java launcher with one explicitly host-only UID admission. A
  real Python child preserves 1 MiB of arbitrary binary input/output, distinct
  stderr, real stdin EOF, independent cancellation with stdin left open, exit
  23 and `waitpid`, and closes inherited FD 128.

These are transport checks. No Binder/SELinux qualification or general backend
policy run on the Fold is claimed. The successful fixed Shizuku/Bionic lab is
separate evidence. Installing this library alone does not resolve the general
policy mediation, native engine integration or official-client acceptance.

UID 2000 is shared with other authorized shell processes. APK-owned executable
and bootstrap code avoid a writable launcher, but staged Python runtime/data
and shell-owned workspaces still require an explicit same-UID trust boundary.
Landlock/seccomp on our workers cannot constrain a hostile external UID-2000
peer. Do not describe this transport as per-task Android-UID isolation.

Build and tests:

```powershell
gradle :transport:testDebugUnitTest :transport:assembleDebug --console=plain
wsl.exe -e /usr/sbin/runuser -u nobody -- python3 /mnt/c/Dev/ChatgptFold/tools/executor/shizuku-service/verify-native-host.py
```

Use Gradle 9.7.1 and the installed Android SDK. The Gradle dependency hashes are
recorded in `gradle/verification-metadata.xml`; they are provenance from the
resolved artifacts, not an independent signature claim.
