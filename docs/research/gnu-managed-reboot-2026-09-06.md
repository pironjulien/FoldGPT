# Native GNU managed diagnostic: unexpected reboot incident

Status: unresolved. Reproducer runs suspended. Ordinary phone command routing
still uses the existing path and reports Bubblewrap as unavailable.
Clarification after source/evidence review on 7 September: "missing" describes
the engine's unavailable result, not an absent file. The retained bwrap binary
answered `--version`, but its `--help` failed; the required user/PID namespaces
remain absent independently. See [the precise blocker](capabilities/01-effective-mechanisms.md).

## Observations

- APK `97cabf15011d15980a2d913a7fb42fa2e9a878fd9383e54233d5afc782b239f7`
  contains the native FD and virtual-address capacity calculations. It was
  installed from `downloads/gnu-runtime/managed-android-a0745f868eb343478fb2ed50e848dae1`.
- The fixed DUMP-protected GNU diagnostic was launched. Its case
  `cache/gm-9075357992589474852/cases/gnu-rpc-sib7itas` retained the actual
  `project/app/maths.py`, `project/app/__main__.py`, and `project/test.py` names.
  Their collected contents are entirely NUL bytes (29, 45 and 286 bytes).
  The 4,888-byte context file is also entirely NUL and cannot prove runtime
  context. No completed suite report, test output or packaged project survived.
- A device reboot occurred around 23:50 Paris. The user initially answered
  that it was manual; the fixture was restarted after that answer. The user
  then corrected the answer: neither reboot was voluntary. A second reboot
  occurred around 23:53. No further execution of this fixture was requested.
- Native uptime restarted, USB disappeared, and authenticated wireless ADB
  later identified the same device serial `R3GL808JN4A`. The normal interface
  returned. The diagnostic service and GNU executor service were absent from
  the live service inventory.
- Rechecked indicators: warranty bit `0`, verified boot `green`, flash locked
  `1`, SELinux `Enforcing`. These are observations, not contractual warranty
  guarantees or proof that no instability occurred.

## Retained evidence and limits

`downloads/gnu-runtime/reboot-incident-20260906/` contains read-only collection:
the interrupted project file bytes, unusable context, empty output, process/service inventory,
memory, boot reason and integrity observations. The incident collector does
not execute any guest source.

`downloads/runtime/reboot-20260906-235042.txt` and
`reboot-20260906-235429.txt` retain the two available DropBox LAST_KMSG entries.
They contain bootloader information and generic `reboot`, without a usable
kernel fault stack. The `_KP` tag alone does not establish a particular panic.
The shell cannot read `/proc/last_kmsg`, `/proc/reset_reason`,
`/proc/reset_summary`, `/proc/reset_rwc` or `/proc/reset_history`; those access
controls were not changed.

The three retained project filenames correspond to operations before the first
Python `subprocess.run` in the suite. They are minimum structural progression,
not proof of the last completed write or exact failing instruction: file data
did not survive intact and later operations may have been lost. Possible memory or
kernel interactions require investigation. A successful standalone PRoot version
probe at the computed address ceiling does not establish that the composed
ptrace/seccomp/Landlock process tree is stable.

## Current engineering boundary

No repeat of the suspect fixture, no normal routing activation, and no memory
stress test while the cause remains unknown. Source review and existing evidence
analysis continue. Scudo, CFI, ASLR, Android memory management, SELinux and Knox
are preserved. Removing a protection to avoid the symptom is not a resolution.

Offline bounded source review found no reboot command or unbounded fork/load
in the fixed project sequence. PRoot processes fork/vfork/clone ptrace events;
the native supervisor detaches its own ptrace at the first exec, then mediates
seccomp USER_NOTIF/ADDFD_SEND. Its timeout kills the still-owned process group
and reaps descendants. The retained logs do not locate either reboot within
those operations. There is no defensible causal code correction yet.
