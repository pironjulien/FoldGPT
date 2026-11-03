# Changelog

## 2026-11-03

- `prototype-Cargo.lock`: tokio 1.53.1 → 1.53.3 (RUSTSEC-2026-0386). Upstream
  source hashes and patch unchanged; both `--locked` validations pass.

## 2026-09-07

- Documented the real local Android backend integration boundary at Codex
  rust-v0.153.4, including model, host process, filesystem and session routes.
- Added an additive owned-process adapter against pinned upstream PTY sources,
  with bounded lossless output channels and fallible process controls.
- Verified real PC child streams, stdin EOF, exit and termination; type-checked
  the adapter library for Android ARM64. No phone or client changes.
