# Independent Android engine integration work

The [integration plan](integration-plan.md) identifies the central local runtime
selection, the exact 0.153.4 process/file contracts and the remaining host routes.
No original client file, upstream checkout or phone state is changed here.

The [owned process adapter](owned_process_driver.rs) extends the actual pinned
`codex-utils-pty` code through [a reviewable patch](owned-process-driver.patch).
It passes native mpsc streams directly to upstream managers, supports fallible
interrupt/resize/terminate controls and retains termination control after a
failed request. Existing broadcast-based driver call sites are unchanged.
The new `try_request_terminate()` returns the controller error. Native host
`ProcessControl::Kill` and `CommandControl::Terminate` must use it instead of
the upstream best-effort `request_terminate(); Ok(())` sequence.

On the PC, run:

```powershell
python tools/executor/android-engine/export_prototype.py
cargo test --manifest-path tools/executor/android-engine/pty-prototype/Cargo.toml --test owned_driver --locked
cargo check --manifest-path tools/executor/android-engine/pty-prototype/Cargo.toml --lib --target aarch64-linux-android --locked
```

The export verifies tag commit `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` and
retains source hashes in `prototype-provenance.json`. Generated copied sources
and build output stay in the ignored `pty-prototype` directory. The standalone
manifest enables winapi's std feature so the original Windows source uses the
same c_void type as std; it does not modify the original Windows implementation.

Validation on 2026-09-07 with Rust 1.97.0:

- Two tests pass using an actual compiled child executable, without a visible
  window. stdin EOF and binary stdout/stderr are preserved exactly under
  one-chunk channel backpressure: 771,006 stdout bytes and 385,500 stderr bytes.
  The real child exit code is 23.
- The real waiting child is terminated and reaped. Unsupported pipe resize and
  Windows console interruption return errors. No successful PTY or Unix signal
  test is claimed by that PC run.
- The library type-checks for `aarch64-linux-android`. This is not an Android
  link, phone run or full Codex engine compilation.

This component is a process adapter, not an Android launcher, policy translator,
transport authenticator, PTY provider or filesystem implementation. Those must
come from the native runtime and the Shizuku application. In particular, a
process exit is not a descendant-cleanup attestation. Runtime ownership and a
separate trusted failure/cleanup channel are still required.
