#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
    echo "Usage: $0 /path/to/your-public-key.pub" >&2
    exit 2
fi
pubkey=$(cat -- "$1")
case "$pubkey" in
    *$'\n'*|*$'\r'*) echo 'Provide exactly one public SSH key.' >&2; exit 2 ;;
    ssh-ed25519\ *|ssh-rsa\ *|ecdsa-sha2-*\ *|sk-ssh-ed25519@openssh.com\ *|sk-ecdsa-sha2-*\ *) ;;
    *) echo 'The supplied file must contain a public SSH key, never a private key.' >&2; exit 2 ;;
esac
ssh-keygen -l -f "$1" >/dev/null
mkdir -p "$HOME/.ssh"
chmod 700 "$HOME/.ssh"
touch "$HOME/.ssh/authorized_keys"
grep -qxF "$pubkey" "$HOME/.ssh/authorized_keys" || printf '%s\n' "$pubkey" >> "$HOME/.ssh/authorized_keys"
chmod 600 "$HOME/.ssh/authorized_keys"
sshd -p 8022 -o ListenAddress=127.0.0.1 -o PasswordAuthentication=no -o KbdInteractiveAuthentication=no
echo "SETUP_DONE" > /sdcard/Download/setup_status.txt
