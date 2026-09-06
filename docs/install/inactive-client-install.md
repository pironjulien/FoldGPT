# Inactive installation of the official client

`AndroidInactiveClientInstaller.install` is the package step of the existing
[coordinator contract](end-to-end-architecture.md). The caller passes its live
`RootfsTransaction` lease, stable coordinator installation ID, authenticated
client descriptor and trusted hashes for the two Python helpers. The component
requires `PREPARED`, loads the previously provisioned guest account, runs the
actual package managers in that exact staged root and returns package-specific
evidence. It does not alter the account/keyring journals, open an independent
rootfs transaction, activate a root or launch the official client.

`AndroidInactivePreparation.prepare(..., ClientInput)` now invokes this step
under its existing transaction lease after guest-account preparation and before
vault/collection preparation. The required `ClientInput` supplies the descriptor,
package path, two helper paths/hashes and bounded package-step deadline. A null
package path requests recovery from the retained package; a null `ClientInput`
is refused. The call does not acquire/download these authenticated inputs or
start the runtime.

The coordinator's v2 journal binds the exact descriptor digest and both helper
hashes in addition to its existing root, base, native-runtime and keyring inputs.
It records `CLIENT_PREPARED` with the actual verified report hash before it can
prepare the vault. Every retry reruns the package step's actual verification and
compares that report hash, including retries after collection preparation. A
package failure or drift therefore stops the flow before credential use. The
same coordinator installation ID is passed to the package ledger on every run.

The existing diagnostic is explicitly named `prepareKeyringOnly` and retains
its v1 journal and original package-free scope. The two entry points use the same
journal pathname and refuse each other's schemas/bindings; neither silently
migrates an existing keyring installation or downgrades a client-enabled one.
The existing debug keyring probe calls only `prepareKeyringOnly`. Its earlier
Android evidence remains keyring evidence, not client installation evidence.

## Required inputs and actual execution

```java
AndroidInactiveClientInstaller.Result result = AndroidInactiveClientInstaller.install(
    context, preparedTransaction, coordinatorInstallationId,
    trustedClientDescriptor, downloadedPackageOrNullForResume,
    verifiedInventoryScript, trustedInventoryScriptSha256,
    verifiedInstallScript, trustedInstallScriptSha256, totalDeadlineMillis);
```

For the enclosing inactive flow, pass the same authenticated package/helper
inputs with the base and keyring helper inputs:

```java
AndroidInactivePreparation.ClientInput client = new AndroidInactivePreparation.ClientInput(
    trustedClientDescriptor, downloadedPackageOrNullForResume,
    verifiedInventoryScript, trustedInventoryScriptSha256,
    verifiedInstallScript, trustedInstallScriptSha256, packageDeadlineMillis);
AndroidInactivePreparation.Result prepared = AndroidInactivePreparation.prepare(
    context, trustedBaseSpec, baseArchiveSource,
    verifiedKeyringInitializer, trustedInitializerSha256,
    verifiedKeyringSupervisor, trustedSupervisorSha256, client);
// prepared.client contains the actual package report; prepared.root stays PREPARED.
```

`Descriptor` binds `chatgpt`, ARM64, exact version, archive SHA-256/size and
expanded-tar/member bounds. The two scripts are
`tools/install/official_client_package.py` and
`tools/install/install_official_client.py`. Their trusted hashes must cover the
exact canonical LF source bytes delivered by the installer. A package's own
checksum sidecar is not an independent trust source. The preceding
[input-verification component](official-client-input.md) documents package
provenance and archive checks.

The Android adapter snapshots and hashes these inputs in an app-private cache
directory, then invokes APK-packaged PRoot, its loaders, talloc and shared-memory
support. It uses the same `--kill-on-exit --link2symlink --sysvipc` engine options
as the existing inactive guest runner, with guest UID 0 for Debian package
operations. The Android process UID remains unchanged. It clears inherited
environment variables and supplies only the package-step environment; no
display, account credential, GNOME bus, namespace shim or client command is
started. Cache paths and Android UID/GID are obtained at runtime.

The total Java deadline and bounded output reader stop a failed guest process.
Cancellation uses public Android `Process.destroy()` and the packaged PRoot's
conditional SIGTERM cleanup for `--kill-on-exit`, followed by a real wait.
The tracer is never replaced with a forcibly killed process; see the
[native cancellation regression](../../tools/install/native/README.md).
The guest driver additionally bounds each package-manager command and records
its actual output in private log files. Completed outer output is retained as
`runner.log` in the private `ci-*` cache directory. A nonzero command status,
deadline or absent/mismatching receipt remains a failure.

## Dependency boundary

The authenticated Debian base already supplies the inspected official client's
required dependencies, including Debian's versioned `t64` provider packages.
The base deliberately has no DNS configuration before the later network
binding step. This component therefore requires the complete declared
dependency set to be installed already. A real APT planning operation must
propose exactly one installation, `chatgpt`; another package addition, upgrade
or removal refuses the step before client mutation. No dependency is ignored,
replaced by a stub, forcibly marked installed or downloaded from a guessed
source. A future client with additional dependencies requires a separately
authenticated base/component update before this step can succeed.

The accepted plan is followed by actual `dpkg --unpack` and
`dpkg --configure chatgpt` using the intact package. This runs its original
maintainer scripts. Subsequent checks require the exact installed version and
architecture, `install ok installed`, empty `dpkg --audit`, successful APT
dependency checking, and an unchanged base package set and versions.

The official `postinst` creates the official APT signing key and repository
configuration. Validation compares the actual key bytes with the literal key
in the authenticated `postinst`, verifies the expected HTTPS repository,
ARM64 architecture and `Signed-By` path, rejects trust-relaxing fields, and
checks the generated and active source files agree. It does not substitute a
FoldGPT repository, rewrite official files or execute an APT update transaction.

## Recovery and durable evidence

The component's per-step intent lives in
`/var/lib/foldgpt/client-install/intent.json`, under the staged root. It records
the coordinator ID, root device/inode, client descriptor, exact helper hashes,
baseline package records and progress (`PLANNED`, `UNPACKED`, `CONFIGURED`,
`VERIFIED`). This is a provisioning ledger; it cannot publish `ACTIVE` or replace
the rootfs transaction's authority. Its separate local lock supplements the
global coordinator lease.

The input package is retained in the same step's private `input` directory.
After interruption, the same bound package is reverified and dpkg can re-unpack
and configure it. Only legitimate pending trigger states are accepted for
unchanged base packages during an incomplete step. A completed `VERIFIED` step
rechecks actual files, package status and repository evidence and refuses
drift; it never repairs a completed installation by overwriting unexpected
changes. An unbound existing client or official repository configuration is
refused by the fresh installer.

When the original download is unavailable, the Java entry point accepts a null
package source and snapshots the exact already-retained package from the bound
inactive root. No base re-extraction or account/credential regeneration occurs.
Changed helper hashes or client descriptors require deliberate coordinator
compatibility handling; they cannot be silently adopted into an earlier intent.

Before the report is published, packaged files and their containing directories
are synchronized, together with the official repository outputs. Java compares
the returned receipt with the actual report bytes, staged root identity,
coordinator ID and installed package fields, revalidates the account and calls
the transaction's existing prepared-root verification again. Success has scope
`configured-client-package-only`. Complete GPU, command-policy, keyring,
lifecycle and activation validation still belong to the coordinator.

## Validation scope

The coordinator integration passes 43 JVM/POSIX tests under nonroot Linux,
including three new client-journal tests. They exercise the mandatory client
step before vault progression, refusal of changed package/helper bindings and
implicit scope migration, and ten actual JVM deaths immediately before/after
the five durable publications followed by recovery of the same coordinator ID.
These are journal/filesystem tests; their fixture hashes do not simulate a
package installation or claim Android keyring success. Evidence is
`downloads/install/transaction-check/foldgpt-install-java-TcfevgTg`.
The complete installation Java sources, `KeyringVault` and the retained debug
keyring probe compile against the actual Android API 37.0 SDK, with evidence in
`downloads/install/coordinator-client-compile-afb1bbacdcfd45fcabc76a16f3ee9aa5`.
The combined coordinator now runs on Android and installs the actual package
through this entry point. The first complete call and source-free retry both
pass with matching root/package inodes, client report, vault and collection.
Details are in [combined-preparation-probe.md](combined-preparation-probe.md).
Its result remains inactive provisioning evidence;
GPU/integration installation, protected commands, lifecycle and activation
validation are still outside this increment.

Four JVM tests execute real child processes as a nonroot Linux user and cover
the precise PRoot bindings/environment, refusal of ambiguous paths, input EOF,
private failure evidence, excessive output, deadlines and interruption. Seven
Python tests cover APT plan refusal, baseline/version checks, root mismatch and
real subprocess status/deadline/output handling. The new Android adapter and
its dependencies compile against Android API 37. The subsequent real Gradle
debug/release builds and APK separation checks pass; the debug build is installed.

A separate live fixture uses the authentic Debian 13 ARM64 base and official
`chatgpt` 26.901.41600 package, with the same PRoot source revision
`7266fb3e8516535682f5a9c8f3a7e70f6506eddb` compiled for the Linux host and QEMU
for ARM64 guest execution. The real package install, original postinst, APT
dependency check and package inventory pass while the host process runs as
`nobody`. This is host provisioning evidence, not Android execution, graphics
validation or official sign-in.

A real interruption after the durable `UNPACKED` checkpoint terminated PRoot
through SIGQUIT. Resuming that same root reached `VERIFIED` with the same root
device/inode, retained package inode, coordinator identity, descriptor and
helper hashes. Dpkg configuration, APT dependency validation and all packaged
files were rechecked. The final report SHA-256 is
`6ba41a8bc3400ffdaf830ae393269b83b07c0de1370244624d4b5041d85cf7b9`;
evidence is `/var/tmp/foldgpt-client-install-live-yy326861/resumed-proof.json`.
An earlier SIGTERM attempt against the unpatched PRoot did not stop it and is
excluded from interruption evidence.

After the cancellation integration, four JVM tests passed again, the real
Gradle debug/release builds and release vital lint passed, and the debug APK
was installed preserving its application UID and existing data. The package
step is now invoked on Android by the separately recorded combined probe;
installation of the containing APK alone was not used as that evidence.

The old Ubuntu PRoot 5.1 initially failed dpkg's database access check despite
the fixture directory being writable. The same fixture completed with the
canonical PRoot source revision. No access check was bypassed or directory
permission weakened to obtain that result.

Private evidence, including commands and package-manager outputs, is retained
under `downloads/install/client-input-59de43132ff8467498627ae89f08d494/` and the
referenced `/var/tmp/foldgpt-client-install-live-*` host fixtures. No package,
account profile or credential is added to the public source tree.
