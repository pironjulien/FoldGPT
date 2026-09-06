"""Exercise cache synchronization as the real Android app UID, without a restart.

Compile dmabuf-sync-probe.c with the Android NDK (API 30+, -landroid), placing
the executable at downloads/gpu/dmabuf-sync-probe. This creates only temporary
anonymous buffers and a private executable that is removed after the test.
"""
import argparse
import hashlib
from pathlib import Path
import shlex
import subprocess
import uuid

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    adb = ["adb", "-s", args.serial]
    name = "foldgpt-dmabuf-probe-" + uuid.uuid4().hex
    private = "cache/" + name
    data = (ROOT / "downloads/gpu/dmabuf-sync-probe").read_bytes()
    install = f"set -eu; set -C; cat > {private}; chmod 700 {private}"
    installed = False
    try:
        subprocess.run(adb + ["shell", "-T", "run-as app.foldgpt sh -c " + shlex.quote(install)],
                       input=data, check=True)
        installed = True
        actual = subprocess.check_output(adb + ["shell", "run-as", "app.foldgpt", "sha256sum", private], text=True).split()[0]
        if actual != hashlib.sha256(data).hexdigest():
            raise RuntimeError("DMA-BUF probe changed during transfer")
        result = subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "/system/bin/linker64", private], timeout=30)
        return result.returncode
    finally:
        if installed:
            subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "rm", "-f", private], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
