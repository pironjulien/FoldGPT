#!/bin/sh
# The official application selects this separate engine via CODEX_CLI_PATH.
set -eu
engine=/usr/local/libexec/foldgpt/codex-native
if [ "${1-}" = app-server ]; then
    : "${FOLDGPT_NATIVE_BOOTSTRAP:?Native startup manifest is required}"
    case "$FOLDGPT_NATIVE_BOOTSTRAP" in
        /*) ;;
        *) printf '%s\n' 'Native startup manifest must be absolute' >&2; exit 64 ;;
    esac
    if [ ! -f "$FOLDGPT_NATIVE_BOOTSTRAP" ]; then
        printf '%s\n' 'Native startup manifest is unavailable' >&2
        exit 70
    fi
    shift
    exec "$engine" app-server --foldgpt-native-bootstrap "$FOLDGPT_NATIVE_BOOTSTRAP" "$@"
fi
exec "$engine" "$@"
