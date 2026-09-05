#!/data/data/com.termux/files/usr/bin/bash
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
pubkey="ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAILCPRGMgE5SeM+tqA0bM6AQK5MGeITMKxn9WklYXUOpW julie@PCSALON"
touch "$HOME/.ssh/authorized_keys"
grep -qxF "$pubkey" "$HOME/.ssh/authorized_keys" || printf '%s\n' "$pubkey" >> "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
pkill -f qemu-system-aarch64 || true
pkill -f sshd || true
sshd -p 8022 -o ListenAddress=127.0.0.1 -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no
echo "SETUP_DONE" > /sdcard/Download/setup_status.txt
