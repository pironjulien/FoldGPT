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
- Added the app-side private AF_UNIX/Binder adapter for the existing native
  stdio bridge, plus real pipe-copy tests and the concrete APK integration path.
- Qualified the actual bootstrap/ExecServer with preserved nested policy and
  explicit test refusal, real diagnostic cleanup, and retained failure markers.
- Wired the library into the main APK and added the `:runtime` owner, protected
  multi-process Binder delivery, explicit preparation action and qualified-asset
  admission. The default launcher remains unchanged; no deployment is enabled.
- Replaced unconditional runtime-process destruction with confirmed cleanup and
  a process-wide generation/ownership gate, verified by four actual JVM tests.
- Main signed debug APK builds and passes content/certificate checks. The
  existing HTTPS test cannot compile in the Android Gradle unit-test task;
  independent JVM exit-gate tests and library tests pass. No phone access occurred.
- Package the native cwd compatibility library and admit its exact installed
  nativeLibraryDir basename/SHA before fork. Resolve the fixed marker against
  the actual running interpreter before backend construction, with four Java
  tests and real process-path PC checks. No deployment is enabled by bundling it.
