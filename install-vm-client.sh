#!/bin/bash
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y --no-install-recommends ca-certificates dbus-x11 openbox xauth x11-utils fonts-dejavu fonts-noto-color-emoji gnome-keyring libsecret-tools git /home/julien/chatgpt_arm64.deb
dpkg-query -W chatgpt
printf '\nVM_CLIENT_INSTALLED\n'
