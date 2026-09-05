#!/data/data/com.termux/files/usr/bin/bash
set -eu
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
key=$(cat /sdcard/Download/fold-usb.pub)
grep -qxF "$key" "$HOME/.ssh/authorized_keys" || printf '%s\n' "$key" >> "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
sshd -p 8022 -o ListenAddress=127.0.0.1 -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no
