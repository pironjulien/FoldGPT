"""Build, verify and prepare FoldGPT's guest integration files; never install Linux.

The small, canonical bundle contains only named repository sources and LICENSE.
Verification requires an independently trusted archive SHA-256. Preparation
creates a new directory atomically on Linux; it never merges into a rootfs.
"""
import argparse
import ctypes
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import uuid


ROOT = Path(__file__).resolve().parents[2]
FORMAT = "foldgpt.guest-integration.v1"
MAX_FILE_BYTES = 1024 * 1024
MAX_BUNDLE_BYTES = 8 * 1024 * 1024
# Positive source/destination list: never collect a rootfs, account or binary.
SOURCES = {
    "LICENSE": ("LICENSE", 0o644),
    "foldgpt-session.sh": ("payload/usr/local/bin/foldgpt-session", 0o700),
    "foldgpt_keyring.py": ("payload/usr/local/lib/foldgpt/foldgpt_keyring.py", 0o644),
    "foldgpt_ime.py": ("payload/usr/local/lib/foldgpt/foldgpt_ime.py", 0o644),
    "keyboard-focus.js": ("payload/usr/local/lib/foldgpt/keyboard-focus.js", 0o644),
}
MODES = {name: mode for name, mode in SOURCES.values()}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=True, sort_keys=True, indent=2) + "\n").encode()


def _manifest(files):
    return {
        "format": FORMAT,
        "kind": "guest-integration-only",
        "files": [{"path": path, "size": len(data), "mode": MODES[path],
                   "sha256": digest(data)} for path, data in sorted(files.items())],
    }


def _archive(files):
    entries = {**files, "manifest.json": json_bytes(_manifest(files))}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name, data in sorted(entries.items()):
            item = tarfile.TarInfo(name)
            item.size = len(data)
            item.mode = MODES.get(name, 0o644)
            # USTAR regular files, uid/gid/mtime zero and no host owner names.
            archive.addfile(item, io.BytesIO(data))
    return output.getvalue()


def read_bounded(path, limit):
    """Read one byte snapshot, rejecting links, special files and oversized input."""
    path = Path(path)
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Input must be a regular file: " + path.name)
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("Input was replaced while opening: " + path.name)
        data = stream.read(limit + 1)
        after = os.fstat(stream.fileno())
        if (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise ValueError("Input changed while reading: " + path.name)
    if len(data) > limit:
        raise ValueError("Input exceeds bundle format limit: " + path.name)
    return data


def build(root=ROOT):
    root = Path(root).resolve(strict=True)
    files = {}
    for source, (destination, _) in SOURCES.items():
        data = read_bounded(root / source, MAX_FILE_BYTES)
        # Sources are portable UTF-8 text. Normalize Git checkout line endings.
        data.decode("utf-8")
        if b"\0" in data:
            raise ValueError("Integration source contains a NUL byte: " + source)
        files[destination] = data.replace(b"\r\n", b"\n")
    result = _archive(files)
    verify(result, digest(result))
    return result


def verify(data, expected_sha256):
    if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("An independently trusted lowercase SHA-256 is required")
    if len(data) > MAX_BUNDLE_BYTES or digest(data) != expected_sha256:
        raise ValueError("Bundle size or SHA-256 verification failed")
    files = {}
    manifest_data = None
    try:
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
            for item in archive:
                if item.name in files or (item.name == "manifest.json" and manifest_data is not None):
                    raise ValueError("Duplicate bundle entry")
                if item.name not in MODES and item.name != "manifest.json":
                    raise ValueError("Entry is not an allowed integration path")
                if item.type != tarfile.REGTYPE or item.size < 0 or item.size > MAX_FILE_BYTES:
                    raise ValueError("Only bounded regular integration files are permitted")
                if item.mode != MODES.get(item.name, 0o644):
                    raise ValueError("Unexpected integration file permissions")
                content = archive.extractfile(item).read(MAX_FILE_BYTES + 1)
                if len(content) != item.size:
                    raise ValueError("Truncated integration file")
                try:
                    content.decode("utf-8")
                except UnicodeError as error:
                    raise ValueError("Integration entries must contain UTF-8 text") from error
                if b"\0" in content or b"\r\n" in content:
                    raise ValueError("Integration entries must contain normalized text without NUL bytes")
                if item.name == "manifest.json":
                    manifest_data = content
                else:
                    files[item.name] = content
    except (tarfile.TarError, OSError) as error:
        raise ValueError("Invalid uncompressed USTAR bundle") from error
    if files.keys() != MODES.keys() or manifest_data is None:
        raise ValueError("Bundle is missing a required integration file")
    # Compare canonical JSON directly: duplicate keys, unknown fields, altered
    # sizes/hashes and parser ambiguities cannot become a second interpretation.
    if manifest_data != json_bytes(_manifest(files)):
        raise ValueError("Bundle manifest does not describe the exact allowed files")
    # Also rejects PAX/GNU headers, alternate names, concatenation, truncation,
    # nonzero owner/time metadata and trailing bytes ignored by tar readers.
    if data != _archive(files):
        raise ValueError("Bundle is not in the canonical archive format")
    return {**files, "manifest.json": manifest_data}


def write_new_archive(path, data):
    """Publish a complete file with an atomic, exclusive hard link; never replace."""
    path = Path(path).absolute()
    parent = path.parent.resolve(strict=True)
    if parent != path.parent:
        raise ValueError("Output parent must not contain symlink aliases")
    if os.name == "posix":
        directory = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            _require_private_parent(directory)
        finally:
            os.close(directory)
    fd, temporary = tempfile.mkstemp(prefix=".foldgpt-bundle-", dir=parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
    finally:
        Path(temporary).unlink()


def _require_private_parent(fd):
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or info.st_mode & 0o022:
        raise ValueError("Parent must belong to the caller and forbid group/other writes")


def _rename_new(parent_fd, source, destination):
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        rename = libc.renameat2
    except AttributeError as error:
        raise RuntimeError("Linux renameat2 is required; no overwrite fallback exists") from error
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(parent_fd, os.fsencode(source), parent_fd, os.fsencode(destination), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), destination)


def _write_entries(stage_fd, entries):
    descriptors = {"": stage_fd}
    try:
        for name, data in sorted(entries.items()):
            parts = name.split("/")
            prefix = ""
            for part in parts[:-1]:
                child = prefix + "/" + part if prefix else part
                if child not in descriptors:
                    os.mkdir(part, mode=0o700, dir_fd=descriptors[prefix])
                    descriptors[child] = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                                 dir_fd=descriptors[prefix])
                    if stat.S_IMODE(os.fstat(descriptors[child]).st_mode) != 0o700:
                        raise OSError("Preparation filesystem must enforce POSIX directory modes")
                prefix = child
            fd = os.open(parts[-1], os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=descriptors[prefix])
            try:
                remaining = memoryview(data)
                while remaining:
                    written = os.write(fd, remaining)
                    if written == 0:
                        raise OSError("Integration file write made no progress")
                    remaining = remaining[written:]
                os.fchmod(fd, MODES.get(name, 0o644))
                if stat.S_IMODE(os.fstat(fd).st_mode) != MODES.get(name, 0o644):
                    raise OSError("Preparation filesystem must enforce POSIX file modes")
                os.fsync(fd)
            finally:
                os.close(fd)
        for fd in reversed(list(descriptors.values())):
            os.fsync(fd)
    finally:
        for name, fd in descriptors.items():
            if name:
                os.close(fd)


def prepare(data, expected_sha256, destination):
    """Materialize a verified overlay bundle in a NEW Linux directory, not a rootfs."""
    entries = verify(data, expected_sha256)
    if sys.platform != "linux" or not shutil.rmtree.avoids_symlink_attacks:
        raise RuntimeError("Preparation requires Linux fd-relative filesystem operations")
    destination = Path(destination).absolute()
    parent = destination.parent.resolve(strict=True)
    if parent != destination.parent or destination.name in ("", ".", ".."):
        raise ValueError("Destination requires a real parent and a new directory name")
    parent_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    stage_name = ".foldgpt-stage-" + uuid.uuid4().hex
    created = False
    promoted = False
    try:
        # 0700 on the staging directory alone cannot stop another user from
        # replacing its name in a shared writable parent before promotion.
        _require_private_parent(parent_fd)
        os.mkdir(stage_name, mode=0o700, dir_fd=parent_fd)
        created = True
        stage_fd = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            if stat.S_IMODE(os.fstat(stage_fd).st_mode) != 0o700:
                raise OSError("Preparation requires a private POSIX staging directory")
            _write_entries(stage_fd, entries)
        finally:
            os.close(stage_fd)
        _rename_new(parent_fd, stage_name, destination.name)
        promoted = True
        os.fsync(parent_fd)
    finally:
        try:
            if created and not promoted:
                shutil.rmtree(stage_name, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    return destination


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("build", help="Assemble the five named source files only")
    pack.add_argument("--output", type=Path, required=True)
    for name in ("verify", "prepare"):
        operation = commands.add_parser(name)
        operation.add_argument("--archive", type=Path, required=True)
        operation.add_argument("--sha256", required=True)
        if name == "prepare":
            operation.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "build":
        data = build()
        write_new_archive(args.output, data)
    else:
        data = read_bounded(args.archive, MAX_BUNDLE_BYTES)
        verify(data, args.sha256)
        if args.command == "prepare":
            prepare(data, args.sha256, args.destination)
    print(json.dumps({"operation": args.command, "format": FORMAT, "sha256": digest(data),
                      "bytes": len(data), "linuxInstalled": False}))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, RuntimeError) as error:
        print("FoldGPT guest bundle: " + str(error), file=sys.stderr)
        raise SystemExit(1)
