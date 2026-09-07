# Changelog

## 2026-09-07

- Add a canonical private setup_failed frame with bounded stage, exception,
  errno, basename/line and ASCII message. The parser accepts it only before ready,
  rejects duplicates/late success, and retains the existing actual wait/cleanup
  ownership gate. Real host setup failures and20 JVM tests pass. Lab v7 uses a
  new kernel-v3 report/attempt directory while retaining the fixed native basev2.

- Reuse the single fixed diagnostic Activity source in laboratory v6, with
  KERNEL_* actions and a canonical private kernel-v2 report subdirectory.
- Add explicit hash-checked frozen JNI inputs for the additive lab build so
  its transport and shim retain the previously reviewed APK bytes exactly.

- Added a separate fixed-kernel diagnostic APK using the actual authenticated
  UserService transport, with one attempt and independent native/JNI evidence.
- Resolve attested helper, runner and worker markers from PackageManager and
  the real interpreter ELF; verify all native hashes and staged Python data
  before shell-side fork. The diagnostic never selects general model commands.

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
