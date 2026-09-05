"""Developer bootstrap: compile the pinned PRoot source on an authorized ARM64 Termux.

Only source and compiler outputs are transferred; no account state is accessed.
PRoot remains a compatibility layer, not a security isolation boundary.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ssh-port", type=int, default=18022)
parser.add_argument("--ssh-user", default="u0_a409")
args = parser.parse_args()
keys = Path(os.environ["LOCALAPPDATA"]) / "ChatgptFold"
ssh = ["ssh", "-p", str(args.ssh_port), "-i", str(keys / "usb_ed25519"),
       "-o", "BatchMode=yes", "-o", f"UserKnownHostsFile={keys / 'known_hosts'}",
       f"{args.ssh_user}@127.0.0.1"]
commit = subprocess.check_output(["git", "-C", str(ROOT / "vendor/proot"), "rev-parse", "HEAD"], text=True).strip()
archive = subprocess.check_output(["git", "-C", str(ROOT / "vendor/proot"), "archive", "HEAD"])
remote = "fold-proot-" + commit[:12]
subprocess.run(ssh + [f"mkdir -p {remote} && tar -xf - -C {remote}"], input=archive, check=True)
command = (f"cd {remote}/src && make -j4 CC=clang LD=clang STRIP=llvm-strip "
           "OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump "
           "PROOT_UNBUNDLE_LOADER=/foldgpt/runtime PROOT_WITH_LIBANDROID_SHMEM=1")
subprocess.run(ssh + [command], check=True)
destination = ROOT / "android/native/runtime/arm64-v8a"
destination.mkdir(parents=True, exist_ok=True)
for source, name in [("proot", "libproot.so"), ("loader/loader", "libproot-loader.so"),
                     ("loader/loader-m32", "libproot-loader32.so")]:
    data = subprocess.check_output(ssh + ["cat " + shlex.quote(f"{remote}/src/{source}")])
    if not data.startswith(b"\x7fELF"):
        raise RuntimeError(f"Invalid build output: {source}")
    (destination / name).write_bytes(data)
manifest = {"proot_source": commit, "sha256": {
    str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
    for p in (ROOT / "android/native").rglob("*.so")}}
(ROOT / "android/native/hashes.json").write_text(json.dumps(manifest, indent=2) + "\n")
print("Built PRoot and matching loaders from", commit)
