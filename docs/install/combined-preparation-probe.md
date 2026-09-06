# Actual combined inactive preparation probe

`CombinedPreparationProbeService` is a debug-only, `android.permission.DUMP`
protected service in its own `:combinedProbe` process. It calls the real
`AndroidInactivePreparation.prepare(..., ClientInput)` entry point twice. It
does not implement a second package installer or substitute success callbacks.

The first call prepares the authenticated Debian base, provisions its account,
installs and verifies the intact official client, prepares the isolated Android
vault and verifies the supervised guest GNOME collection. The second call uses
an archive supplier that always throws and a null package source, exercising
the coordinator's actual source-free recovery through the retained package.
Neither call activates the root, starts a display/client, opens a model task or
modifies the prototype runtime.

## Fixture isolation and inputs

The launcher supplies only a random fixture UUID and the SHA-256 of the reviewed
fixture descriptor. There is no Intent-selected path, shell command, rootfs,
Keystore alias or activation option. All input filenames are fixed beneath
`cache/combined-input/<uuid>`. The descriptor carries exact artifact identities,
resource bounds and deadlines. The DUMP-authorized host runner is the fixture
trust authority; this is not a production descriptor acquisition mechanism.

Durable state lives under `files/.combined-probes/<uuid>/`. Its `files` and
`noBackup` children replace those methods in an isolated Context. A separate
short cache directory is generated directly under Android's app cache, keeping
GNOME's translated control socket within Linux's pathname bound. The fixture
records that directory's identity and its own inode before provisioning; a
missing/replaced cache or mismatching descriptor refuses reuse. No live vault
ciphertext is read, imported, overwritten or deleted. Android's existing
nonexportable Keystore alias may protect the independent fixture ciphertext,
as in the previously verified keyring probe; no alias is deleted or replaced.

The earlier `.guest-account-probe` stage has a keyring-only v1 coordinator
journal. This probe deliberately creates a separate transaction rather than
converting that evidence into a v2 client installation. It preserves both the
old probe and `files/debian`. The new fixture and failed reports are retained
for investigation; the runner never recursively cleans a stage or user tree.

The local preparer uses the already independently authenticated base and client
26.901.41600 identities described in [official-client-input.md](official-client-input.md).
It streams their hashes before generating a bundle. It snapshots the exact
repository helper sources with canonical LF and binds those bytes in the
descriptor. Large base/package inputs are referenced in the local staging plan
and verified again before upload, avoiding another local archive copy. This
does not adopt a moving `latest` endpoint or qualify a newer package.

## Prepare and execute

The commands below reproduce the reviewed debug-device flow. The implementation
agent prepared it without device access; the coordinator subsequently built,
installed and executed it on the Fold. Actual results are recorded below.

From `C:\Dev\ChatgptFold`, prepare a new reviewed fixture:

```powershell
python tools/install/combined-probe/prepare.py `
  --archive downloads/install/debian-13-arm64-dd0aac2065057596/debian-13-arm64-rootfs.tar.gz `
  --package downloads/chatgpt_arm64.deb
```

The defaults allocate 15 minutes to each package call and one hour to the whole
fixture, including fresh extraction and two keyring calls. Both deadlines are
explicit test bounds, not performance targets. Override the preparer's deadline
arguments before generating the descriptor when a different measured budget is
needed; do not change a bound fixture in place.

One concrete bundle is ready at
`downloads/install/combined-probe-864a7994fbfb496195ae750236d1c2a6/staging-plan.json`.
Its fixture UUID is `864a7994fbfb496195ae750236d1c2a6`, and descriptor SHA-256 is
`96003cb201547a8f6156c4d6f189aa1b09006a5bd59a4143727c36e54525b30b`.
The bundle contains only the descriptor and canonical helper snapshots; the
large source paths in the plan remain local, private diagnostic data.

Build/install the reviewed debug APK using the canonical project build flow.
Check that the new service is registered only in the debug manifest and absent
from the release DEX/manifest. The existing APK diagnostic-class gate now
includes `CombinedPreparationProbeService` and `CombinedPreparationFixture`;
run that gate on the rebuilt debug and release APKs before recording separation.
Then use the actual connected ADB serial:

```powershell
python tools/install/combined-probe/stage.py --serial R3GL808JN4A `
  --plan downloads/install/combined-probe-864a7994fbfb496195ae750236d1c2a6/staging-plan.json `
  --start
```

The staging command validates local inputs first, copies only into the derived
fixture input directory as the app UID, checks each device SHA-256 and publishes
completed copies. Matching existing inputs are retained; different published
inputs fail. It requires no Android root and does not install an APK. Omit
`--start` to stage only. The wrapper and actual Android service were both used
for the recorded device run; a prepared staging plan alone is not that evidence.

Read the structural report without opening the vault:

```powershell
adb -s R3GL808JN4A shell run-as app.foldgpt cat `
  files/.combined-probes/864a7994fbfb496195ae750236d1c2a6/report.json
```

For another service invocation on the same fixture, reuse the exact UUID and
descriptor hash. Retained input files may remain present; its **second internal
call** still cannot open the archive source or receive an external package
source. To test an interrupted whole invocation with source files unavailable,
first preserve/rename only its `base.tar.gz` and `package.deb` inputs after the
existing stage is actually PREPARED and its package ledger has retained the
package; then launch the service directly with the same UUID/hash. Never remove
inputs or kill a process during unverified extraction merely to manufacture a
recovery result.

## Success, interruption and authentication

`PASS` requires two successful calls, actual `PREPARED` transaction state,
absence of any activation pointer, `COLLECTION_PREPARED` coordinator state,
and agreement between the returned client receipt, durable report and v2
journal. Independent Android inspections compare root and retained package
device/inodes, account identity, coordinator UUID/report hash, ciphertext hash,
collection intent hash and collection UUID across both calls. The real
coordinator performs package integrity/dependency/repository checks and the
real GNOME lock/unlock verification on each call. The probe never prints the
credential, exception payloads, guest command output or environment.

Android unlock is an actual `KeyringVault` prerequisite. The package step runs
before that prerequisite, so a locked device can still complete and durably
record `CLIENT_PREPARED`. If the vault then refuses because Android is locked,
the report says `WAITING_FOR_ANDROID_UNLOCK` and records independently observed
client report/journal evidence where available. It does **not** claim a prepared
collection or successful combined flow. Once the user has normally unlocked
Android, relaunch the same fixture to resume. The service cannot and does not
bypass Android authentication.

Deadline/service cancellation interrupts the worker; the existing coordinator
process wrappers terminate and wait for their owned PRoot processes. A cancelled
package mutation is not rolled back. A report records `CANCELLED` or `FAIL` with
phase and structural error type, while the transaction/package journals remain
the recovery authorities. It never marks a failed guest operation successful.

## Validation performed during implementation

The service, its descriptor parser and the complete installation Java sources
compile against the actual Android API 37.0 SDK. Thirty-four parser checks pass,
covering missing/duplicate fields, descriptor hashes, UUID path escapes,
unknown command fields, CRLF, malformed digests and numeric/deadline overflow.
These tests do not simulate package installation or keyring success.

Compiler/parser evidence is in
`downloads/install/combined-probe-compile-4b7c6663425843cbb33bcdb730f417e1`.
The preparer also validated both real large artifact hashes and produced the
concrete bundle above. Complete runtime validation, GPU integration, protected
commands, lifecycle and activation remain separate unfinished installation
requirements.

## Actual Fold result

The coordinator installed debug APK SHA-256
`3184494bb8fee16c73d051e298ed9e69abdf544054d0c462b3c6d70d9273893a`
and invoked the exact fixture above under Android UID/GID 10412. Both complete
calls passed in 219,012 ms total. The base archive was opened exactly once; the
second call's archive supplier refuses access and its package source is null.
The stage remains `PREPARED`, the coordinator is `COLLECTION_PREPARED`, and no
activation was attempted.

The two independently inspected snapshots agree on the root inode
`65097:298005`, retained package inode `65097:317759`, guest account, coordinator
identity, official package report, ciphertext hash and GNOME collection identity.
The host then reread the actual report/journal and checked both inodes through
ADB, as well as the staged official Codex executable's unchanged SHA-256.
No credential or vault ciphertext was copied into this evidence.

Private evidence: `downloads/install/combined-device-20260906/`.
The structural report SHA-256 is
`a1b7ae49b99c5762ce337debea3beef06252e40087971417ad7afd54891ce751`;
the actual package report is
`d192a82d2cda8b770c4043f59db3d1cee2ecbcaca163d5b8174fbee6f5f58898`.
The new debug/release APKs pass the diagnostic/native-library separation gate;
only debug was installed. The containing root, client and vault are independent
of the existing development runtime and remain inactive.
