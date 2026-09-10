"""Run a diagnostic Linux command inside the development APK over authorized ADB.

Requires a debuggable FoldGPT installation with Linux already installed.
"""
import argparse
from pathlib import PurePosixPath
import re
import shlex
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--guest-root", action="store_true", help="Emulate Debian UID 0 for package maintenance; does not root Android")
parser.add_argument("command", nargs=argparse.REMAINDER)
args = parser.parse_args()
adb = ["adb", "-s", args.serial]
try:
    package = subprocess.check_output(adb + ["shell", "dumpsys", "package", "app.foldgpt"], text=True, stdin=subprocess.DEVNULL)
    match = re.search(r"^\s*codePath=(.+)$", package, re.M)
    code = match.group(1).strip() if match else None
except subprocess.CalledProcessError:
    code = None
if not code:
    pm_path = subprocess.check_output(adb + ["shell", "pm", "path", "app.foldgpt"], text=True, stdin=subprocess.DEVNULL).strip()
    match = re.search(r"^package:(.+)/[^/]+\.apk$", pm_path)
    if match:
        code = match.group(1).strip()
    else:
        raise RuntimeError("FoldGPT package has no installed code path")
native = code + "/lib/arm64"
def app_read(*command):
    return subprocess.check_output(adb + ["shell", "run-as app.foldgpt " + shlex.join(command)],
                                   text=True, stdin=subprocess.DEVNULL).strip()

base = app_read("pwd")
if not re.fullmatch(r"/data/(?:user/[0-9]+|data)/app\.foldgpt", base):
    raise RuntimeError("Unexpected FoldGPT application data directory")
user = app_read("cat", "files/debian/etc/foldgpt-user")
if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user) or user == "root":
    raise RuntimeError("Invalid selected nonroot guest account")
rows = [line.split(":") for line in app_read("cat", "files/debian/etc/passwd").splitlines()]
selected = [row for row in rows if len(row) == 7 and row[0] == user]
if len(selected) != 1:
    raise RuntimeError("Selected guest account is missing or ambiguous")
account = selected[0]
if not all(value.isdecimal() and int(value) > 0 for value in account[2:4]):
    raise RuntimeError("Guest diagnostic requires a selected nonroot UID/GID")
guest_home = account[5]
if guest_home != "/home/" + user or str(PurePosixPath(guest_home)) != guest_home or account[6] != "/bin/bash":
    raise RuntimeError("Selected guest home/shell differs from the installed identity contract")
uid = subprocess.check_output(adb + ["shell", "run-as", "app.foldgpt", "id", "-u"], text=True, stdin=subprocess.DEVNULL).strip()
if not uid.isdecimal() or int(uid) <= 0:
    raise RuntimeError("ADB did not select an unprivileged Android application UID")
env = ["env", f"LD_LIBRARY_PATH={base}/files/native:{native}",
       f"PROOT_LOADER={native}/libproot-loader.so", f"PROOT_LOADER_32={native}/libproot-loader32.so",
       f"PROOT_TMP_DIR={base}/cache/x11"]
command = [native + "/libproot.so", "--kill-on-exit", "--link2symlink", "--sysvipc",
           "-r", base + "/files/debian", "-i", "0:0" if args.guest_root else account[2] + ":" + account[3], "-w", guest_home]
for path in ["/dev", "/proc", "/sys", "/system", "/apex", base + "/cache/x11:/tmp", base + "/cache/shm:/dev/shm"]:
    command += ["-b", path]
command += ["/usr/bin/env", "-i", "HOME=" + guest_home, "USER=" + user, "LOGNAME=" + user, "LANG=C.UTF-8",
            "PATH=/usr/local/bin:/usr/bin:/bin", "DISPLAY=:2", f"FOLDGPT_IME_UID={uid}", f"FOLDGPT_URL_UID={uid}"]
command += args.command or ["/bin/bash"]
# Android install paths contain '='; env would mistake that executable path for
# another variable assignment. A fixed shell path ends env's assignment parsing.
raise SystemExit(subprocess.call(adb + ["shell", "run-as app.foldgpt " + shlex.join(env + ["/system/bin/sh", "-c", "exec " + shlex.join(command)])]))
