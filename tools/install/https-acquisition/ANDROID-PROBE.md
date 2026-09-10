# Android HTTPS acquisition probe

`NativeHttpsAcquisitionProbeService` is a debug-only, fixed-input diagnostic of
the actual `AndroidTrustedHttpsArtifact.acquireClient` adapter. It acquires the
official client over HTTPS in a new private cache and calls the same adapter a
second time to verify reuse of the published artifact. It does not install,
prepare or activate a client, access an existing profile or keyring, modify a
rootfs transaction, or change Android security settings.

The implementation is
`android/app/src/debug/java/app/foldgpt/NativeHttpsAcquisitionProbeService.java`.
The first Android execution on 2026-09-06 failed before networking: Android's
managed cache had mode 2771, so its newly created evidence directory inherited
2700 despite the requested 0700. The strict mode check then correctly refused
it; the same check prevented final evidence writing there. The integrator's
original logs, stats and APK are preserved unchanged in
`downloads/install/https-acquisition/android-cb8b011a`; the failed private leaf
is `cache/https-9147257979820243278` and the APK SHA-256 is
`cb8b011aecca18027cbad011f8ee4982c3552c225e906a990f41f39b80db14be`.

The corrected service and acquisition adapter explicitly finalize permissions
on newly created directory inodes, as described below. The 19-test nonroot
Linux suite and actual Android adapter compilation pass in
`downloads/install/https-acquisition/foldgpt-https-java-dUfNMcSD`. That suite
reproduces actual setgid inheritance and verifies exact full modes. A new APK
and Android rerun are still required; host PASS does not replace that device
evidence. The parent integration owns the manifest, APK build/install, device
run and independent evidence collection.

## Fixed authority and input

The debug manifest must declare the following service. The service checks its
actual declared permission, exported status, process name and running process
name before starting a worker.

```xml
<service
    android:name="app.foldgpt.NativeHttpsAcquisitionProbeService"
    android:process=":httpsAcquisitionProbe"
    android:exported="true"
    android:permission="android.permission.DUMP"
    android:foregroundServiceType="specialUse">
    <property
        android:name="android.app.PROPERTY_SPECIAL_USE_FGS_SUBTYPE"
        android:value="ADB-only fixed official HTTPS artifact acquisition and private verified-cache reuse diagnostic" />
</service>
```

The existing application requires `INTERNET`, `WAKE_LOCK` and the foreground
service permissions. This is a separate process under the ordinary app UID;
it is not an Android `isolatedProcess` with a separate isolated UID. DUMP gates
the exported service to the authorized shell/system caller. No root operation,
bootloader change, certificate installation or trust override is involved.

The invocation accepts no extras, URI, clip data, selector or categories. Its
action may be absent or exactly `app.foldgpt.action.PROBE_HTTPS_ACQUISITION`.
It cannot select a URL, filesystem path, descriptor, command or account through
an Intent. A concurrent start does not launch another worker; a later run uses
another fresh cache.

The exact client input is copied from the existing v3 fixture in
`tools/install/combined-probe/prepare.py`:

| Field | Trusted value |
| --- | --- |
| Version | `26.901.41600` |
| SHA-256 | `8d5141b299ca593255fa25760895e84375937cc305197528c822dfa71ac2a3bf` |
| Package bytes | `388651910` |
| Maximum tar bytes | `1365770240` |
| Maximum members | `7360` |

The adapter reads the URL from the existing
`AndroidInactiveClientInstaller.Descriptor.json().sourceUrl`. The service does
not duplicate or replace that endpoint. A mutable `latest` response that has
changed since the trusted descriptor must fail the exact size or digest check.
Do not authorize a newly computed response hash as a way to make this run pass.

## Acquisition and independent checks

Each invocation creates `cache/https-<random>/` with mode 0700, then an empty
0700 `acquisition-cache/`. Immediately after each successful creation, the
service opens the new path with no-follow/nonblocking flags, requires the
expected app-owned directory device/inode, and applies `fchmod(fd, 0700)`.
It verifies the full resulting mode and unchanged identity/GID before fsync.
This clears inherited setgid on the new inode only. It never chmods or chowns
the Android managed-cache parent or an existing fixture. The report records
the parent's before/after metadata and verifies preserved UID/GID, device/inode
and full mode; its size may legitimately change as a directory gains a child.

The production acquisition storage uses the same new-directory rule for its
own two cache levels and checks full mode bits on existing directories/files.
An existing directory with special bits fails unchanged instead of being
accepted through the incomplete Java POSIX-permission view or normalized.
A `ContextWrapper` overrides only `getCacheDir()` so
the real adapter acquires into that fresh cache. The existing application cache,
client and profile are not used as the acquisition fixture.

The first actual adapter call uses 15-second connect, 30-second read and
20-minute total acquisition deadlines. It must report positive, strictly
increasing downloaded-byte progress ending at the exact package size and
return `resumedFrom == 0`. The service independently reads and hashes the
returned file, requiring the exact descriptor size and digest, app ownership,
a regular 0600 file with one link, and unchanged device/inode and size during
the read. It also checks the exact descriptor-derived private cache path.

The second actual call uses the same descriptor and cache with a 3-minute
total acquisition deadline. Only for this synchronous call, the worker uses
`StrictMode.detectNetwork().penaltyDeathOnNetwork()`. An attempted Java network
operation on that worker throws instead of proceeding. The original thread
policy is restored in `finally`. A body-download progress callback independently
fails the call if invoked. The existing adapter and acquisition core perform
network work synchronously on that thread, and their published-cache branch
rehashes and returns before the network branch.

PASS requires successful return through that guard, zero second-call progress
callbacks, the same path and descriptor cache key, `resumedFrom == 0`, a second
independent exact file hash, the same artifact device/inode, and no competing
`download.part`. This is evidence about the real component's guarded Java call,
not a firewall or a proof that the entire app UID transmitted no traffic.

Supplementary `TrafficStats` samples are labeled as shared-app-UID byte
counters, not HTTP request counters. Unsupported counters, resets and API
unavailability are recorded without being interpreted as zero traffic or
causing the actual acquisition to fail.

## Device run and evidence collection

After the integrator has included this debug service and installed that APK,
an authorized shell can start the fixed invocation:

```text
adb shell am start-foreground-service -n app.foldgpt/.NativeHttpsAcquisitionProbeService -a app.foldgpt.action.PROBE_HTTPS_ACQUISITION
adb logcat -d -s FoldGPT-HttpsProbe:I
```

The log announces `RUNNING evidence=<private path>` and a terminal status when
the report has been persisted. Collect only the exact announced diagnostic
leaf with the existing authorized debug `run-as` mechanism. Do not scan or
export the application's account, profile or keyring files. The private package
cache remains on the device for verification; a structural report is sufficient
for ordinary host evidence collection.

Files in the evidence leaf are owned private 0600 regular files. Each report
write forces a fresh temporary file, atomically replaces its named report and
synchronizes the parent directory:

- `report.json`: initial RUNNING report, a checkpoint after the independently
  verified first acquisition, then terminal PASS, FAIL or CANCELLED.
- `progress.json`: actual received/expected byte counts and elapsed time,
  persisted at most once every 5 seconds, plus the exact final body count.
- `android-completion.txt`: terminal status, UID and SHA-256 of the exact final
  `report.json` bytes, including its final newline.

The terminal report contains deadlines, duration, phase, expected descriptor,
actual file hashes, byte counts, modes, link counts, device/inode identities,
cache reuse observations, bounded error chains and a bounded private cache
inventory. It contains no downloaded package body or account contents. An
inventory error is retained and turns a would-be PASS into FAIL without
preventing the terminal evidence write.

The collector must verify the completion marker against the actual report
bytes and UID; reject a stale RUNNING report, an absent/mismatched completion
marker, a non-PASS status or a failed cache-network guard. Preserve the built
APK/source hashes and device execution identity alongside that evidence. Do
not treat the first progress file, downloaded-byte count or an HTTP success
alone as successful verification. Final process/service state should also be
checked independently after the terminal marker.

## Lifetime and limits

The foreground service uses a partial wake lock with a 25-minute plus
30-second automatic timeout. The worker checks a 25-minute overall deadline;
a handler also requests cancellation when that deadline expires. Lifecycle
destruction and deadline cancellation set a flag, interrupt the worker and
dispatch the acquisition token's potentially blocking `disconnect()` on a
separate daemon cleanup thread. The Android lifecycle thread does not wait on
socket disconnection.

Finalization synchronizes with cancellation and clears any pending worker
interrupt before writing its terminal evidence. `workerFinalizationReached`
means exactly that; it does not assert that the worker or daemon cleanup thread
has already exited. Wake lock cleanup cannot prevent posting foreground/service
cleanup. Android process death, force-stop or storage failure can still prevent
a final report; absence of a valid completion marker remains inconclusive or
failed evidence, never PASS. This probe does not weaken Android's process or
network confinement to ensure completion.

No release-discovery UI, resumable invocation across separate fresh probe
runs, browser qualification, GUI/GPU validation, runtime activation or official
client installation is certified by this diagnostic. The component's separate
host tests cover interruption/resume and TLS rejection; see `README.md` for
that bounded evidence.
