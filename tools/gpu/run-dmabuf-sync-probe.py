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
import tempfile
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
    staging = "/data/local/tmp/" + name
    remote = staging + "/probe"
    subprocess.run(adb + ["shell", "mkdir", "-m", "700", staging], check=True)
    try:
        # adb shell stdin truncated ELF bytes on Windows. Transfer an immutable
        # snapshot through adb sync, then pipe entirely within Android.
        with tempfile.TemporaryDirectory(prefix=name) as local:
            snapshot = Path(local) / "probe"
            snapshot.write_bytes(data)
            subprocess.run(adb + ["push", str(snapshot), remote], check=True, timeout=30)
        remote_digest = subprocess.check_output(adb + ["shell", "sha256sum", remote], text=True).split()[0]
        if remote_digest != hashlib.sha256(data).hexdigest():
            raise RuntimeError("DMA-BUF probe changed during ADB push")
        installed = True
        command = "set -o pipefail; cat " + shlex.quote(remote)
        command += " | run-as app.foldgpt sh -c " + shlex.quote(install)
        subprocess.run(adb + ["shell", command], check=True, timeout=30)
        actual = subprocess.check_output(adb + ["shell", "run-as", "app.foldgpt", "sha256sum", private], text=True).split()[0]
        if actual != hashlib.sha256(data).hexdigest():
            raise RuntimeError("DMA-BUF probe changed during transfer")
        absolute = subprocess.check_output(adb + ["shell", "run-as", "app.foldgpt", "readlink", "-f", private], text=True).strip()
        if absolute not in ("/data/user/0/app.foldgpt/" + private, "/data/data/app.foldgpt/" + private):
            raise RuntimeError("Unexpected app-private executable path")
        result = subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "/system/bin/linker64", absolute], timeout=30)
        return result.returncode
    finally:
        if installed:
            subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "rm", "-f", private], check=True)
        subprocess.run(adb + ["shell", "rm", "-f", remote], check=True, timeout=10)
        subprocess.run(adb + ["shell", "rmdir", staging], check=True, timeout=10)


if __name__ == "__main__":
    raise SystemExit(main())
