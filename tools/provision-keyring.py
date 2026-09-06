"""Stage an existing keyring password for one-time Android Keystore import.

Development only: adb must already be authorized and app.foldgpt debuggable.
The password moves from NexusSecure to the app's private stdin; never argv,
environment, console, shared storage, or a local temporary file.
"""
import argparse
import os
from pathlib import Path
import shlex
import subprocess
import sys
import uuid


def staging_command(token):
    if len(token) != 32 or any(c not in "0123456789abcdef" for c in token):
        raise ValueError("Invalid staging identifier")
    return f"""set -eu
umask 077
if [ ! -e no_backup ]; then mkdir no_backup; fi
[ -d no_backup ] && [ ! -L no_backup ]
[ "$(readlink -f no_backup)" = /data/user/0/app.foldgpt/no_backup ]
[ "$(stat -c %a no_backup)" = 700 ]
[ "$(stat -c %u no_backup)" = "$(id -u)" ]
directory=no_backup/foldgpt-keyring
if [ ! -e "$directory" ]; then mkdir "$directory"; fi
[ -d "$directory" ] && [ ! -L "$directory" ]
[ "$(stat -c %a "$directory")" = 700 ]
[ "$(stat -c %u "$directory")" = "$(id -u)" ]
cd "$directory"
lock=keyring-password.provisioning
mkdir "$lock"
staging="$lock/{token}.pending"
trap 'rm -f "$staging"; rmdir "$lock"' EXIT
[ ! -e keyring-password.v1 ] && [ ! -L keyring-password.v1 ]
[ ! -e keyring-password.import ] && [ ! -L keyring-password.import ]
[ ! -e "$staging" ] && [ ! -L "$staging" ]
set -C
cat > "$staging"
size=$(stat -c %s "$staging")
[ "$size" -ge 1 ] && [ "$size" -le 8192 ]
[ "$(stat -c %a "$staging")" = 600 ]
# Android SELinux denies app hardlinks. An exclusive provisioning directory
# serializes writers; same-filesystem rename publishes the complete file.
mv -n "$staging" keyring-password.import
[ ! -e "$staging" ]
rmdir "$lock"
trap - EXIT
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--secret-file", type=Path,
                        default=Path(os.environ.get("OneDrive", "")) / "Documents/NexusSecure/projects/ChatgptFold/foldgpt-keyring-password.txt")
    args = parser.parse_args()
    password = bytearray()
    try:
        # Preserve exact bytes: trimming a valid password would silently change it.
        with args.secret_file.open("rb") as source:
            password = bytearray(source.read(8193))
        if not password or len(password) > 8192 or 0 in password:
            raise ValueError("Invalid credential")
        command = staging_command(uuid.uuid4().hex)
        result = subprocess.run(["adb", "-s", args.serial, "shell", "-T", "run-as", "app.foldgpt",
                                 "sh", "-c", shlex.quote(command)], input=password,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        if result.returncode:
            raise RuntimeError("Private import refused")
        print("Credential staged privately for Android Keystore import on next workspace launch.")
        return 0
    except Exception:
        print("Keyring provisioning failed; no credential contents were logged.", file=sys.stderr)
        return 1
    finally:
        password[:] = b"\0" * len(password)


if __name__ == "__main__":
    raise SystemExit(main())
