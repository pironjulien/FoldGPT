# Procps boot-time correction candidate

This is a source patch to GNU `ps` from authenticated Debian procps
`2:4.0.4-9`. It does not alter the official ChatGPT/Codex client, install a
replacement `/proc`, intercept file contents, suppress stderr, or change any
Android permission. **It is not installed on the Fold.**

## Cause established

The actual Electron sampler command in the recorded device log is:

```text
ps -p <live child pids> -o pid=,ppid=,%cpu=,rss=,lstart=,command=
```

Its error is `ps: Unable to get system boot time`. In the authenticated source,
`src/ps/output.c:boot_time()` calls `procps_stat_new()`, which primes its data
by opening `/proc/stat` (`library/stat.c:stat_read_failed()`). The `lstart`
formatter depends on this boot epoch. A read-only check on the Fold under
`run-as app.foldgpt` confirmed `/proc/stat` returns `Permission denied`.

The same check's guest Python read real kernel clocks successfully:
`CLOCK_REALTIME=1788723778.9970155`, `CLOCK_BOOTTIME=17019.072220797`,
`CLOCK_MONOTONIC=17019.07222111`. These values are diagnostic observations,
not build constants. No phone file or setting was modified for this audit.

Debian already carries the upstream patch `library_use_clock_gettime`, marked
`Applied-Upstream: 4.0.5`, replacing `/proc/uptime` with `CLOCK_BOOTTIME` for the
process library's elapsed-time accounting. That patch does **not** fix the
independent `ps` `lstart` boot-epoch lookup. This candidate fixes that remaining
dependency, within `ps`.

## Measurement and error handling

Normal Linux behavior retains `/proc/stat`. Only access/missing-interface errors
`EACCES`, `EPERM`, or `ENOENT` permit the alternative clock measurement.
Allocation errors and other failures still abort.

The helper samples `CLOCK_REALTIME`, `CLOCK_BOOTTIME`, then `CLOCK_REALTIME`
again. The two realtime samples bound the possible epoch corresponding to the
boot-time sample. It returns a whole epoch second only when both bounds fall
in the same second. It uses neither a tolerance constant nor a guessed boot
date. Ambiguous samples fail with `EAGAIN`; invalid/reversed samples fail with
`ERANGE`; clock syscall errors propagate. The caller retains a nonzero exit
and its normal `Unable to get system boot time` diagnostic if no valid time is
available. The existing `ps` per-invocation timestamp cache remains.

`CLOCK_BOOTTIME` includes suspend, matching Linux `/proc/PID/stat` starttime.
Using `CLOCK_MONOTONIC` would incorrectly shift process start dates after a
suspend and is deliberately not used. The arithmetic tests exercise this
distinction; **no actual suspend or phone clock adjustment was performed**.

A completed wall-clock change moves the current realtime-to-boottime mapping,
as it does for kernel `btime`. Neither this measurement nor `btime` reconstructs
the civil time that a process originally saw before past clock corrections.
A detected change/large scheduling gap inside the sample is rejected. Opposite
clock steps entirely between samples, time-namespace anomalies, and historical
clock changes cannot be reconstructed from these three reads. The Android
integration must retain matching process/kernel time namespaces.

## Source and reproduction

`source-lock.json` pins the three source files recovered from the existing
authenticated Debian corresponding-source bundle. Their byte counts and
SHA-256 were rechecked before extraction. `output-source.sha256` rejects an
unknown `output.c`. `make-patch.py` creates a reviewable patch without changing
the source input. The patch adds a header to the upstream source distribution
list and changes only the boot-time lookup.

From an environment with GCC, Python 3, `dpkg-source`, Autoconf, Automake,
Libtool, Gettext/Autopoint, and pkg-config installed:

```sh
bash tools/runtime/boot-time/run-linux-tests.sh
```

The harness builds original and patched GNU ps from the same Debian source,
as UID 65534 when started in a privileged build environment. Compilation and
tests themselves are nonroot. No `make install` is run. Build products stay
in a fresh `/var/tmp/foldgpt-procps-boot-*` directory; a verified copy of the
test sources, logs, binaries and report is exported beneath ignored
`downloads/runtime-boot-time/`.

The live fixture uses **real Landlock rules** to deny reads of `/proc/stat`
while permitting process-file reads and proc directory enumeration. It confirms
the kernel's `EACCES` and readable `/proc/self/stat` before running the actual
ps binary. This is a focused Linux permission test, not an emulation of all
Android restrictions. Test fixture messages are retained separately from ps
stderr; no error output is discarded.

Tests cover original failure reproduction, unchanged unrestricted output,
recovered sampler fields for a real parent/child with dates matching the real
kernel `btime` baseline, a later sample, unrelated argument errors, and 17
explicit deterministic clock arithmetic/failure cases under ASan/UBSan.

## Remaining integration work

The Linux result does not establish an Android fix. Before integration:

1. Cross-build the patched GNU component for the authenticated ARM64 runtime,
   preserve its build recipe, version/provenance and GPL corresponding source.
2. Execute it from the private development runtime on the Fold, retaining the
   original sampler output and error baseline. Verify actual process timestamps
   and elapsed CPU accounting across normal use and real suspend/resume.
3. Integrate through the versioned runtime artifact and installer/update paths;
   verify the official client hash remains unchanged.
4. Confirm a newly captured Electron sampler succeeds. Continue tracking the
   independent primary-runtime manifest 404, scheduler permission, GCM endpoint
   and other log categories. This patch does not establish clean logs.

The source addition and fixtures use GPL-2.0-or-later to match GNU ps. The
complete upstream and Debian source materials remain in the authenticated
corresponding-source bundle.
