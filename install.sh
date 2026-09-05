#!/usr/bin/env bash
# Historical installer entry point. A clean installation has not been validated.
set -euo pipefail
cat >&2 <<'NOTICE'
FoldGPT: this legacy installer is unavailable because its clean-install workflow
has not been validated. No packages, application data or settings were changed.

For the current development build, see README.md (Build) and android/.
tools/migrate-device-runtime.py is a developer-only migration from an existing
Termux installation, requires an empty destination, and is not a fresh installer.
NOTICE
exit 1
