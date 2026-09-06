#!/bin/bash
set -euo pipefail
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    exec dbus-run-session -- "$0"
fi
export FOLDGPT_CDP_PORT=9223
export XDG_RUNTIME_DIR=/tmp/runtime-julien
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.local/state"
chmod 700 "$XDG_RUNTIME_DIR"
timeout 20s python3 /usr/local/lib/foldgpt/foldgpt_keyring.py
python3 -u /usr/local/lib/foldgpt/foldgpt_ime.py > "$HOME/.local/state/foldgpt-ime.log" 2>&1 &
ime_pid=$!
# A window manager implements maximize, modal dialogs and display-size changes.
# Starting the application alone leaves these X11 requests unhandled.
xfwm4 > "$HOME/.local/state/foldgpt-wm.log" 2>&1 &
wm_pid=$!
trap 'kill "$ime_pid" "$wm_pid" 2>/dev/null || true' EXIT
chatgpt --ozone-platform=x11 --force-device-scale-factor="${FOLDGPT_SCALE:-1}" --start-maximized --remote-debugging-address=127.0.0.1 --remote-debugging-port="$FOLDGPT_CDP_PORT" &
client_pid=$!
# Ask the window manager for fullscreen using the application's actual window ID.
# EWMH fullscreen follows XRandR/IME resizes without a fixed pixel geometry.
while kill -0 "$client_pid" 2>/dev/null; do
    if clients=$(wmctrl -lx 2>/dev/null); then
        window=$(awk '$0 ~ /\)\.Chatgpt[[:space:]]/ { print $1; exit }' <<< "$clients")
    else
        window=""
    fi
    if [[ -n "$window" ]]; then
        wmctrl -i -r "$window" -b add,fullscreen
        break
    fi
    sleep 0.1
done
wait "$client_pid"
