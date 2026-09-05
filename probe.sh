#!/data/data/com.termux/files/usr/bin/bash
set -eu
exec > /sdcard/Download/fold-probe.log 2>&1
uname -m
id
command -v proot-distro || true
command -v sshd || true
apt-cache policy proot proot-distro termux-x11-nightly x11-repo
printf '\nPROBE_COMPLETE\n'
