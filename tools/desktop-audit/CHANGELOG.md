# Changelog

## 2026-09-08

- Added static LLVM inventories of all 57 ELF files in installed 26.901.41600
  and reference 26.901.51231, with before/after byte checks and long-path support.
- Added a reproducible native comparison: 51 identical ELF contents and six
  changed files with unchanged observed imported requirements; kept runtime
  behavior and confinement outside that static claim.
- Added versionable native metadata and three analyzer checks for archive paths,
  cross-block literal evidence, version ordering and static-ELF classification.
- Added SHA-256 verified ASAR extraction without executing packaged client code.
- Added static Acorn analysis across explicit corpora, with source fingerprints,
  structured positions, parse failures and unresolved dynamic names retained.
- Added installed-client summaries separating actual main-process handlers and
  the reviewed renderer command map from broader syntactic candidates.
- Added eight focused parser tests covering non-execution, actual schemas,
  static versus dynamic calls, route classification and callback maps.
- Included full installed external JavaScript and checked all 370 ASAR unpacked
  members against the separately collected file sizes and hashes.
