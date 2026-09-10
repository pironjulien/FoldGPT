#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail
cd "$HOME/fold-vm"
exec qemu-system-aarch64 -machine virt -accel tcg,thread=multi -cpu max -smp 4 -m 4096 \
  -bios "$PREFIX/share/qemu/edk2-aarch64-code.fd" \
  -drive if=none,file=disk.qcow2,id=os,format=qcow2 -device virtio-blk-pci,drive=os \
  -drive if=none,file=seed.iso,id=seed,format=raw,readonly=on -device virtio-blk-pci,drive=seed \
  -netdev user,id=net,hostfwd=tcp:127.0.0.1:8023-:22 -device virtio-net-pci,netdev=net \
  -display none -serial file:console.log -monitor unix:monitor.sock,server,nowait
