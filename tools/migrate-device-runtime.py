"""Developer-only local migration from the existing Termux installation.

Refuses any nonempty destination. Private temporary archives are cleaned up on
success and failure; an interrupted destination is preserved for inspection.
The original Termux installation is preserved. This is not the public installer.
"""
import os
import argparse
from pathlib import Path
import posixpath
import re
import shlex
import subprocess
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[1]
SERIAL = os.environ.get("FOLDGPT_ADB_SERIAL", "")
ADB = ["adb", "-s", SERIAL]
KEYS = Path(os.environ["LOCALAPPDATA"]) / "ChatgptFold"
SSH = ["ssh", "-p", "18022", "-i", str(KEYS / "usb_ed25519"), "-o", "BatchMode=yes",
       "-o", f"UserKnownHostsFile={KEYS / 'known_hosts'}", "u0_a409@127.0.0.1"]
EXCLUDE = ["proc", "sys", "dev", "data", "apex", "system", "vendor", "odm", "product", "system_ext", "linkerconfig",
           "storage", "sdcard", "mnt", "tmp", "run", "var/cache"]


def app_shell(command, **kwargs):
    return subprocess.run(ADB + ["shell", "run-as", "app.foldgpt", "sh", "-c", shlex.quote(command)],
                          check=True, **kwargs)


def require_empty_destination():
    # Check before creating archives, and again before extraction. Never remove an
    # existing installation, even after a failed migration.
    app_shell("""
set -eu
if [ -L files/debian ]; then
    echo 'Migration refused: destination is a symlink.' >&2
    exit 1
fi
if [ -e files/debian ]; then
    if [ ! -d files/debian ]; then
        echo 'Migration refused: destination is not a directory.' >&2
        exit 1
    fi
    entries=$(ls -A files/debian)
    if [ -n "$entries" ]; then
        echo 'Migration refused: Linux destination already contains data; nothing was overwritten.' >&2
        exit 1
    fi
else
    mkdir -p files/debian
fi
[ "$(readlink -f files/debian)" = /data/user/0/app.foldgpt/files/debian ] || {
    echo 'Migration refused: unexpected destination path.' >&2
    exit 1
}
""")


def cleanup_archives(archive, staging):
    errors = []
    if archive is not None:
        try:
            if archive.parent.resolve() != KEYS.resolve() or not re.fullmatch(r"migration-private-[A-Za-z0-9_-]+\.tar", archive.name):
                raise RuntimeError("Refusing cleanup outside the private migration directory")
            archive.unlink(missing_ok=True)
        except Exception as error:
            errors.append(f"Local private archive cleanup failed ({archive}): {error}")
    if staging is not None:
        try:
            if not re.fullmatch(r"/data/local/tmp/foldgpt-private-[0-9a-f]{32}", staging):
                raise RuntimeError("Refusing unexpected Android staging path")
            # No recursive deletion. Validate the resolved directory before deleting
            # only our named archive and removing the now-empty staging directory.
            command = f"""
set -eu
if [ -e {staging} ] || [ -L {staging} ]; then
    [ ! -L {staging} ] && [ "$(readlink -f {staging})" = {staging} ] || exit 1
    rm -f {staging}/rootfs.tar
    rmdir {staging}
fi
"""
            subprocess.run(ADB + ["shell", command], check=True, timeout=30)
        except Exception as error:
            errors.append(f"Android private archive cleanup failed ({staging}): {error}")
    if errors:
        raise RuntimeError("\n".join(errors))


def migrate():
    require_empty_destination()
    KEYS.mkdir(parents=True, exist_ok=True)
    (ROOT / "logs").mkdir(exist_ok=True)
    archive = None
    staging = None
    source = None
    try:
        with tempfile.NamedTemporaryFile(prefix="migration-private-", suffix=".tar", dir=KEYS, delete=False) as temporary:
            archive = Path(temporary.name)
        command = 'tar -C "$PREFIX/var/lib/proot-distro/containers/fold-debian/rootfs" '
        command += ' '.join('--exclude=./' + item for item in EXCLUDE) + ' -cf - .'
        with (ROOT / "logs/migration-source.log").open("wb") as log:
            source = subprocess.Popen(SSH + [command], stdout=subprocess.PIPE, stderr=log)
            copied = 0
            with tarfile.open(fileobj=source.stdout, mode="r|") as incoming, tarfile.open(archive, mode="w") as outgoing:
                for member in incoming:
                    clean = posixpath.normpath(member.name)
                    if clean.startswith("/") or clean == ".." or clean.startswith("../"):
                        raise RuntimeError("Archive entry escapes the Linux root")
                    if member.issym() and member.linkname.startswith("/"):
                        member.linkname = posixpath.relpath(member.linkname.lstrip("/"), posixpath.dirname(clean) or ".")
                    outgoing.addfile(member, incoming.extractfile(member) if member.isfile() else None)
                    copied += member.size
            if source.wait():
                raise RuntimeError("Migration source failed; inspect logs/migration-source.log")
            print("Prepared", copied // (1024 * 1024), "MiB in private temporary storage.", flush=True)
        staging = "/data/local/tmp/foldgpt-private-" + uuid.uuid4().hex
        subprocess.run(ADB + ["shell", "mkdir", "-m", "700", staging], check=True)
        subprocess.run(ADB + ["push", str(archive), staging + "/rootfs.tar"], check=True)
        require_empty_destination()
        subprocess.run(ADB + ["shell", f"cat {staging}/rootfs.tar | run-as app.foldgpt tar -xf - -C files/debian"], check=True)
        subprocess.run(ADB + ["shell", "run-as", "app.foldgpt", "mkdir", "-p"] +
                       ["files/debian/" + d for d in EXCLUDE] +
                       ["files/debian/usr/local/lib/foldgpt", "files/debian/usr/local/bin"], check=True)
        for source_name, target in {
            "foldgpt_ime.py": "usr/local/lib/foldgpt/foldgpt_ime.py",
            "keyboard-focus.js": "usr/local/lib/foldgpt/keyboard-focus.js",
            "foldgpt-session.sh": "usr/local/bin/foldgpt-session",
        }.items():
            data = (ROOT / source_name).read_bytes().replace(b"\r\n", b"\n")
            app_shell(f"cat > files/debian/{target}", input=data)
        subprocess.run(ADB + ["shell", "run-as", "app.foldgpt", "chmod", "755", "files/debian/usr/local/bin/foldgpt-session"], check=True)
    finally:
        try:
            if source is not None:
                if source.stdout is not None:
                    source.stdout.close()
                if source.poll() is None:
                    source.terminate()
                    try:
                        source.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        source.kill()
                        source.wait(timeout=5)
        finally:
            cleanup_archives(archive, staging)
    print("Local migration complete. Original installation preserved. Temporary archives removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=not SERIAL, default=SERIAL)
    parser.add_argument("--ssh-user", default="u0_a409")
    args = parser.parse_args()
    ADB = ["adb", "-s", args.serial]
    SSH[-1] = args.ssh_user + "@127.0.0.1"
    migrate()
