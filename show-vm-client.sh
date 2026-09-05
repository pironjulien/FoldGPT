#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
export DISPLAY=:1
exec ssh -Y -p 8023 -i "$HOME/fold-vm/display-key" -o BatchMode=yes \
  julien@127.0.0.1 'dbus-run-session -- chatgpt --ozone-platform=x11 --enable-logging=stderr'
