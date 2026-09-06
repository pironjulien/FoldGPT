"""Install only the isolated GPU probe prefix into the development FoldGPT APK."""
import argparse
import hashlib
import io
from pathlib import Path
import posixpath
import shlex
import subprocess
import tarfile
import tempfile
import uuid

ROOT = Path(__file__).resolve().parents[2]
PREFIX = "opt/foldgpt-gpu/mesa-26.2.2-foldgpt4"


def validate_archive(data):
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as content:
        for item in content:
            if item.name != PREFIX and not item.name.startswith(PREFIX + "/"):
                raise ValueError("GPU archive entry is outside the isolated prefix")
            if ".." in item.name.split("/") or not (item.isfile() or item.isdir() or item.issym()):
                raise ValueError("Unexpected GPU archive entry type or path")
            if item.issym():
                target = posixpath.normpath(posixpath.join(posixpath.dirname(item.name), item.linkname))
                if (item.linkname.startswith("/") or ".." in item.linkname.split("/")
                        or not target.startswith(PREFIX + "/")):
                    raise ValueError("GPU archive symlink escapes isolated prefix")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    # Validate and hash the same bytes; builds may replace the original archive
    # at any time. Transfer a private snapshot and compare against this digest.
    data = (ROOT / "downloads/gpu/foldgpt-mesa-26.2.2-arm64.tar.gz").read_bytes()
    validate_archive(data)
    expected_digest = hashlib.sha256(data).hexdigest()
    revision_stage = "files/debian/opt/foldgpt-gpu/.stage-" + uuid.uuid4().hex
    command = f"""set -eu
destination=files/debian/{PREFIX}
[ ! -L files/debian ] && [ "$(readlink -f files/debian)" = /data/user/0/app.foldgpt/files/debian ]
[ -d files/debian/opt ] && [ ! -L files/debian/opt ]
if [ ! -e files/debian/opt/foldgpt-gpu ]; then mkdir files/debian/opt/foldgpt-gpu; fi
[ ! -L files/debian/opt/foldgpt-gpu ]
[ ! -e "$destination" ] && [ ! -L "$destination" ]
stage={revision_stage}
mkdir -m 700 "$stage"
cleanup() {{
    [ ! -L "$stage" ] && [ "$(readlink -f "$stage")" = /data/user/0/app.foldgpt/{revision_stage} ] || return 1
    rm -rf -- "$stage"
}}
trap cleanup EXIT
tar -xzf - -C "$stage"
payload="$stage/{PREFIX}"
for required in bin/vulkan-clear-probe bin/glx-clear-probe bin/vulkan-timestamp-probe lib/libGL.so.1 lib/libEGL.so.1 lib/libvulkan_freedreno.so share/vulkan/icd.d/freedreno_icd.aarch64.json; do
    test -r "$payload/$required"
done
test -x "$payload/bin/vulkan-clear-probe"
# Same filesystem, no merge into or replacement of an existing revision.
mv -nT "$payload" "$destination"
test ! -d "$payload"
test -x "$destination/bin/vulkan-clear-probe"
"""
    adb = ["adb", "-s", args.serial]
    staging = "/data/local/tmp/foldgpt-gpu-" + uuid.uuid4().hex
    remote = staging + "/mesa.tar.gz"
    subprocess.run(adb + ["shell", "mkdir", "-m", "700", staging], check=True)
    try:
        # Use ADB's binary-safe file transfer, then a pipe wholly on Android.
        # Windows ADB shell stdin truncated the compressed archive in testing.
        with tempfile.TemporaryDirectory(prefix="foldgpt-gpu-snapshot-") as local_stage:
            snapshot = Path(local_stage) / "mesa.tar.gz"
            snapshot.write_bytes(data)
            subprocess.run(adb + ["push", str(snapshot), remote], check=True, timeout=120)
        digest = subprocess.check_output(adb + ["shell", "sha256sum", remote], text=True).split()[0]
        if digest != expected_digest:
            raise RuntimeError("GPU archive changed during ADB transfer")
        extraction = "set -o pipefail; cat " + shlex.quote(remote)
        extraction += " | run-as app.foldgpt sh -c " + shlex.quote(command)
        subprocess.run(adb + ["shell", extraction], check=True, timeout=120)
    finally:
        # The random, exact directory is validated before nonrecursive cleanup.
        cleanup = f"""set -eu
[ ! -L {staging} ] && [ "$(readlink -f {staging})" = {staging} ]
rm -f {remote}
rmdir {staging}
"""
        subprocess.run(adb + ["shell", cleanup], check=True, timeout=30)
    print("Isolated GPU test prefix installed; system Mesa and the running client were not changed.")


if __name__ == "__main__":
    main()
