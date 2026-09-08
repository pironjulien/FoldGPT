# Changelog

## 2026-09-08

- Prepared separate Android app-context diagnostic for unchanged r25 Bionic pipe
  and PTY process adapters, native execution, subprocesses, stdin, interrupt and
  observed cleanup. Built and verified on PC; Android execution is pending.
- Recorded normal Java/Zygote lineage, UID/seccomp/capability evidence and
  cgroup/CPU/memory context. Preserved owners on unproven cleanup.
- Kept production app, bootstrap guards, runtime settings and signing authority
  outside the probe.
