# Changelog

## 2026-09-06

- Audit authenticated Debian procps 2:4.0.4-9 and the Fold's read-only kernel
  interfaces to isolate the Electron sampler's `lstart` failure.
- Prepare a guarded REALTIME/BOOTTIME measurement in GNU ps when procfs boot
  metadata is inaccessible, with explicit failure for ambiguous samples.
- Add nonroot Linux original/corrected binary comparisons using a real
  Landlock denial, plus deterministic clock/error tests. Android integration
  and publication remain unqualified.
