# Authenticated Shizuku executor transport

This independent Android library hosts a **fixed, installed Python/Bionic
ExecServer backend**. It is an integration component, not a new sandbox and not
an assertion that general FoldGPT execution already works. The caller never
supplies a privileged executable, service argv, environment, native pathname or
backend selection. The command and full policy remain structured ExecServer RPC
inputs to the installed backend.

The main FoldGPT project now includes this library and an explicitly selected
application owner. The Shizuku lab and official ChatGPT files remain separate.
Building either artifact does not install or launch anything on the phone.

## Boundary and interface

`ExecutorService` is an official Shizuku `UserService`, constructed with its
installed application Context. The native launch requires matching real,
effective and saved UID/GID 2000 with zero effective/permitted/inheritable
capabilities (therefore zero ambient capabilities). The service authenticates
every Binder operation against the actual application UID. The provider disables
automatic Sui initialization before its superclass starts. There is no root
backend, arbitrary `exec(String)`, ADB bootstrap, wireless-debugging setting,
WRITE_SECURE_SETTINGS grant or expiration change.

Bind with `new Shizuku.UserServiceArgs(new ComponentName(context,
ExecutorService.class))`, `.daemon(false)`, an application-version-specific
tag/version, and `.debuggable(false)`. Only bind after the ordinary official
Shizuku permission is already granted and `Shizuku.getUid() == 2000`. Retain the
binding until `status.cleanupComplete` is true; destroying an active service
requests cancellation and defers destruction while native ownership remains.
An application Activity's destruction is not permission to destroy the owner.
Shizuku removes its service record when issuing its one-way destroy request.
The retained observer therefore finishes that request after verified cleanup,
without requiring a second call from a client which may already be dead.

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

## App-side connection for the GNU engine

`AppSocketBridge.java` runs in the ordinary FoldGPT app process and owns a real
filesystem AF_UNIX socket beneath `context.getDir("foldgpt_exec", MODE_PRIVATE)`.
It checks the directory's canonical path, type, UID and 0700 privacy, creates an
exclusive random socket name, then checks its inode and applies mode 0600.
Every accepted connection must have kernel `SO_PEERCRED.uid == Process.myUid()`
and a valid PID before a Binder session can be opened. UID 2000 is not admitted
to this app endpoint. The existing native client independently checks the
server's exact app UID.

After an already authorized official Shizuku binding completes, the containing
application constructs:

```java
IExecutorService remote = IExecutorService.Stub.asInterface(serviceBinder);
AppSocketBridge bridge = new AppSocketBridge(applicationContext, remote, listener);
String socketPath = bridge.socketPath();
int serverUid = bridge.peerUid();
```

The existing `tools/executor/private-exec-bridge.c` already accepts this exact
endpoint. The engine's trusted environment definition launches its packaged
native bridge with the literal argument vector:

```text
<packaged-private-exec-bridge> --socket <bridge.socketPath()> --peer-uid <bridge.peerUid()>
```

No shell parses that argument vector. The kernel UID remains the app UID even
when the caller is the existing GNU engine. No TCP port, world-readable socket,
shell-UID endpoint or client-chosen backend is introduced. Binder transports
only descriptors/control; the two copy directions preserve arbitrary RPC bytes
with bounded buffers, half-close and EOF. The final stdout pipe is fully drained
before cleanup closes the client socket, even if native `waitpid` arrived first.

Hold the bridge and `UserServiceArgs`/`ServiceConnection` in FoldGPT's existing
long-lived service/controller. `bridge.close()` stops new connections and
requests native cancellation; do not unbind/remove the UserService until
`bridge.cleanupComplete()` or the `onSessionClosed` callback confirms cleanup.
A disconnected Shizuku Binder closes admission and leaves unknown ownership
visible. The adapter does not automatically bind again or replay a request.

The socket's path is a physical app-private Android path. It is unrelated to
the worker cwd. The backend deployment independently supplies its real workspace,
pins its device/inode and advertises the matching policy/environment URIs. The
adapter never substitutes `/home`, rewrites a cwd prefix, chooses a fictitious
workspace or suppresses the incoming sandbox context. Kernel/SELinux validation
of the app-side socket and Binder-FD path on the Fold is still required.

The source dependency is now included in `android/settings.gradle` as
`:shizukuTransport`, and the app declares `implementation project(':shizukuTransport')`.
Package the reviewed generated assets and required runtime libraries
in the existing runtime source set. The main app already uses
`extractNativeLibs=true` and `jniLibs.useLegacyPackaging true`, which are needed
for the fixed native interpreter pathname. Keep those settings. Build the APK
with the project's normal pipeline, then inspect its merged manifest, deployed
config, native hashes and assets before any installation.

## Current main-APK wiring

`android/app/src/main/java/app/foldgpt/FoldExecutorRuntime.java` is created by
the existing `com.termux.x11.FoldRuntimeService` in `:runtime`. Its constructor
checks that actual process name. The protected Shizuku provider stays in
`app.foldgpt`; the runtime explicitly calls the SDK's multi-process Binder
request API, with Sui initialization disabled in both contexts.

Only the package-internal service action
`app.foldgpt.action.PREPARE_NATIVE_EXECUTOR` selects native preparation. It
does not launch the existing GNU desktop after a failure. Ordinary starts keep
their existing launcher, and no generated qualified deployment is packaged by
default. A missing/unqualified deployment produces a failed preparation future,
an explicit log and app-private `native-executor-status.json` with reason
`qualified_native_deployment_unavailable`; no Shizuku bind has occurred then.
That status explicitly states `officialLauncherReplaced=false`.

The optional main build property `-PfoldgptExecutorAssets=<reviewed assets dir>`
requires all four deployment files before packaging. Runtime admission then
checks exact SHA-256 for deployment, the complete source manifest and the
actual qualification evidence. It checks every source, rejects unmanifested
files, requires the real factory, and verifies the packaged interpreter. The
qualification asset contract is:

```json
{
  "schema": "foldgpt.shizuku.qualification.v1",
  "scope": "host-native-executor",
  "deploymentSha256": "<actual deployment asset SHA-256>",
  "sourceManifestSha256": "<actual source manifest asset SHA-256>",
  "evidenceSha256": "<actual evidence asset SHA-256>"
}
```

This is documentation of required fields, not a deployable qualification file.
`foldgpt-executor-evidence.json` must record `success=true` as an actual Boolean
and the same `host-native-executor` scope, backed by the completed qualification
for those exact sources and inputs. No such claim or file is generated by the
transport packager. Host qualification does not claim phone or official-client
acceptance. The packaging script includes `foldgpt-executor-manifest.json` but
leaves generation of genuine qualification evidence to the completed backend
validation.

The old unconditional `killProcess` in `FoldRuntimeService.onDestroy` is now
behind actual native cleanup and a process-wide `RuntimeExitGate`. Four real
JVM tests verify normal release, older unresolved ownership, newer Service
generations, and rejection of invented/double cleanup. The latest service
cannot kill older pending native work; an older delayed callback cannot kill a
new service. Official Shizuku bindings are detached only after cleanup, with
`remove=false` so another active connection is not removed. If a Binder never
reached this owner, no RPC session or worker could have been started by it; a
late callback only observes its closing state.

The main debug APK builds and verifies under the preserved signing certificate
SHA-256 `30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16`.
Its content separation check passes. The merged manifest has the protected
provider in the main process and the non-exported runtime service in `:runtime`.
The existing `WRITE_SECURE_SETTINGS` declaration comes from Termux:X11; this
integration neither grants it nor adds a settings-writing startup path.

The main Gradle unit-test task currently cannot compile the existing
`TrustedHttpsArtifactTest` against the Android test bootclasspath because
`com.sun.net.httpserver` is unavailable there. The four new exit-gate tests were
compiled from their actual source and passed with the normal JDK 21/JUnit
runner. This limitation is separate from the successful main APK build and the
12 passing transport-library tests.

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

For the attested cwd compatibility library, the installed backend option is:

```json
{"cwdShim":{"path":"@nativeLibraryDir/libfoldgpt_bionic_cwd.so","sha256":"ACTUAL_PACKAGED_SHA256"}}
```

The example digest is deliberately not valid deployment evidence. CMake
compiles this library from `../bionic-cwd` into our APK's extracted native
libraries. `InstalledLibrary` resolves the fixed basename under PackageManager's
canonical `nativeLibraryDir` and checks its actual SHA-256 before fork. An
absolute deployment-supplied path, another filename or a traversal is refused.
The bootstrap independently resolves it beside the actual `/proc/self/exe`,
matches sys.executable and the configured interpreter basename, rejects aliases
and verifies its digest before constructing the backend. Only then is the
resolved absolute `cwdShim.path` supplied to the native process factory.
Package updates can change `/data/app` paths without rebuilding a path into the
deployment JSON. The packaged shim digest still needs exact build qualification.

The backend must implement `supported_methods`, `capabilities`, `mount.uri`, `files.root`,
`handle`, `close`, and `processes.quarantined`, matching
`NativeExecutorBackend`. Full nested policy data is passed to `ExecServer`
without reinterpretation or removal. A factory that raises after entry is
quarantined because partially created processes cannot be ruled out. It must
therefore perform its validation before acquiring resources and reliably own
any resources it does acquire.
The bootstrap checks the pinned root's device/inode against the workspace
identity persisted before factory entry.

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
- Two real bounded-pipe adapter tests pass: a further 1 MiB binary transfer
  under backpressure with EOF and an output failure propagated as an error.
- Four installed-library Java tests pass: exact packaged bytes, bad/missing
  digests/files, fixed marker and traversal/alternate-path rejection.
- `verify-deployment-host.py` launches a real copied Python ELF in a changing
  test package directory and checks the production resolver: actual executable
  identity, fixed path, preserved options, wrong digest, symlink, missing file,
  writable file and malformed schema. This proves PC admission semantics, not
  Android package-manager or SELinux behavior.
- `verify-native-host.py`, run in Linux as UID 65534, compiles and executes the
  actual JNI C/Java launcher with one explicitly host-only UID admission. A
  real Python child preserves 1 MiB of arbitrary binary input/output, distinct
  stderr, real stdin EOF, independent cancellation with stdin left open, exit
  23 and `waitpid`, and closes inherited FD 128.
- `verify-bootstrap-host.py` executes the real bootstrap and ExecServer with a
  recording/refusing test backend. Complete nested policy survives unchanged;
  the test refuses command execution. A separate real diagnostic child is
  reaped on stdin EOF and service EOF with stdin still open. An injected
  cleanup-reporting failure retains the live bootstrap and persistent marker.

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
wsl.exe -e /usr/sbin/runuser -u nobody -- python3 /mnt/c/Dev/ChatgptFold/tools/executor/shizuku-service/verify-bootstrap-host.py
```

Use Gradle 9.7.1 and the installed Android SDK. The Gradle dependency hashes are
recorded in `gradle/verification-metadata.xml`; they are provenance from the
resolved artifacts, not an independent signature claim.
