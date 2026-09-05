"""Collect only named runtime binaries from the already installed official packages.

This developer bootstrap never reads account data. Generated binaries are ignored by Git.
"""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / "android/native/runtime/arm64-v8a"
DEST.mkdir(parents=True, exist_ok=True)
KEYS = Path(os.environ["LOCALAPPDATA"]) / "ChatgptFold"
SSH = ["ssh", "-p", "18022", "-i", str(KEYS / "usb_ed25519"), "-o", "BatchMode=yes",
       "-o", f"UserKnownHostsFile={KEYS / 'known_hosts'}", "u0_a409@127.0.0.1"]
inputs = {
    "libtalloc.so": "lib/libtalloc.so.2.4.3",
    "libandroid-shmem.so": "lib/libandroid-shmem.so",
}
for name, source in inputs.items():
    data = subprocess.check_output(SSH + [f'cat "$PREFIX/{source}"'])
    if not data.startswith(b"\x7fELF"): raise RuntimeError(f"Not ELF: {source}")
    (DEST / name).write_bytes(data)
# PRoot and its loaders are compiled from vendor/proot by build-proot-on-device.py.
# The Play variant embeds Termux-private paths and cannot run in our sandbox.
with zipfile.ZipFile(ROOT / "downloads/termux-x11.apk") as archive:
    dest = ROOT / "android/native/x11/arm64-v8a"
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "libXlorie.so").write_bytes(archive.read("lib/arm64-v8a/libXlorie.so"))
manifest = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (ROOT / "android/native").rglob("*.so")}
(ROOT / "android/native/hashes.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Prepared", len(manifest), "native libraries; no account data collected.")
