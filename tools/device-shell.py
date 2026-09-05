"""Run a diagnostic Linux command inside the development APK over authorized ADB.

Requires a debuggable FoldGPT installation with Linux already installed.
"""
import argparse
import re
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--guest-root", action="store_true", help="Emulate Debian UID 0 for package maintenance; does not root Android")
parser.add_argument("command", nargs=argparse.REMAINDER)
args = parser.parse_args()
adb = ["adb", "-s", args.serial]
package = subprocess.check_output(adb + ["shell", "dumpsys", "package", "app.foldgpt"], text=True, stdin=subprocess.DEVNULL)
code = re.search(r"^\s*codePath=(.+)$", package, re.M).group(1).strip()
native = code + "/lib/arm64"
base = "/data/user/0/app.foldgpt"
uid = subprocess.check_output(adb + ["shell", "run-as", "app.foldgpt", "id", "-u"], text=True, stdin=subprocess.DEVNULL).strip()
env = ["env", f"LD_LIBRARY_PATH={base}/files/native:{native}",
       f"PROOT_LOADER={native}/libproot-loader.so", f"PROOT_LOADER_32={native}/libproot-loader32.so",
       f"PROOT_TMP_DIR={base}/cache/x11"]
command = [native + "/libproot.so", "--kill-on-exit", "--link2symlink", "--sysvipc",
           "-r", base + "/files/debian", "-i", "0:0" if args.guest_root else "10410:10410", "-w", "/home/julien"]
for path in ["/dev", "/proc", "/sys", "/system", "/apex", base + "/cache/x11:/tmp", base + "/cache/shm:/dev/shm"]:
    command += ["-b", path]
command += ["/usr/bin/env", "-i", "HOME=/home/julien", "USER=julien", "LANG=C.UTF-8",
            "PATH=/usr/local/bin:/usr/bin:/bin", "DISPLAY=:2", f"FOLDGPT_IME_UID={uid}"]
command += args.command or ["/bin/bash"]
# Android install paths contain '='; env would mistake that executable path for
# another variable assignment. A fixed shell path ends env's assignment parsing.
raise SystemExit(subprocess.call(adb + ["shell", "run-as app.foldgpt " + shlex.join(env + ["/system/bin/sh", "-c", "exec " + shlex.join(command)])]))
