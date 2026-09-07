# Changelog

## 2026-09-07

- Added an independently built Shizuku transport library with caller-UID
  authentication, session ownership and once-only RPC pipe transfers.
- Added an APK-owned fixed Python bootstrap and async-signal-safe JNI launcher
  with a separate cancellation channel and private lifecycle reports.
- Preserve backend/persistent-marker ownership until explicit cleanup and real
  waitpid agree; reject missing deployment or unknown cleanup without retry.
- Added ten ownership tests and real host JNI process/stream/EOF/cancellation
  qualification. The main application and phone remain untouched by this work.
