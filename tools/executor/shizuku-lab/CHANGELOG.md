# Changelog

## 2026-09-07

- Version10 hosts the authenticated stdio bootstrap with PrivateSessionOwner.
  It retains the pinned directory, flock, stale-socket refusal and persistent
  marker without opening an unused listener. All84 native ELF and deployment
  bytes match v9; only broker/bootstrap assets and their manifest change.
  Twelve real nonroot owner tests and actual bootstrap lifecycle checks pass.
  The Activity pins report action identity and rejects a new Intent while its
  Java worker still runs, including after a reporting deadline. Reports use
  kernel-v6 and only KERNEL_RUN_FIXED_V10 reserves this revision. These are
  PC/build results; the phone evidence is recorded separately.

- Version9's explicit launch reached a real bootstrap bind refusal, errno13,
  with JNI wait/cleanup complete and no kernel worker launched. Its inherited
  old Intent was rejected before a reservation. V7/v8 admission reports came
  from automatic update replay before restaging, not explicit later trials.

- Version8 adds an authenticated read-only UserService preflight and bounded
  actual admission stage/cause reporting after v7 lost its pre-session error
  across Binder. Fixed read-only actions inspect the previous v3 service with
  NO_CREATE or preflight the new v4 service without JNI load/fork. New reports
  use files/kernel-v4; native bytes, bootstrap and lifetime protections remain
  unchanged. The previous-tag absence never establishes cleanup. Final APK
  76f58714... passes package/native/source/signature checks and24 transport JVM
  tests; cancellation is rechecked after preflight before opening a session.

- Version7 adds bounded private setup diagnostics after the real v6 bootstrap
  exited70 before ready. Its new attempt/reports use files/kernel-v3; the native
  base remains v2 and all84 native ELF entries match v6 byte for byte. The only
  changed assets are the bootstrap and source-manifest hash. Final APK
  0f7a673f... retains the certificate, original probe sources and authorization.
  Host setup/lifecycle tests and20 transport JVM tests pass; Android qualification
  is not inferred from this build. Prior APKs and device reports are preserved.

- Version 6 adds the independently reviewed fixed kernel diagnostic through the
  production Shizuku transport. The previous Java/AIDL probe sources and its
  7fa4f638 guard hash are unchanged. New report, package metadata and single-run
  reservation use only files/kernel-v2; the original report.json is untouched.
- Reuse normal existing API_V23 permission checks through the unchanged
  ProbeProvider. No Shizuku configuration, permission grant, PIN or system
  setting is changed by the APK. A distinct UserService tag owns kernel work.

- Qualified the real Fold UserService and final fixed native Python operation with version 5, pinning guard `7fa4f638...`. Three tests, zipapp build/run, six interpreter denials and descendant cleanup pass; independent collection confirms actual artifacts and unchanged boot/integrity. Earlier static PIE and Android runtime-data failures remain preserved. This does not implement ordinary model routing or automatic Shizuku startup.
- Version 3 identifies the rebuilt dynamic-PIE native guard separately after the first guard failed before main because of static-PIE startup relocations. Service tag/version now derive from the APK version so a corrected guard cannot silently reuse an older service instance. No native success is inferred from this rebuild.
- Added a separately versioned fixed native qualification operation, compiled executable hash, bounded independent output capture and retention of process ownership whenever native cleanup is unresolved. The frozen context-only APK remains unchanged.
- Added a separate DUMP-protected qualification APK using official Shizuku API/provider 13.1.5 and a fixed read-only UserService under shell UID 2000.
- Reports actual UserService credentials, seccomp status, SELinux context, parentage and descriptors into the probe application's private report.json. No phone deployment or runtime result is implied by this host build.
