# Prepared Android probe for coordinator v3

This uses the existing DUMP-only `CombinedPreparationProbeService` component.
No new service registration or release diagnostic class is introduced. The
fixture parser now distinguishes the original fixture schema v1 (coordinator
v2) and the new fixture schema v2 (coordinator v3). Both scopes require their
exact field sets; neither can adopt the other's descriptor or durable journal.

The original validated fixture is unchanged:

```text
fixture           864a7994fbfb496195ae750236d1c2a6
descriptor SHA    96003cb201547a8f6156c4d6f189aa1b09006a5bd59a4143727c36e54525b30b
coordinator       foldgpt.inactive-preparation.v2
input files       7
```

The new local fixture is ready, with no ADB performed by its preparation:

```text
fixture           8b654a63b6f64c138fe2a0da31594de8
descriptor SHA    c5f8bdfee5359e58f050f6d53c06aa21e43665c67f93dc43600721adbf118825
fixture schema    foldgpt.combined-preparation-fixture.v2
coordinator       foldgpt.inactive-preparation.v3
staging schema    foldgpt.combined-probe-staging.v2
input files       8
input bytes       757503640
```

Local plan:

```text
C:\Dev\ChatgptFold\downloads\install\combined-probe-8b654a63b6f64c138fe2a0da31594de8\staging-plan.json
```

The plan contains each absolute local input path, private device destination,
exact SHA-256 and byte count. The new payload is `integration.fgi`, with SHA
`d0d9f2edce1c194ae2188556922373bb8e66d9ae30e8f34197da54a51945c16c`,
41,116,761 bytes and manifest SHA
`a832faca1620125b00256271c236e12d07dc5972f3b403a24407559ca0b0feb0`.
The existing pinned Debian archive, intact official ARM64 package and four
canonical LF helpers are the other inputs. No existing runtime/profile is used.

## Local verification

```powershell
python -B tools/install/combined-probe/stage.py --plan downloads/install/combined-probe-8b654a63b6f64c138fe2a0da31594de8/staging-plan.json --validate-only
```

`--validate-only` authenticates all local inputs against the generated plan,
checks the schema/input set, and prints constructed launch arguments. It opens
no ADB connection. It also succeeds for the original seven-input v1 plan.

The parser has passed **70 checks** covering both schemas, missing or extra
fields, digest/size bounds, downgrade and unsupported schema refusals, malformed
identities, paths, commands, duplicates and CRLF. Both actual prepared
descriptors were then parsed independently (71 checks per invocation, including
the selected real descriptor). All production installation
classes, KeyringVault and both debug probe classes compile against Android
API 37. No APK installation or Android execution is implied by these host checks.

## Coordinator's next device action

Build/install the debug APK containing the current sources using the project's
canonical build/sign/install sequence. Keep the phone's existing runtime and
old fixtures intact. Then, with the already verified Fold serial and ADB path:

```powershell
python -B tools/install/combined-probe/stage.py --plan downloads/install/combined-probe-8b654a63b6f64c138fe2a0da31594de8/staging-plan.json --serial $foldSerial --adb $adbPath --start
```

Staging is idempotent: matching existing inputs are checked and reused;
differing existing inputs are retained and refused. Each new copy goes through
an app-private `.part` file and a device SHA check before publication. The
launcher constructs its command from validated identifiers, ignoring any
command text present in the plan.

The exact start arguments are:

```text
shell am start-foreground-service -n app.foldgpt/app.foldgpt.install.CombinedPreparationProbeService --es fixture 8b654a63b6f64c138fe2a0da31594de8 --es descriptorSha256 c5f8bdfee5359e58f050f6d53c06aa21e43665c67f93dc43600721adbf118825
```

The private report can be read with `run-as app.foldgpt` from:

```text
files/.combined-probes/8b654a63b6f64c138fe2a0da31594de8/report.json
```

It is written during execution and on completion/failure. The service owns a
partial wake lock and a bounded total deadline; cancellation interrupts its
worker and the existing process supervisor. It does not start Xlorie, the
client, browser or GPU and never calls runtime activation.

## Evidence required for a pass

The service calls the real v3 coordinator twice in the same isolated
files/cache/noBackup context, closing/reopening its transaction between calls.
First preparation installs native scripts/GPU files, checks native XKB, installs
the official client, and provisions the isolated vault/collection. The second
call uses a throwing base supplier and a null package source, but reopens and
reauthenticates the integration container. It revalidates real integration
files before running the client package verification or accessing the vault.

For the new fixture a pass requires:

- `schema = foldgpt.combined-preparation-probe.v2`,
  `coordinatorSchema = foldgpt.inactive-preparation.v3`, `status = PASS`.
- Two successful calls and two authenticated integration input opens.
- `baseAndPackageSourceFreeRetry = true`, `integrationRevalidationCalls = 2`.
  `sourceFreeRetry = false` is intentional because integration input is reread.
- Matching first/second root/account/client/vault/collection evidence and
  matching integration report SHA, report inode, input SHA, manifest SHA and
  exact inventory counts (29 installed entries and 316 Debian XKB entries for
  this pinned release).
- Root `PREPARED`, coordinator `COLLECTION_PREPARED`, no active `debian` pointer,
  `activationAttempted = false`, `gpuExecutionAttempted = false`.

The integration report is compared against the returned real coordinator
result, durable v3 journal and current guest/root identity. Its reported file
identities describe native filesystem checks, not claimed GPU execution. On
failure, any readable bound integration/client report is labeled as observed
evidence; it does not convert a failed run into a pass.

This is the final inactive preparation proof, not complete runtime readiness or
managed-executor security proof. Those require their separate real validators.
