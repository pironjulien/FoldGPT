# Changelog

## 2026-09-08

- Both real Fold cases now pass without Shizuku; add a PC receipt verifier and
  preserve the independent Zygote, identity, file, cleanup and device evidence.
  Production integration remains pending; its owner was already unavailable.
- Prepared separate Android app-context diagnostic for unchanged r25 Bionic pipe
  and PTY process adapters, native execution, subprocesses, stdin, interrupt and
  observed cleanup. Built and verified on PC before the recorded Android run.
- Recorded normal Java/Zygote lineage, UID/seccomp/capability evidence and
  cgroup/CPU/memory context. Preserved owners on unproven cleanup.
- Kept production app, bootstrap guards, runtime settings and signing authority
  outside the probe.
