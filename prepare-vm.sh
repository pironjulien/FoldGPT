#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
mkdir -p "$HOME/fold-vm/seed"
cd "$HOME/fold-vm"
if [ ! -f disk.qcow2 ]; then
  cp /sdcard/Download/fold-debian.qcow2 disk.qcow2
  qemu-img resize disk.qcow2 16G
fi
key=$(cat /sdcard/Download/fold-usb.pub)
cat > seed/user-data <<EOF
#cloud-config
hostname: fold-linux
users:
  - name: julien
    groups: [sudo]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: true
    ssh_authorized_keys:
      - $key
ssh_pwauth: false
disable_root: true
timezone: Europe/Paris
EOF
printf 'instance-id: fold-prototype-001\nlocal-hostname: fold-linux\n' > seed/meta-data
proot-distro login fold-debian -- genisoimage -output "$HOME/fold-vm/seed.iso" -volid cidata -joliet -rock "$HOME/fold-vm/seed/user-data" "$HOME/fold-vm/seed/meta-data"
