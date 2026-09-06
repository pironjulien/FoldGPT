"""Present a temporary, unfocused 64px GPU window; remove the probe afterwards.

Run tools/gpu/build-present-probe.sh in WSL first. This test intentionally uses
X11 presentation, unlike the offscreen probes. It does not modify any client file.
"""
import argparse
import hashlib
from pathlib import Path
import re
import shlex
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "/opt/foldgpt-gpu/mesa-26.2.2-foldgpt5"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--probe", choices=("present", "tfp"), default="present")
    parser.add_argument("--prefix", default=PREFIX, help="Isolated driver revision to test")
    args = parser.parse_args()
    if not re.fullmatch(r"/opt/foldgpt-gpu/mesa-[0-9]+\.[0-9]+\.[0-9]+-foldgpt[1-9][0-9]*", args.prefix):
        parser.error("prefix must name an isolated FoldGPT Mesa revision")
    adb = ["adb", "-s", args.serial]
    name = "foldgpt-glx-" + args.probe + "-" + uuid.uuid4().hex
    staging = "/data/local/tmp/" + name
    private = "cache/x11/" + name
    executable = ROOT / ("downloads/gpu/glx-" + args.probe + "-probe")
    expected = hashlib.sha256(executable.read_bytes()).hexdigest()
    subprocess.run(adb + ["shell", "mkdir", "-m", "700", staging], check=True)
    try:
        subprocess.run(adb + ["push", str(executable), staging + "/probe"], check=True, stdout=subprocess.DEVNULL)
        actual = subprocess.check_output(adb + ["shell", "sha256sum", staging + "/probe"], text=True).split()[0]
        if actual != expected:
            raise RuntimeError("Presentation probe changed during transfer")
        install = f"set -eu; set -C; cat > {private}; chmod 700 {private}"
        subprocess.run(adb + ["shell", "set -o pipefail; cat " + staging + "/probe | run-as app.foldgpt sh -c " + shlex.quote(install)], check=True)
        result = subprocess.run([sys.executable, str(ROOT / "tools/device-shell.py"), "--serial", args.serial,
            "/usr/bin/env", "VK_DRIVER_FILES=" + args.prefix + "/share/vulkan/icd.d/freedreno_icd.aarch64.json",
            "LD_LIBRARY_PATH=" + args.prefix + "/lib", "MESA_LOADER_DRIVER_OVERRIDE=zink", "GALLIUM_DRIVER=zink",
            "XDG_CACHE_HOME=/tmp/foldgpt-gpu-probe-cache", "LIBGL_DEBUG=verbose", "MESA_DEBUG=1",
            "/usr/bin/timeout", "30s", "/tmp/" + name], timeout=45)
        return result.returncode
    finally:
        subprocess.run(adb + ["shell", "run-as", "app.foldgpt", "rm", "-f", private], check=True)
        cleanup = f"set -eu; [ ! -L {staging} ] && [ \"$(readlink -f {staging})\" = {staging} ]; rm -f {staging}/probe; rmdir {staging}"
        subprocess.run(adb + ["shell", cleanup], check=True)


if __name__ == "__main__":
    raise SystemExit(main())
