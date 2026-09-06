# Fresh rootfs transaction

The Android installer now has a Java implementation for preparing a verified
Debian archive, recovering interrupted preparation and publishing a completed
runtime atomically. Sixteen unprivileged JVM tests pass. The Android adapter
also prepares and resumes the authenticated Debian base on the Fold, with an
independent full inventory comparison. **It has not been integrated into the
service's first-install flow**. The actual test Debian base remains inactive.

## Components and caller contract

- `RootfsExtractor` authenticates and extracts one pinned POSIX tar.gz archive
  into a new private stage. It does not publish a runtime.
- `RootfsTransaction` holds an interprocess installation lease and a durable
  state journal. It separates base preparation from explicit activation.
- `AndroidRootfsTransaction` uses `Context.getFilesDir()`, real `Os` ownership
  checks, `chmod`, inode identity and directory `fsync`. No root is involved.

The caller supplies a trusted `RootfsExtractor.Spec`: SHA-256, exact compressed
size, exact regular payload bytes, maximum uncompressed tar bytes and exact
logical member count. These values must come from authenticated release
metadata or a trusted APK input. Computing them from an unauthenticated download
does not establish trust. The current Debian manifest needs these totals added
before production consumption; the local validation used a separately pinned
artifact and recorded its totals only after checking that digest.

Open the transaction once and retain its `AutoCloseable` lease throughout
preparation, trusted guest provisioning and activation. Competing transaction
objects/processes fail while it is held. All runtime/installer entry points
must respect that lease before this becomes an integrated installer. No guest
may execute untrusted tasks in an inactive stage. Trusted, bounded provisioning
and validation may execute while its owner retains the lease. The files directory and its ancestors must
remain under trusted application control. This is not protection against
arbitrary concurrent native code with the same Android UID.

`prepare(ArchiveSource)` returns an inactive root and never calls `activate`.
Provisioning must then establish the complete guest identity, DNS, bindings,
native runtime, graphics driver, integration scripts, official client and fresh
encrypted keyring without importing a personal image. Call
`activate(ActivationValidator)` only with a validator that checks those actual
requirements. There is no default validator or production readiness claim.
After any operation failure, close and reopen the transaction to recover.

## Filesystem and crash behavior

The private layout below lives under Android's application files directory:

```text
.foldgpt-install/                  0700
  install.lock                   cross-process lease
  fresh/                          0700
    journal.v1                   durable state and trusted input identity
    stages/                       0700
      rootfs-<UUID>/              0700
        verified-input.tar.gz    private authenticated snapshot
        extracted.sha256         durable extraction receipt
        root/                    inactive guest tree
debian -> .foldgpt-install/fresh/stages/rootfs-<UUID>/root
```

The `debian` pointer appears only during activation. `Files.createSymbolicLink`
publishes it atomically with no-clobber semantics. Java `ATOMIC_MOVE` alone
cannot guarantee refusal to replace an existing destination, so activation
does not use it for `files/debian`. An existing installation, migration or
unrelated symlink is refused, including one created during activation. No
existing profile is merged or overwritten. The activated root remains in its
private stage; this is a fresh-install transaction, not an updater.

| Durable state | Recovery behavior |
| --- | --- |
| `NEW` | No root has been prepared. |
| `PREPARING` | Reclaim only recognized incomplete stages; reuse one complete receipt, or download again. Ambiguous complete stages fail. |
| `PREPARED` | Reuse the recorded root and inode without downloading; leave it inactive for trusted provisioning. |
| `ACTIVATING` | If no pointer exists, require validation again. If the exact recorded pointer and inode exist, complete the durable `ACTIVE` commit. |
| `ACTIVE` | Reuse the recorded pointer and inode; fail if they are missing or changed. Never silently reinstall. |

Journal writes force a private temporary file, atomically replace only the
transaction's own journal, and sync its directory. The journal records the
archive specification, storage backend, state, stage name and root device/inode. Its checksum
detects corruption; it is not authentication against the same UID. Metadata
symlinks, hardlinks, foreign owners and group/other-writable files are rejected.
Extraction flushes file content and directory metadata before its receipt.
Activation also flushes later provisioning changes before publishing its
pointer, syncs the application files directory, then records `ACTIVE`.

Abrupt process termination at the tested commit boundaries recovers correctly.
This is not a physical power-loss test of Android storage. A filesystem must
honor `fsync` and atomic link/rename semantics for the durability contract.
After activation the compressed cache is removed to reclaim its space.

## Archive handling

The extractor copies the download into a private file and verifies exact SHA
and compressed size. Tar framing validation and extraction read that same open
file descriptor, not a subsequently reopened download path. A bounded raw
framing pass validates ustar headers, checksums, supported types, PAX record
size, zero padding and two terminal zero blocks; it drains gzip to check its
trailer. Apache Commons Compress 1.28.0 supplies POSIX tar/PAX semantics.

The supported format matches `build_rootfs.py`: GNU tar POSIX output with `x`
PAX records, regular files, directories, symbolic links and hardlinks. Sparse
files, devices, FIFOs, global PAX/GNU extensions, absolute member paths,
traversal, normalized duplicates and undeclared/link ancestors are rejected.
Member count and regular payload size must exactly match the trusted spec;
uncompressed bytes are bounded separately.

Files and directories are written before any links. Absolute Debian symlink
targets are retained literally as guest paths; extraction and cleanup never
follow them into the host. Relative targets cannot lexically escape the guest
root. Hardlinks must refer to declared regular members with identical mode and
mtime. Cleanup walks only its own recognized stage, without following links.

Android's production adapter explicitly selects `proot-termux-l2s-7266fb3-v1`:
it moves each hardlink group's one data inode into PRoot's registered storage
representation. It does not duplicate file contents or silently substitute
symlinks after a failed native hardlink. The native POSIX backend is retained
for host callers; mismatched receipts/journals are refused. Absolute backing
targets require immutable stage paths. See [proot-hardlinks.md](proot-hardlinks.md).
Android symlink mtime uses no-follow `utimensat` through the small JNI module,
because the Java implementation fails on guest symlinks. Actual nanosecond
preservation and an unchanged target were verified under the application UID.

Modes, sticky/setuid/setgid bits and mtime are preserved. The host JDK applies
mtime at microsecond precision. Numeric archive UID/GID ownership is **not**
reproduced: files belong to the Android application UID, and no `chown` is
attempted. Guest identity/ownership mapping remains a separate provisioning
contract. Setuid bits on app-owned files do not grant Android root privileges.

## Reproducing the host checks

From WSL Ubuntu with Java 17, curl and an ext4 `/var/tmp`:

```sh
bash tools/install/transaction/run-jvm-tests.sh
```

The runner verifies six pinned Maven dependencies, snapshots the Java sources,
compiles them into a new ext4 directory and executes JUnit. When invoked as
WSL root, it runs the tests as `nobody`; that does not change Android. Sources,
hashes, versions and test output are retained in ignored
`downloads/install/transaction-check/`.

Sixteen tests pass, covering authenticated extraction and malformed archives,
modes and guest links, existing-install preservation, concurrent lease and
activation races, rejected validators, tampered metadata/specification and
recovery. Child JVMs actually terminate with `Runtime.halt(71)` after partial
download, extraction receipt, prepared-journal staging, immediately before and
after pointer creation, and after the active journal. Parent processes reopen
the transaction and independently read the resulting files. The test validator
only validates its fixture; it is not a production validator.

Five additional real child-process deaths occur after backing-file movement,
intermediate creation, source creation, alias creation and directory sync.
Every interrupted conversion leaves no completed receipt or activation; retry
reclaims only that incomplete stage and restores shared data in a new stage.
Activation/reopen preserves its absolute storage paths. Another test refuses
adoption through a different backend without modifying the original root.

A review found that directory modes `0000`/`0111` prevented reopening the
directory for flushing and reclaiming incomplete stages. Final metadata now
uses a directory descriptor opened before its restrictive mode, and abandoned
directory permissions are restored before enumeration. The added unprivileged
test exercises both modes, actual bytes and successful retry. Activation's
separate provisioning flush requires a runtime tree readable/traversable by
the owning app UID; inaccessible provisioned content fails activation rather
than changing its access permissions. The actual Debian artifact meets that
requirement.

The opt-in `RootfsRealArchiveCheck` prepares and resumes the actual Debian
archive without activating it or executing ARM code. Its CLI arguments are
`files archive sha256 compressedBytes payloadBytes maxTarBytes members`; its
classes and dependency paths are printed by the runner. Use a new private
Linux files directory owned by the test UID. Retain the resulting root for
independent verification:

```sh
python3 -B tools/install/transaction/verify-prepared.py \
  --archive PATH_TO_TRUSTED_ARCHIVE --sha256 TRUSTED_SHA256 \
  --root PREPARED_INACTIVE_ROOT
```

That separate Python/tarfile implementation compares all file bytes, modes,
mtime, link targets, hardlink inode identities and the complete path inventory.
It never extracts or executes anything and assumes the inactive tree stays
under exclusive trusted control while being checked.

The actual artifact tested on 6 September 2026 has SHA-256
`dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f`,
327,673,156 compressed bytes, 958,101,116 regular payload bytes,
977,131,520 tar bytes and 20,240 members. Preparation and reopening took about
73 seconds on the WSL host. These are host measurements, not Fold performance.
No Android first launch, account creation, keyring initialization, client
installation or production runtime activation is implied.
