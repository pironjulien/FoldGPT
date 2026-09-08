# Changelog

## 2026-09-08

- Added explicit inventory and verified relocation of one legacy project using
  Linux/Android directory descriptors, two-pass source checks and publication
  with renameat2(NOREPLACE). No source deletion or thread database modification.
- Added real filesystem tests for links, changes during copying and publication
  collisions. Android execution remains a separate qualification.
- Verified all 20 tests on a project-contained ext4 image as ordinary uid 1000;
  publication failures preserve errno and distinguish an already published copy.
- Documented the existing project/update and thread resume/settings APIs, including
  identity-proven native path aliases that require no copying or data movement.
