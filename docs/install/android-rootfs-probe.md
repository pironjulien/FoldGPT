# Isolated Android rootfs preparation probe

`app.foldgpt.install.RootfsProbeService` lives only under `src/debug`. It runs
the real production extractor, transaction and Android POSIX adapter under the
ordinary application UID. It never launches Linux, provisions an account,
creates a keyring, modifies client files, calls `activate`, or changes the
current runtime service. There is no network or arbitrary input path/command.

The debug manifest now registers this service. Actual Android preparation and
resume passed on 6 September 2026, followed by independent full inventory and
native-shell comparisons. These checks establish an inactive Debian base,
not completion of the first-install product flow.

## Debug manifest registration

Merge this service **only into `android/app/src/debug/AndroidManifest.xml`**:

```xml
<service android:name="app.foldgpt.install.RootfsProbeService"
    android:process=":rootfsProbe"
    android:exported="true" android:permission="android.permission.DUMP"
    android:foregroundServiceType="specialUse">
    <property android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
        android:value="ADB-only verified Debian preparation in an inactive diagnostic stage" />
</service>
```

The normal manifest already declares foreground special-use and wake-lock
permissions. Release must contain neither this component nor its implementation.
The manifest's DUMP permission limits external starts to authorized Android
diagnostic callers. The service ignores all Intent extras, uses a dedicated
process and refuses to touch an activated probe tree.

## Fixed input and provenance

Use only this existing host file; no download is required:

```text
downloads/install/debian-13-arm64-dd0aac2065057596/debian-13-arm64-rootfs.tar.gz
SHA256 dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f
compressedBytes 327673156
payloadBytes 958101116
maxTarBytes 977131520
members 20240
```

The archive digest is in that directory's `SHA256SUMS.json`; its
`manifest.json` SHA-256 is
`5e42ca69096d588d10a6599dcd4f0ae73fdba751e9f611f9cd984a493498068c`.
The extraction counts were independently derived after verifying this exact
archive and are retained in `downloads/install/transaction-real-spec.json`.
They are pinned in the debug service, not accepted from a remote Intent or
unauthenticated adjacent manifest. This is a fixed local diagnostic input,
not an update channel or production release descriptor.

Before launch, import the exact bytes as an app-owned regular file:

```text
/data/user/0/app.foldgpt/cache/rootfs-probe-input.tar.gz
```

Use an exclusive temporary file in that cache, mode 0600, verify its SHA-256
under `run-as app.foldgpt`, and publish it without replacing an unrelated input.
An already present matching file can be reused. Do not stream binary bytes
through PowerShell text redirection; use a binary-safe subprocess/file transfer.
The input must have one hardlink, app ownership and no group/other write bits.
The service checks its actual no-follow file descriptor, exact length and hash,
then the production extractor authenticates its own private snapshot again.

Check device free space before import/preparation. The diagnostic retains both
327.7 MB archive copies plus about 958.1 MB payload and filesystem overhead.
It does not delete caches or old installations to create space. Because the
run uses the already installed app UID, retain exclusive control of this
diagnostic staging area while it runs; a malicious same-UID process is outside
the installer's ownership contract.

## Launch and outputs

After the coordinating build and normal debug APK update:

```sh
adb -s SERIAL shell am start-foreground-service \
  -n app.foldgpt/app.foldgpt.install.RootfsProbeService
```

The notification describes the ongoing isolated check. A ten-minute elapsed
time limit interrupts the worker; its partial wake lock also expires then.
Stopping/destroying the service interrupts it. Android killing the process
can leave a `RUNNING` report and incomplete stage; neither means success.
A new launch resumes the same transaction. All results and partial data remain
available for inspection; there is no automatic recursive cleanup by this probe.
The transaction itself reclaims only its recognized incomplete stages.

Read these files using `run-as app.foldgpt` and a binary-safe host capture:

```text
files/.rootfs-proot-install-probe/report.json
files/.rootfs-proot-install-probe/inventory.json
files/.rootfs-proot-install-probe/files/.foldgpt-install/fresh/journal.v1
```

The actual test root is beneath
`files/.rootfs-proot-install-probe/files/.foldgpt-install/fresh/stages/rootfs-UUID/root`.
The nested `files` directory is provided by a debug `ContextWrapper` overriding
`getFilesDir()`; the unmodified `AndroidRootfsTransaction` adapter consumes it.
The real `files/debian` is inspected with `lstat` only before and after, never
traversed or written. A probe-local `files/debian` must remain absent.

`PASS_PREPARED_INACTIVE` is emitted only after actual extraction, directory/file
sync, receipt commit, closing/reopening the transaction without a second input
read, a complete no-follow inventory and regular-file hash pass, matching
existing-runtime identity and a final absence check on the probe's activation
pointer. The report and inventory share a random `runId`; the report includes
the exact inventory digest. `FAIL`/`CANCELLED` preserves the exception class,
message and cause chain, with further details in tag `FoldGPT-RootfsProbe`.
Do not hide an Android DAC, symlink, filesystem API or `fsync` failure.

## Independent coordinator checks

Record the started run's ID/PID. Verify both before and after that the original
runtime still has the same PID and directory/link identity, and that the probe
local `files/debian` is absent. A report alone does not establish task continuity.

Retrieve the two JSON outputs and compare every member against the independently
parsed host archive:

```sh
python -B tools/install/transaction/verify-android-inventory.py \
  --archive downloads/install/debian-13-arm64-dd0aac2065057596/debian-13-arm64-rootfs.tar.gz \
  --report RETRIEVED_REPORT.json --inventory RETRIEVED_INVENTORY.json
```

The Python verifier uses tarfile, not the Java extractor. It requires the
pinned archive hash, output hash/run identity, inactive success state, exact
path inventory, permissions, mtime (microsecond precision), file contents and
symlink targets. It explicitly distinguishes native hardlink inode equivalence
from the pinned PRoot storage representation. For the latter, it requires the
20,240 logical names plus exactly four generated internals with expected
targets/data/modes. It does not claim attestation of an untrusted report.

Also inspect the actual prepared root from a separate `run-as` shell: `lstat`
or `stat` `usr/bin/env`, `usr/bin/dash`, `usr/share/X11/xkb/rules/evdev` and
`var/lib/dpkg/status`; compare their `sha256sum` values against the host archive.
Use `readlink` for guest absolute symlinks; do not follow them from Android into
host paths. Inspect both hardlink groups' host intermediate/backing paths,
then separately check their guest inode/count/behavior with the debug-only
`ProotStorageProbeService`. This independent observation must use the recorded root path after
checking it lies under the fixed diagnostic prefix, not an arbitrary path from
an untrusted result. The archive inventory requires no ARM execution; the
separate storage semantics test deliberately runs bounded ARM64 fixtures.

Passing establishes Android preparation and resume for this exact base. It
does not prove fresh runtime activation, guest execution, client installation,
keyring creation, Remote, upgrades or the near-one-click product flow.

Actual result: `PASS_PREPARED_INACTIVE`, run
`8bd6790e-8c9b-479f-94e0-fd1726da7923`, UID 10412. The prepared root's original
runtime identity is unchanged and the diagnostic activation pointer is absent.
The independently compared inventory has SHA-256
`3daee6d058faf162bc500d02b7dc786d3bb9ccaafc5f37f47da4fef263260f0e`.
There are 20,244 physical entries and 958,101,116 regular bytes. Resume and
inventory took 5.4 seconds; this is not a fresh-download/install timing claim.

Two real Android differences were fixed: Java no-follow link timestamp updates
failed with ELOOP (now native `utimensat`, target preservation verified), and
kernel hardlinks returned EACCES (now the explicit PRoot storage backend,
verified by actual guest operations; see `proot-hardlinks.md`). An initial
inventory run stopped at the old logical count ceiling; the fixed probe now
counts the four required physical internals, each independently verified.

The current host transaction suite passes 16 unprivileged JVM checks, including
real child-process termination during PRoot storage conversion.

## Packaging checks

`verifyRuntimeLibraries`, required by Android `preBuild`, accepts exactly the
five named PRoot/talloc/shared-memory inputs under `native/runtime`. An initial
check actually rejected a stale historical `libfoldgpt-probe.so`; it was moved
to ignored local evidence storage, without deleting it or changing the runtime
libraries. The gate prevents a similar leftover entering a future build.

`python tools/install/verify-apk-contents.py APK [--debug]` inspects the actual
ZIP and DEX contents. Both rebuilt variants pass; release contains seven native
libraries (the five inputs, Xlorie and the JNI installer) and none of the debug
probe classes or executables. Debug and release builds, including release vital
lint, pass. The local unsigned release artifact is a packaging test only.
