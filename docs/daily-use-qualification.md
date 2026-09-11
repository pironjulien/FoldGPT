# Daily-use qualification

FoldGPT's immediate release gate is **stable, restartable, installable**. New
DeX, Remote, second-screen and multi-agent work waits for these gates. A built
APK, passing host tests or a visible desktop does not qualify daily use.

## Candidate record

Keep one record per candidate: source revision and local diff, APK SHA-256,
version code, signing certificate SHA-256, native input inventories, guest
engine/client fingerprints, device build, and test evidence. Generated artifacts
and raw device evidence stay under `work/` or `downloads/`, outside Git.

The latest device-qualified *bounded baseline* is r46/versionCode36. R45 recovery
returned to ready after a controlled owner/service crash in 18.286 seconds;
explicit stop stayed stopped for 122 seconds. R44 verified accented text and a
4,096-character insertion. These observations do not transfer automatically to
a new APK or prove extended sleep, two active conversations or fresh installation.

## Gate 1: sessions survive daily use

Run on the physical display, with stock process protection, realistic battery
settings and normal Android background use. Use two new disposable test projects;
do not send account details or unrelated private files to a model.

| Scenario | Required evidence and pass condition |
| --- | --- |
| Cold launch and project access | Client reaches ready; a real Codex command creates, reads, edits and rereads a file in its native project. No EACCES, duplicate owner or repair from a PC. |
| Two conversations | Both can do useful work in independent projects. Distinct persistent JavaScript values and working directories remain separate after switching between them. Results, exit status and saved files agree. |
| Ten-minute background | Leave the app for at least ten minutes, then return. The UI and keyboard work; completed work remains readable; any interrupted operation is explicitly reported. No silent request or tool replay. |
| Extended session | At least two hours of representative editing, real commands, idle periods and app switching. Compare idle and peak process/memory observations. No monotonic accumulation of owner threads or helper generations. |
| Fold and focus | Real fold/unfold, keyboard show/hide, display/activity recreation, selection, paste, accented text, cancel and first key after return all work. Do not simulate fold posture with ADB overrides. |
| Repeated start/stop | Ten cycles, including rapid Stop during startup and delayed conversation/connector activation. Old generations finish before new ones launch; explicit Stop stays stopped; no activation escapes cleanup. |
| Interruption | Record genuine background interruption and separately controlled owner/service crashes in test work. Recovery preserves project bytes and desired run/stop state. Active tools are never reported complete without their actual result. |
| Process pressure | Record the effective global phantom limit and monitored-child population separately from FoldGPT UID counts, peak helper use, PSS coverage and Android trim events. No changing or disabling the global limit. |

The durations and cycle counts above are acceptance workloads, not new runtime
timeouts. A stopped process is not proof its descendants exited. An idle
conversation can still own a live terminal or persistent JavaScript state.

### Read-only measurements

Before and after each device campaign, use explicit, previously identified ADB
transport and hardware identity:

```sh
python tools/runtime/collect-device-baseline.py \
  --serial "$ADB_SERIAL" --expected-device-serial "$DEVICE_SERIAL" \
  --expected-model "$DEVICE_MODEL" --output work/qualification/before.json

python tools/runtime/inspect-android-memory.py \
  --serial "$ADB_SERIAL" --output work/qualification/memory-before.json
```

Choose new output names for later observations. The first command refuses a
different device before inspecting the application. It records only selected
system properties, FoldGPT process names/IDs and package version; no conversation
text or screenshots. The second checks PID/start-time identity and reports
partial PSS explicitly. Both are sequential observations; unreadable/hidden
processes remain a coverage limit. The UID count is **not** the global phantom
count and must never be subtracted from the phantom limit to claim free slots.
Inspect Android's phantom-process list and relevant trim events separately during
the real campaign, keeping private raw output out of the public report.

## Gate 2: install from declared inputs

- Build in a clean checkout with explicit toolchain, runtime libraries, X11,
  transport, executor assets and signing identity. Preserve the generated input
  descriptor, checksums, verifier results and APK certificate.
- Acquire the pristine Linux base and official client using their independently
  authenticated metadata. Never distribute an authenticated development rootfs.
- Complete the inactive-install coordinator: version the guest integration format
  shared by Python and Android, install the separate GNU engine and companion,
  assemble required guest audio dependencies and activate only a fully validated
  fresh root. No undocumented preinstalled files.
- On a clean supported device, install the candidate and complete a real Codex
  file-edit task. Test interrupted downloads/install, insufficient storage and
  retry. Existing projects and account data must remain unchanged on refusal.
- A candidate that updates an existing development runtime must be labelled an
  **update candidate**, until the fresh-install sequence itself passes.

### System-preservation checklist

| Check | Required before/after evidence |
| --- | --- |
| Bootloader | `ro.boot.flash.locked` and `ro.boot.vbmeta.device_state`, when exposed; compare with the recorded baseline. |
| Verified boot | `ro.boot.verifiedbootstate`; no boot/system/vendor changes are part of installation. |
| Knox | `ro.boot.warranty_bit` / `ro.warranty_bit` where readable. A missing property is unknown, never `0`. |
| One UI | Device fingerprint and `ro.build.version.oneui`, with any intervening OS update recorded separately. Launcher and ordinary Android navigation still work. |
| Samsung Pay | Maintainer confirms it works on the existing Fold. For a new qualification campaign, record the real functional check separately; boot properties do not test payments. |
| Data | Before/after hashes or scoped inventories of pre-existing project files and relevant account stores. Publish only redacted evidence. |
| Signature | Update certificate matches the installed package. Never uninstall an existing app just to bypass a signature mismatch. |

## Gate 3: safe official-client changes

The official desktop client, FoldGPT Android host, separate GNU engine and
workspace integration are independent artifacts. Keep each version/fingerprint
in the record. A changed official ARM64 package is a compatibility candidate,
not permission to rewrite or activate the client.

Validate the official signed repository metadata before admitting a new package.
The ASAR adapter accepts only a known original or bytes reproduced from its
verified original backup. An editable receipt cannot approve unknown bytes.
Unknown payloads must fail before AGENTS/context synchronization, keyring unlock
or client launch. Test interrupted adapter publication and recovery before
qualifying real updates. The fresh-root transaction is not an in-place updater
or a general rollback mechanism.

Include client-admission latency in the cold-launch measurement. The current
read-only checks independently hash the ASAR and its preserved original; DBus
re-execution adds repeated reads. Their startup cost on Android has not yet been
measured against the existing startup deadline.

Then repeat local tool access, two conversations, background/recovery, keyboard
and project-preservation checks against the new payload. A daily maintainer
monitor observes official ARM64 metadata and reports changes; it never activates
updates automatically.

## Current open boundaries

On 11 September the known Fold was not reachable through an authorized transport;
the only visible Wi-Fi ADB endpoint was unauthorized and was not identified as
the Fold. No new phone stability, payment, installation or sleep result is
claimed. Host concurrency tests and the candidate build can proceed independently.

The existing engine recovery patch already contains cached lazy MCP startup and
an Android three-minute unsubscribe unload policy. The historical r34 delivery
receipt binds that patch to the separate engine. The current service still sets
that policy; this is not a new improvement in this campaign. Cold caches,
explicitly selected plugins and live stateful sessions still consume resources.
Safe state retention and the actual process savings require device measurements.

The service's legacy orphan reaper also remains a review boundary: it enumerates
readable same-UID processes and signals numeric PIDs. That is not a complete
kernel ownership proof, and the native cleanup receipt must not be conflated with
its candidate count. This campaign's activation race and executor-lifetime fixes
do not establish complete orphan reclamation under every Android restriction.
