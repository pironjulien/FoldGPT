# FoldGPT native memory observation, 6 September 2026

Read-only ADB observations at 23:43 Paris, retained in
`downloads/runtime/memory-20260906.json`, with the collector
`tools/runtime/inspect-android-memory.py`. Values vary with workload.

| Observation | Result |
| --- | --- |
| Kernel MemTotal | 11,351,456 KiB = 10.83 GiB usable by Android |
| Kernel MemAvailable | 3,733,340 KiB = 3.56 GiB |
| Sum of PSS across all 26 processes with FoldGPT UID 10412 | 1,390,800 KiB = 1.33 GiB |
| Main Android surface graphics, additional dumpsys accounting | about 116 MiB |
| Approximate total including that graphics accounting | about 1.45 GiB |
| Global UID 2 GiB rlimit | None observed |
| Main client, official codex, PRoot RLIMIT_AS and RLIMIT_DATA | Unlimited |
| Three interface processes RLIMIT_DATA | 8 GiB each |
| Another interface process RLIMIT_DATA | 4 GiB |
| Android Java heap growth/max | 512 MiB, applies to ART rather than all native child memory |

The current native launcher does not reserve a VM RAM allocation. Its installed
`foldgpt-session` has no memory override; `FoldRuntimeService` starts native PRoot
and GNU ARM64 directly. The historical `start-vm.sh` contains QEMU `-m 4096`, but
no QEMU process was observed and that script is not the native runtime launch.
Android's separately owned `crosvm_trustedvm` is not a FoldGPT process.

RLIMIT_DATA values are process limits, not reserved RAM or proof of an aggregate
FoldGPT allowance. Summed PSS accounts for shared pages proportionally, but this
sequential snapshot omits some driver allocations. One UI, Android and cached
background application processes remain present. MemAvailable already includes
memory that the kernel estimates it can reclaim; MemFree alone understates it.

The cgroup parent `/sys/fs/cgroup/apps/memory.max` reports `max`; the observed UID
and process cgroups expose no memory.max controller file. This does not remove
Android's memory limiter or low-memory process killing. The retained 16 recent
ApplicationExitInfo entries show package updates and one invalid service start,
not a MemoryLimiter:AnonSwap event; they are a bounded history, not proof that
memory pressure can never occur.

The GNU managed diagnostic's former 8.5 GiB RLIMIT_AS came from the static
allocator fixture and was insufficient for the dynamic Android loader. Scudo
requests 33 * 256 MiB of virtual address space; Bionic additionally reserves CFI
and randomized library gaps. This is separate from physical RAM use. Raising
or lowering that number to 4 GiB would not allocate 4 GiB of RAM to FoldGPT.
The dynamic runtime now derives its explicit address budget from the actual
ELF dependency closure, maximum loader gaps, CFI and Scudo reservations. The
retained calculation is 16,071,356,416 bytes of virtual address space, not RAM.
The standalone loader passed at this ceiling with 22,840 KiB RSS; this does not
qualify the later composed managed test. See the address derivation and evidence
in `tools/executor/gnu-runtime/android-scudo-address.md`.

Later native managed project attempts coincided with two actual device reboots
around 23:50 and 23:53. The user corrected an initial answer and confirmed that
neither restart was intentional. These attempts are not successful validation.
After the first reboot MemAvailable was 5,711,156 KiB (5.45 GiB). Further
reproducer runs are suspended while this unexpected instability is investigated;
normal execution routing remains inactive.

## Read-only follow-up, 7 September at 00:21 Paris

`downloads/runtime/native-readonly-20260907.json` records the same USB serial,
uptime 1,678.01 seconds and unchanged MemTotal. MemAvailable is 4,861,188 KiB
(4.64 GiB) at this later instant. This is not a sample of either failure.
The uptime is consistent with the second recorded reboot, without a newer
reboot before this reading.

The official Android 17 diagnostic `am memory-limiter status` reports
`disabled`. No limiter setting was changed. This additional observation does not
disable or rule out LMKD, reclaim, per-process limits or other Android resource
management. SwapTotal 12,582,908 KiB is separate from physical RAM and must not
be added to MemTotal as installed RAM. The live integrity readings remain
warranty bit 0, verified boot green, flash locked 1 and SELinux Enforcing.

The command is documented in the [Android 17 behavior changes](https://developer.android.com/about/versions/17/behavior-changes-all),
reopened in the integrated browser on 7 September; the page is dated 4 August
2026. Its mutating `ignore` and `manual` commands were not used.

## New live observation, 7 September at 07:00 Paris

The corrected collector uses `adb shell -T` and checks exit status, UID,
per-process starttime, boot identity and process membership around the sequential
snapshot. A denied, malformed or raced PSS reading now makes the whole-UID total
unknown; a partial observed sum is separately labelled. Seven regression tests
cover CRLF, denied/empty readings, partial coverage, PID reuse/changed owner,
membership changes and failed process enumeration. The independent review also
required a final starttime check to detect reuse after a process's individual
PSS reading window. All seven pass. Matching boundary sets do not rule out
transient processes between these sequential observations.

The actual new observation is retained in
`downloads/runtime/android-memory-v3-20260907.json`; its SHA-256, collector
identity, figures and process limits are in the tracked
[verification report](../../recovery/verification/android-memory-20260907.json).

| Observation | Result |
| --- | --- |
| MemTotal | 11,351,456 KiB = 10.83 GiB usable by Android |
| MemAvailable at this instant | 3,655,348 KiB = 3.49 GiB |
| FoldGPT UID 10412 | 23 processes, all 23 PSS readings usable |
| Sum of PSS | 712,435 KiB = 695.74 MiB |
| Main app, runtime, PRoot, official client and engine | RLIMIT_DATA and RLIMIT_AS unlimited |
| Four interface child processes | One RLIMIT_DATA of 4 GiB, three of 8 GiB |
| Boot before and after | `348d453e-f4e5-40e0-8ef0-030f4d5e38af` |

This does not account for every allocation attributable to the project: graphics
driver accounting is incomplete and Shizuku executes under UID2000, outside the
FoldGPT UID. The reading is not an atomic memory snapshot, and availability and
PSS change with reclaim and workload. It does not demonstrate an aggregate 2 GiB
limit or mean that reserving 4 GiB is possible or needed.

Separately, the experimental Bionic supervisor currently validates a maximum
`data_bytes` of 2 GiB in `processes.py`, `wire.py` and `runner.c`; the runner applies
it as **per-process RLIMIT_DATA**, not a physical RAM reservation or workspace
quota. Its general default is 256 MiB and the fixed qualification uses 16 MiB.
These configured limits do not describe the already-running official interface.
No memory limit was raised or removed by this observation.
