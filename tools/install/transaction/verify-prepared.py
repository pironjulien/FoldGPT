"""Independently compare a prepared host tree to a trusted archive; never extract.

Run on Linux against an inactive, exclusively owned staging tree. Python tarfile
is independent of the Java extractor. No Android connection or guest execution.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile


def digest(stream):
    result = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        result.update(block)
    return result.hexdigest()


def verify(archive, expected_sha, root):
    root = root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("A real inactive root directory is required")
    owner = root.stat().st_uid
    expected = set()
    counts = {"regular": 0, "directory": 0, "symlink": 0, "hardlink": 0}
    payload = 0
    with archive.open("rb") as source:
        if digest(source) != expected_sha:
            raise ValueError("Archive differs from the externally trusted digest")
        source.seek(0)
        with tarfile.open(fileobj=source, mode="r|gz") as entries:
            for entry in entries:
                name = str(PurePosixPath(entry.name))
                if name.startswith("/") or ".." in PurePosixPath(name).parts or name in expected:
                    raise ValueError("Unexpected archive path")
                expected.add(name)
                path = root / name
                # Never use a guest symlink as an ancestor, including absolute
                # Debian links, which refer to the guest, not this host.
                for parent in path.relative_to(root).parents:
                    if (root / parent).is_symlink():
                        raise ValueError("Symlink parent in prepared tree: " + name)
                actual = path.lstat()
                if actual.st_uid != owner:
                    raise ValueError("Foreign owner: " + name)
                if stat.S_IMODE(actual.st_mode) != entry.mode:
                    raise ValueError("Mode differs: " + name)
                timestamp = Decimal(entry.pax_headers.get("mtime", str(entry.mtime)))
                # OpenJDK 17 UnixFileAttributeViews applies microsecond times.
                expected_ns = int(timestamp * 1_000_000_000)
                if not 0 <= expected_ns - actual.st_mtime_ns < 1000:
                    raise ValueError("mtime differs: " + name)
                if entry.isdir():
                    if not stat.S_ISDIR(actual.st_mode):
                        raise ValueError("Not a directory: " + name)
                    counts["directory"] += 1
                elif entry.issym():
                    if not stat.S_ISLNK(actual.st_mode) or os.readlink(path) != entry.linkname:
                        raise ValueError("Symlink differs: " + name)
                    counts["symlink"] += 1
                elif entry.islnk():
                    target_name = PurePosixPath(entry.linkname)
                    if target_name.is_absolute() or ".." in target_name.parts:
                        raise ValueError("Unsafe hardlink input")
                    target = (root / target_name).lstat()
                    if not stat.S_ISREG(actual.st_mode) or (actual.st_dev, actual.st_ino) != (target.st_dev, target.st_ino):
                        raise ValueError("Hardlink differs: " + name)
                    counts["hardlink"] += 1
                elif entry.isfile():
                    if not stat.S_ISREG(actual.st_mode) or actual.st_size != entry.size:
                        raise ValueError("File type or size differs: " + name)
                    with path.open("rb") as local:
                        if digest(local) != digest(entries.extractfile(entry)):
                            raise ValueError("File contents differ: " + name)
                    payload += entry.size
                    counts["regular"] += 1
                else:
                    raise ValueError("Unsupported archive type")
    observed = {"."}
    for directory, directories, files in os.walk(root, followlinks=False):
        for name in directories + files:
            observed.add(str((Path(directory) / name).relative_to(root)))
    if observed != expected:
        raise ValueError("Missing or additional paths in prepared root")
    return {"archive_sha256": expected_sha, "members": len(expected),
            "counts": counts, "regular_payload_bytes": payload,
            "root": str(root), "owner_uid": owner, "content_modes_links_verified": True,
            "mtime_precision": "microsecond", "android_execution": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--root", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(verify(args.archive, args.sha256, args.root), indent=2))
