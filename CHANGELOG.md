# Changelog

## Unreleased — 2026-09-10

- Require an explicit reviewed native executor package for candidate Android builds.
- Verify executor assets, JNI inventory, and the final APK before publication.
- Repair the native workspace admission path that previously fell back to a guest path and produced `EACCES`.
- Document Android process-pressure limits, publication scope, and contribution rules.
