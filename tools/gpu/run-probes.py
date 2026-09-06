"""Run bounded Vulkan and optional GLX pixel tests in the isolated Mesa prefix.

Does not restart or reconfigure the main ChatGPT process. A pass is real GPU
clear/readback evidence, not a framerate measurement or desktop GPU validation.
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys

PREFIX = "/opt/foldgpt-gpu/mesa-26.2.2-foldgpt4"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--api", choices=("vulkan", "glx", "timestamp", "both"), default="both")
    parser.add_argument("--prefix", default=PREFIX, help="Isolated driver revision to test")
    args = parser.parse_args()
    if not re.fullmatch(r"/opt/foldgpt-gpu/mesa-[0-9]+\.[0-9]+\.[0-9]+-foldgpt[1-9][0-9]*", args.prefix):
        parser.error("prefix must name an isolated FoldGPT Mesa revision")
    helper = Path(__file__).resolve().parents[1] / "device-shell.py"
    command = [sys.executable, str(helper), "--serial", args.serial, "/usr/bin/env",
               "VK_DRIVER_FILES=" + args.prefix + "/share/vulkan/icd.d/freedreno_icd.aarch64.json",
               "LD_LIBRARY_PATH=" + args.prefix + "/lib", "XDG_CACHE_HOME=/tmp/foldgpt-gpu-probe-cache"]
    apis = ("vulkan", "glx") if args.api == "both" else (args.api,)
    for api in apis:
        environment = []
        if api == "glx":
            environment = ["MESA_LOADER_DRIVER_OVERRIDE=zink", "GALLIUM_DRIVER=zink"]
        executable = "vulkan-timestamp-probe" if api == "timestamp" else api + "-clear-probe"
        result = subprocess.run(command + environment + ["/usr/bin/timeout", "30s",
                                args.prefix + "/bin/" + executable], timeout=45)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
