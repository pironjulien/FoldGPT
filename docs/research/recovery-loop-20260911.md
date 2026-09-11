# Native-owner termination and blocked recovery — 11 September 2026

## Incident

The installed r46/versionCode36 became stuck displaying “Reprise de ChatGPT”.
Android's ActivityManager log recorded `Trimming phantom processes` at
19:51:45 CEST for both the native owner and the guest PRoot launcher. The Java
runtime survived. Its native transport recorded a real wait status of 9,
`bootstrapReaped: true`, `cleanupComplete: false`, and `ownerRetained: true`.

The recovery policy had charged one retry, but shutdown waited indefinitely for
a clean-close report from the dead owner. The recovery deadline was only checked
after cleanup or service recreation, so it could not advance this stalled state.
Other session processes remained alive. This was an Android process-budget kill
followed by a FoldGPT recovery defect, not a model response still running.

## Correction in r48/versionCode38

Observe native-owner death during both ordinary execution and cleanup. A real
wait, a positive bootstrap PID, retained ownership and missing cleanup evidence
authorize retirement of the containing Android runtime process. EOF, a timeout,
a live owner, admission refusal, and a clean exit do not grant that authority.

Before retirement, persist the existing retry or explicit-stop intent and close
admission to new activations. Reuse any retry already charged by the guest exit;
recreating the Java process does not extend the shared 90-second recovery budget.
Retirement is scoped to the current, sole retained generation. Delayed callbacks
cannot retire a newer or independently retained owner.

Android tears down that runtime's process group. FoldGPT does **not** manufacture
a clean native receipt or remove the old ownership marker. A recreated native
owner still requires the exclusive broker lock, matching workspace identity and
two complete kernel-assisted quiescence observations before archiving the marker.
Any survivor still prevents admission. The Android global phantom limit remains
unchanged; no root, bootloader, SELinux or process-protection setting is modified.

## Verification

- APK SHA-256: `945fdc769a71ee7d008b8e77a93809d264e22b9833d008ba470f2b52aad2cd51`.
  Updated the existing installation with the same signing identity; the installed
  APK hash matches the built candidate. The official client was not upgraded.
- 67 JVM lifecycle tests pass, including dead-owner classification, stale and
  overlapping generations, preserved retry budget, and explicit stop. The
  unchanged transport suite remains passing; candidate packaging and native/source
  inventories pass. No new native binaries were introduced by this correction.
- On the physical Fold, the test sent SIGKILL **only to the native owner**. Product
  code retired its Java runtime; the test did not signal the Java process, launch
  the app again, repair files or remove a marker after the fault.
- A new native owner and Java runtime reached client readiness. The last not-ready
  sample was at 25.34 seconds; readiness was observed at 44.88 seconds. This is a
  sampling interval, not an exact restart-time measurement.
- The original marker's bytes and inode were preserved in its recovery archive.
  The receipt retains `previousCleanupClaimed: false` and `previousBootEnded: false`
  and records two complete quiescence passes.
- All 355 existing project files and the 537,946-byte conversation prefix are
  unchanged. The original discussion opens again, with no active response replay.
  Real Android keyboard events entered `FoldGPT1618` into its empty composer;
  deletion restored the empty draft. No test message was submitted.
- The effective global phantom limit remains 32. UID process counts are not the
  global monitored-child count and do not establish spare process capacity.

Private evidence stays under `work/recovery-loop-20260911/`: the incident logs,
data backup, `r48/build-report.json`, `installed-apk.json`,
`owner-only-crash/result.json`, `preservation-verified.json`,
`keyboard-after-recovery.json` and before/after device baselines.

This qualifies recovery from the observed dead-owner failure. It does not prove
that Android will never trim FoldGPT again, preserve an in-flight tool as completed,
or qualify prolonged sleep, two simultaneous discussions and fresh installation.
Reducing peak process use remains a separate daily-use release requirement.
