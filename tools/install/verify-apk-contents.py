"""Check development/production separation in an actual built APK, offline.

This checks packaged contents, not signing, provenance, device behavior or
release qualification. Never install the unsigned release-check artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

RUNTIME = {"libXlorie.so", "libandroid-shmem.so", "libfoldgpt-install.so",
           "libproot-loader.so", "libproot-loader32.so", "libproot.so", "libtalloc.so"}
DEBUG_CLASSES = (b"RootfsProbeService", b"ProotStorageProbeService", b"NativeRunnerProbeService", b"GuestAccountProbeService", b"InactivePreparationProbeService",
                 b"CodexProbeService", b"LandlockProbeReceiver")


def verify(apk, debug):
    with apk.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate APK entries")
            libraries = {name for name in names if name.startswith("lib/") and not name.endswith("/")}
            required = {"lib/arm64-v8a/" + name for name in RUNTIME}
            if not required.issubset(libraries) or (not debug and libraries != required):
                raise ValueError("APK native runtime differs: " + str(sorted(libraries ^ required)))
            dex = b"".join(archive.read(name) for name in names if name.endswith(".dex"))
            for descriptor in DEBUG_CLASSES:
                if (descriptor in dex) != debug:
                    raise ValueError("Wrong diagnostic class separation: " + descriptor.decode())
    return {"apk_sha256": digest, "variant": "debug" if debug else "release",
            "native_libraries": len(libraries), "diagnostic_separation": "PASS",
            "limit": "Package contents only, not a binary release qualification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.apk, args.debug), indent=2))
