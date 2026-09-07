# Changelog

## 2026-09-07

- Qualified the real Fold UserService and final fixed native Python operation with version 5, pinning guard `7fa4f638...`. Three tests, zipapp build/run, six interpreter denials and descendant cleanup pass; independent collection confirms actual artifacts and unchanged boot/integrity. Earlier static PIE and Android runtime-data failures remain preserved. This does not implement ordinary model routing or automatic Shizuku startup.
- Version 3 identifies the rebuilt dynamic-PIE native guard separately after the first guard failed before main because of static-PIE startup relocations. Service tag/version now derive from the APK version so a corrected guard cannot silently reuse an older service instance. No native success is inferred from this rebuild.
- Added a separately versioned fixed native qualification operation, compiled executable hash, bounded independent output capture and retention of process ownership whenever native cleanup is unresolved. The frozen context-only APK remains unchanged.
- Added a separate DUMP-protected qualification APK using official Shizuku API/provider 13.1.5 and a fixed read-only UserService under shell UID 2000.
- Reports actual UserService credentials, seccomp status, SELinux context, parentage and descriptors into the probe application's private report.json. No phone deployment or runtime result is implied by this host build.
