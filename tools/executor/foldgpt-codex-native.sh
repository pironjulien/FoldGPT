#!/bin/sh
# The official application selects this separate engine via CODEX_CLI_PATH.
set -eu
# The engine consumes FOLDGPT_NATIVE_BOOTSTRAP only after its actual CLI parser
# selects app-server startup. Preserve global options and utility argv exactly.
exec /usr/local/libexec/foldgpt/codex-native "$@"
