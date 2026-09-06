# Inactive native integration: scripts, Mesa and XKB

This document retains the **v1 container and v3 combined-preparation evidence**.
The current assembly tool emits an explicit v2 container with agent-context
files. Its separate contract, host checks and remaining Android scope are in
[Inactive agent-context revision](inactive-agent-context.md). Existing v1
containers remain accepted unchanged; they are never relabeled or upgraded in
place.

This increment installs the missing guest integration into the **existing leased,
inactive Debian stage**. It uses native Android Java/filesystem APIs. Neither
PRoot nor a guest Python process performs the installation or the XKB checks.

The inactive preparation coordinator's new v3 route binds this input and calls
the adapter after the guest account and before installing the official client.
This component does not validate GPU execution, browser operation, managed
executors, client/keyring readiness, or the complete runtime. Its durable report
states those limits; it cannot authorize activation by itself.

## Release input

`tools/install/inactive_integration_bundle.py` authenticates these archives
against the release's independently established digest pins:

- The existing canonical guest bundle by an independently supplied SHA-256.
- Debian base `dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f`.
- The reviewed Mesa foldgpt5 archive
  `e02091631e5f16efbc3678373b2c048ebf81b10d551caf210d61b1954b7671d4`.

It emits a bounded `.fgi` container and an exact readable `.manifest` sidecar.
The container starts with the format magic, a big-endian 32-bit manifest length,
an ASCII manifest, then the installed regular files in manifest order. It is
bounded to 64 MiB, with a 512 KiB manifest and 32 MiB individual payload files.
There is no archive extraction engine in the Android reader. The complete input
digest and size are checked before any stage mutation. A digest calculated from
an untrusted download is not an independently trusted release descriptor.

The exact installed set consists of 20 regular files and 9 relative symlinks:

- Session launcher, keyring and IME scripts, keyboard-focus source, URL opener,
  keyring preparation helpers, license and a declared launch contract.
- Seven AArch64 ELF libraries, four Mesa configuration files and nine library
  links under `/opt/foldgpt-gpu/mesa-26.2.2-foldgpt5`.

Development probes, headers and pkgconfig files in the reviewed Mesa archive are
not runtime payload. The corresponding source/review bundle remains a separate
release obligation. Mesa bytes are unchanged. The source archive's Windows
staging modes were 0777: the installer deliberately assigns library files 0755,
configuration files 0644, directories 0755 and relative symlinks 0777. It does not
inherit world-writable file permissions.

The two keyring installation helpers use 0600, matching the existing inactive
coordinator. Their exact pre-existing bytes and mode are accepted. Every other
pre-existing integration file requires this installer's already bound intent.
Debian files and unknown existing files are never overwritten.

All **316 XKB entries** from the authenticated Debian archive are inventoried,
without copying Debian data into the integration payload. The native installer
checks the exact existing tree, each file's hash and mode, every directory, and
the three relative XKB links. Native `toRealPath()` must resolve the links to
readable inventoried files inside the stage's XKB tree. This is the pathname
interpretation used by Xlorie outside PRoot.

## Coordinator call

The new coordinator route is:

```java
AndroidInactivePreparation.IntegrationInput integration =
    new AndroidInactivePreparation.IntegrationInput(
        () -> Files.newInputStream(container, LinkOption.NOFOLLOW_LINKS),
        trustedIntegrationSha256, trustedIntegrationBytes,
        trustedIntegrationManifestSha256);
AndroidInactivePreparation.Result result = AndroidInactivePreparation.prepare(
    context, spec, baseArchiveSource,
    initializerSource, initializerSha256,
    supervisorSource, supervisorSha256,
    clientInput, integration);
```

Both `ClientInput` and `IntegrationInput` are mandatory for this overload. Its
journal is `foldgpt.inactive-preparation.v3`, with `INTEGRATION_PREPARED` between
`ACCOUNT_PREPARED` and `CLIENT_PREPARED`. It binds the container SHA and byte count,
manifest SHA and durable integration report SHA. It authenticates the container
and compares both helper hashes before opening/preparing a root or vault. Every
retry actually checks the native files before running the client package step
or using the vault. `result.integration` exposes the installer evidence.

The earlier `prepare(..., ClientInput)` v2 diagnostic and `prepareKeyringOnly`
v1 diagnostic remain explicit, separate scopes. All three share the original
journal pathname `inactive-preparation.v1` to reject implicit migration,
downgrade or bypass by another journal filename. Earlier diagnostics never
claim native integration evidence.

The prepared integration input includes these exact canonical LF helper hashes;
the v3 coordinator rejects a mismatch before opening a root or vault:

```text
initialize_keyring.py  f2a11141839bd3a563e7250275cdf307c9b6c8cb4422c5591c693a82036f39c0
supervise_keyring.py   3e46f4318889d8dca20dedbe43b443ed24c8336671bb62bd38feba03fbbf0dff
```

For an enclosing installer that already owns its transaction, the lower-level
adapter is `AndroidInactiveIntegrationInstaller.install`:

```java
try (InputStream input = independentlyVerifiedReleaseInput.open()) {
    InactiveIntegrationInstaller.Result result =
        AndroidInactiveIntegrationInstaller.install(
            transaction, installationId, input,
            trustedIntegrationSha256, trustedIntegrationBytes);
}
```

Use the caller's existing, live `RootfsTransaction` in `PREPARED` state, after
guest identity provisioning. Retain the lease through later preparation. The
adapter checks the actual Android UID/GID against the guest account; it never
uses a fixture UID. The v3 coordinator binds the independently trusted
container digest/size and manifest digest, persists `result.reportSha256`, and
calls this real verifier on every retry. Source input
must be supplied again on retry; this component does not silently replace a
missing release source with a different bundle or create a new transaction.

The result exposes the actual `root`, `rootIdentity`, `report`, `bundleSha256`,
`manifestSha256` and `reportSha256`. The existing extractor receipt must identify
the same authenticated Debian base. Reopening the transaction validates its
original stage inode and receipt. An active transaction is rejected.

## Durable publication and drift

The intent and report live inside the stage at
`var/lib/foldgpt/integration-install/{intent,report}.v1`. The intent binds the
installation ID, root device/inode, input and manifest digests, and guest
identity before installing any final payload file. All target paths and the
complete XKB inventory are checked before this intent is created.

Files are written to fixed, intent-owned `.pending` names, synchronized, then
published with atomic moves under the retained installation lease. An incomplete
own pending write can be rewritten from the authenticated bytes. Final existing
files must already match. Links are published after their complete dependency
chain resolves, so an interrupted sequence leaves no dangling final link.
Unknown GPU prefix entries, symlink parents, hardlinked regular files and
impossible pending/final combinations are rejected.

The report records the native file identities, verified hashes, modes and link
targets for every installed and XKB entry. It is immutable after completion.
A completed retry rereads the real files and exact XKB/GPU trees and compares
the generated report byte-for-byte. It does not repair missing or altered files,
change permissions, replace inodes or discard the earlier report to claim a pass.

This follows the existing installer's exclusive-stage model: the app owns the
stage, no guest runs from it, and no other process sharing the same Android UID
writes concurrently. It is not a boundary against hostile code with that UID.
The atomic publication relies on that retained lease and exclusive access.

The declared launch contract records the current session path, GPU prefix and
ICD, XKB path, display `:2`, loopback CDP port 9223 and the sources of account,
display scale and bridge identity. It is a description of inputs, not proof that
the shell, client or browser has executed correctly. The installer requires the
complete GPU prefix even though the current session script has a Debian-library
fallback when that prefix is absent.

## Verification

```powershell
python -B -m unittest discover -s tools/install -p test_inactive_integration_bundle.py -v
wsl -e /bin/bash /mnt/c/Dev/ChatgptFold/tools/install/integration-native/run-jvm-tests.sh
```

The dedicated JVM runner checks the existing pinned Maven dependencies, compiles
an isolated source snapshot and runs under an unprivileged Linux identity. It
tests actual filesystem installation/revalidation, native links, eight separate
JVM deaths at durable publication boundaries, a partial pending write, immutable
completed reports, byte/mode/link/extra-file drift, path aliases, authentication,
account/input bindings and refusal after activation. Tiny test payloads are
explicit fixtures and are never represented as functioning GPU libraries.

The optional `InactiveIntegrationRealArchiveCheck` separately extracts the actual
authenticated Debian archive into a new host Linux stage, creates its locked
guest account, installs the actual release container and repeats verification
after closing/reopening the lease. It executes no ARM binary and is not an
Android/GPU runtime test. Its seven arguments are: fresh files directory, Debian
archive, integration container, trusted container SHA, container bytes, guest UID
and guest GID. Use a non-root host identity whose numerical IDs are free in the
Debian base; Debian already owns 65534 as nobody/nogroup.

The prepared release container has:

```text
bytes           41116761
sha256          d0d9f2edce1c194ae2188556922373bb8e66d9ae30e8f34197da54a51945c16c
manifestSha256  a832faca1620125b00256271c236e12d07dc5972f3b403a24407559ca0b0feb0
guestBundleSha  00c2c68ec845b8e2a26eeafa45999be33fdae1dd954d28b05e5517b51303ab9b
```

Local private artifacts and test snapshots are under
`downloads/install/integration-native/`. They are not source-controlled runtime
state and are not installed into the current development phone by these tools.

Completed host checks on 2026-09-06:

- 7 Python archive/format tests passed.
- 9 dedicated JVM/native filesystem tests passed, including eight actual JVM
  deaths. Evidence: `foldgpt-integration-java-agj6mRJJ`.
- 46 existing transaction/account/journal/process tests passed, including twelve
  new actual JVM deaths around all six v3 journal states and v1/v2/v3 scope
  refusal. Evidence: `downloads/install/transaction-check/foldgpt-install-java-77zvDTv9`.
- All installation Java plus KeyringVault compiled against Android API 37.
- Actual Debian and the 41,116,761-byte integration container were installed and
  verified twice across a closed/reopened transaction under Linux UID 12345,
  GID 23456 (the actual unprivileged host credentials for this fixture).
  The operation took 80.855 s. The root remained `PREPARED`, device/inode
  `2096:299252`; all installed and XKB file identities were unchanged.
  Report SHA: `54b07104a8bebd9a73f5caa3e4c32ee0eff7d65fa3500d139bbed71183333fa6`.
  Output: `downloads/install/integration-native/real-archive-check.txt`.

These are host filesystem/format/coordinator-journal results; none starts the
GPU, client, browser or display.

## Actual Android combined preparation

The v3 coordinator then passed on the Fold under UID 10412, using fixture
`8b654a63b6f64c138fe2a0da31594de8`. Two real complete calls took 225,050 ms;
both verified the 29 integration entries and 316 XKB entries, the intact
official client and the same vault/collection. The recovered root remained
`PREPARED`, identity `65097:330907`. The integration report kept identity
`65097:350044` and SHA-256
`7c78c178f4e3dd681c5accc8605db4058b1f9dcaa0fe29b6bb2666c92e3ac964`.
The base was not reopened during this recovered run; the second call also
omitted the package source. Integration was authenticated twice.

The first Android attempt exposed a real cross-component permission conflict:
integration created `/var/lib/foldgpt` as 0755 while the client installer
requires this shared state parent to be private. New integrations create it as
0700. Recovery tightens the old 0755 directory only after the bound integration
intent and files have been verified, preserving its inode and report. Ten real
native JVM tests pass, including that recovery. The exact failed Android stage
then completed with debug APK SHA-256
`f6f5f500d5e19139adfc536b95ba6e38e1605d543c77d013df181f4208f22e09`.

The initial failure and tested APK are retained under
`downloads/install/combined-device-v3-8b654a63b6f64c138fe2a0da31594de8`.

## Independent native collection

[`combined-probe/collect.py`](../../tools/install/combined-probe/collect.py)
independently passed against all **345 physical entries**: 29 installed entries
and 316 Debian XKB entries. It authenticates the local `.fgi` and manifest,
derives device paths from the fixture ID and checksummed `PREPARED` transaction
journal, and runs native Android stat/hash/readlink operations outside PRoot.
File bytes, sizes and modes match the manifest; actual inodes match the immutable
report. Links resolve to the expected inventoried native file. The exact XKB
and GPU trees have no missing or extra entries.

The collector verifies two successful calls, two integration input opens,
unchanged root/package/report identities and matching vault/collection hashes.
It also verifies the retained client package and installed APK/native-library
bindings, absence of an activation pointer, and unchanged report hashes across
collection. Ciphertext and collection intent are hashed on-device; neither
credentials nor ciphertext are transferred. Only structural reports and native
observations are retained.

The APK identities are deliberately separate:

| Private collection directory under `downloads/install/` | APK present during collection | Meaning |
| --- | --- | --- |
| `combined-device-v3-collected-f4275224a90f4550bd00f686aa7428af` | `f6f5f500d5e19139adfc536b95ba6e38e1605d543c77d013df181f4208f22e09` | Historical collection under the APK that completed the two v3 calls. |
| `combined-device-v3-collected-6a08b04c0df1487cac11106548910390` | `b47b230214cf2fcd8744ebaa951fb6c2b6c6e445c2097da01528dc3734c7263b` | Later native reinspection of the same retained stage and report after an APK update. It did not rerun the coordinator. |

Both collections retain the same run ID
`a3f834b1-d3f9-4e38-99e6-a561cc694ecc`, 225,050 ms execution report, zero base
archive opens, root `65097:330907`, package `65097:350522` and integration report
`65097:350044`. The later APK did not produce the earlier execution report.

```text
combined report SHA256     7e337bf76714aa2ef95e43478e1e2cbe302794670e559c01b59fc73f731f7a7e
integration report SHA256  7c78c178f4e3dd681c5accc8605db4058b1f9dcaa0fe29b6bb2666c92e3ac964
native inventory SHA256    275234a609c1eff73cce87d215f9b361c47ba0c535e734d8662b2ec3cae3ee7c
```

All retained report/inventory hashes were recomputed for both collections at
this checkpoint. A collection overlapping the APK replacement failed, and a
subsequent attempt pinned to the old APK digest was refused. The successful
later collection used the independently checked new digest.

This is still inactive preparation and reinspection: no GPU/client execution,
activation or production installer is claimed by the combined probe. The
collector assumes the existing exclusive inactive-stage contract; repeated
checks do not create an isolation boundary against hostile concurrent writers
sharing the app UID.
