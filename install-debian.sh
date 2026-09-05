#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates dbus-x11 xfce4-session xfwm4 xfce4-panel xfce4-settings xfdesktop4 thunar xterm fonts-dejavu fonts-noto-color-emoji gnome-keyring libsecret-tools git procps util-linux /sdcard/Download/chatgpt_arm64.deb
if ! id julien >/dev/null 2>&1; then
  useradd --create-home --shell /bin/bash julien
fi
install -d -m 700 -o julien -g julien /home/julien/.local/state /home/julien/Projects
dpkg-query -W chatgpt
printf '\nINSTALL_COMPLETE\n'
