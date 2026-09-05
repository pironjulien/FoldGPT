#!/bin/bash
set -euo pipefail
export DISPLAY=:1
export XDG_RUNTIME_DIR=/tmp/runtime-julien
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.local/state"
chmod 700 "$XDG_RUNTIME_DIR"
exec dbus-run-session -- chatgpt --ozone-platform=x11
