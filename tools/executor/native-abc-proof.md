# Native A/B/C/A exact-file access diagnostic

Status on 2026-09-06: **passed natively on WSL; Android ARM64 compiled only**.
This is an isolated experiment, not the FoldGPT executor or a release gate pass.
No APK, ADB, phone state, model, account, official binary or launcher was changed.

## Reproduce

From the project root in PowerShell:

```powershell
& .\tools\executor\native-abc-build.ps1
```

The script needs WSL `Ubuntu-24.04` with GCC and Android NDK
`29.0.14206865`; its parameters allow explicitly selecting those installed tools.
It creates build/evidence files only under ignored `downloads/native-abc-check`.
The native diagnostic accepts an absolute existing fixture parent; the script
uses `/tmp` on the native Linux filesystem. It creates a fresh mode-0700
directory, tests its own three files, and removes exactly those files and that
directory. It never uses user documents as negative-test targets.

## What actually ran

- Native kernel: `6.18.33.2-microsoft-standard-WSL2`, x86_64; **Landlock ABI 7**.
- Native compiler: GCC `13.3.0-6ubuntu2~24.04.1`.
- Android cross compiler: NDK r29, Clang 21.0.0, target
  `aarch64-unknown-linux-android35`; inspected output is ELF64 AArch64 PIE.
- Both compilations: `-std=c11 -O2 -Wall -Wextra -Werror`.
- Each A1/B/C/A2 step forks a fresh fixed worker from the unrestricted parent.
  It closes inherited descriptors, retaining only its output pipe. No target
  data FD is open in the parent when it forks. A worker pins exact allowed
  files with `O_PATH`, installs its Landlock rules, then closes those handles.
- All filesystem rights defined through ABI 5 are handled. ABI 6 or later is
  required because the ruleset also scopes signals. This does **not** establish
  a tested comprehensive process-isolation boundary.
- Only exact files receive read/write grants. There is **no global read grant**,
  no rule on `/`, and no broad runtime or directory read grant.
- A grants target read/write/truncate. B grants target read only. C has no
  target rule. All workers may read one separate positive-control file; a
  third excluded sibling must reject both read and write for every worker.
- Read and writable/truncating acquisitions use real `syscall(SYS_openat, ...)`.
  Reads use `read`; successful writable opens use `write` and `fsync`. A denied
  policy would write a distinct violation marker if its writable open
  unexpectedly succeeded, making incorrect authority observable on disk.
- The parent checks the worker's report and actual exit, then independently
  reopens every fixture file and checks exact bytes, device/inode identity,
  mode, owner/group and link count. C is followed by A again on the same inode.

Observed target identity for the recorded main run: device `2096`, inode
`106093`, mode `0600`, link count `1`. The exact numbers vary on later runs.

| Fresh worker | Target read | Target writable open | Other permitted read | Parent verification |
| --- | --- | --- | --- | --- |
| A1 | Initial bytes read | Succeeds; writes first marker | Pass | First marker, same inode |
| B | First marker read | `EACCES` (13) | Pass | First marker unchanged, same inode |
| C | `EACCES` (13) | `EACCES` (13) | Pass | First marker unchanged, same inode |
| A2 | First marker read | Succeeds; writes final marker | Pass | Final marker, same inode |

The excluded sibling returned `EACCES` for read and write in all four workers.
All four workers exited and were reaped, and the owned fixture was removed.
Source uses direct syscalls; no syscall trace was collected in this run.

The independent watchdog test puts its permitted target behind a FIFO with no
writer, causing a real blocking open in B. The supervisor reached its monotonic
5-second deadline, killed only that unreaped direct child, and reaped it.
Observed elapsed time: **5010 ms**. Timeout is an expected failure result from
the worker supervisor, never a file-access denial or policy pass. Cleanup has a
separate 5-second deadline and failure to reap is reported as failure.

An additional WSL build with `-O1 -g -fsanitize=address,undefined` completed the
same A/B/C/A test successfully. This is a diagnostic memory/undefined-behavior
check, not a wider sandbox or leak-lifetime validation.

## Recorded evidence

The build script records `environment.txt`, `host-result.txt`,
`watchdog-result.txt`, `android-elf-header.txt` and `sha256.json` in
`downloads/native-abc-check`.

SHA-256 for the recorded C source and compiled main diagnostic:

```text
native-abc-probe.c
7ccb1d81d14cb797d984cb2807f779a04c11960bb2d29c7a368b11ef072e04ed
native-abc-linux-x86_64
dbffb6aa61285309f0e64e1677f5674c32721dfdfbf1286ea2130c2f905728b8
native-abc-android-arm64
073f5bdca266e3d4637dcf47ebc35a9492a258fd90811af3c142a60b8698fd5f
```

## Limits and next gates

This establishes different **kernel-enforced file data operations** on the
same native inode. It does not establish full read confidentiality against
arbitrary code: the workers are fixed, already-mapped code after `fork`, with
inherited address-space contents. There is no executable/loader/runtime grant
strategy here, no shell launch, and no private address-space supervisor protocol.

It does not implement or test metadata hiding (`stat`, traversal, names),
protected metadata rules, arbitrary mutation families, hardlink/alias/rename
races, alternate cwd/dirfd resolution, concurrent A/C descriptor theft/passing,
ptrace or process-memory isolation, network isolation, malicious descendants,
cancellation semantics, or a policy compiler. Sequential workers create no
descendants; the final `ECHILD` check covers their direct reaping only.
Signal scoping is installed but its attack matrix is not exercised here.

No PRoot, Debian shell, executor RPC, Desktop host RPC, real Codex command,
patch operation or Remote session was run. The Android artifact was **not run**;
WSL evidence cannot establish the same outcome under the Fold's Android kernel,
SELinux and process environment. No app performance, Knox, warranty or release
claim follows from this experiment.

The broader required matrix remains in
[`../policy/managed-policy-contract.md`](../policy/managed-policy-contract.md).
This diagnostic is only the sequential exact-file A/B/C/A increment of that
contract, with a separate positive control and excluded sibling. It does not
complete its metadata-marker, private-scratch, concurrent attack or integration
requirements. The existing `policy_intent.py` remains inert policy data;
this diagnostic is not connected to it and cannot enforce its general contexts.
