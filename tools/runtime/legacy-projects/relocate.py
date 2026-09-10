"""Inventory and copy one legacy project without following links or replacing data.

Linux/Android only. Descriptor-relative traversal and renameat2(NOREPLACE) are
required, never emulated. This is an offline data tool, not an app-server proxy.
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import PurePosixPath
import stat
import sys
import uuid

SCHEMA = "foldgpt.legacy-project-inventory.v1"
COPY_SCHEMA = "foldgpt.legacy-project-copy.v1"
CHUNK = 1024 * 1024


class Refused(RuntimeError):
    def __init__(self, message, *, retained_stage=None, published=False, errno=None):
        super().__init__(message)
        self.retained_stage = retained_stage
        self.published = published
        self.errno = errno


def require_platform():
    if os.name != "posix" or not sys.platform.startswith(("linux", "android")):
        raise Refused("Linux/Android descriptor semantics are required")
    if os.geteuid() == 0:
        raise Refused("Run as the ordinary project owner, never root")
    for operation in (os.open, os.stat, os.mkdir):
        if operation not in os.supports_dir_fd:
            raise Refused("Required dir_fd operations are unavailable")


def absolute(value):
    value = os.fspath(value)
    if (not value.startswith("/") or value.startswith("//") or "\0" in value
            or any(piece in ("", ".", "..") for piece in value.split("/")[1:])):
        raise Refused("Expected a canonical absolute path without aliases")
    return PurePosixPath(value)


def child_name(value):
    if not isinstance(value, str) or value in ("", ".", "..") or "/" in value or "\0" in value:
        raise Refused("Destination name must be one ordinary path component")
    return value


def stamp(info):
    return {"device": info.st_dev, "inode": info.st_ino, "mode": info.st_mode,
            "uid": info.st_uid, "gid": info.st_gid, "links": info.st_nlink,
            "bytes": info.st_size, "mtimeNs": info.st_mtime_ns, "ctimeNs": info.st_ctime_ns}


def identity(info):
    return info.st_dev, info.st_ino


@contextlib.contextmanager
def pin_directory(value):
    path = absolute(value)
    # Android ancestors such as /data permit traversal without directory reads.
    # O_PATH pins those real directories without demanding unrelated read access;
    # O_DIRECTORY|O_NOFOLLOW still rejects every symlink component.
    descriptor = os.open("/", os.O_PATH | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for index, component in enumerate(path.parts[1:], 1):
            access = os.O_RDONLY if index == len(path.parts) - 1 else os.O_PATH
            following = os.open(component, access | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=descriptor)
            os.close(descriptor)
            descriptor = following
        yield descriptor
    finally:
        os.close(descriptor)


def fingerprint(value):
    data = json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def content_entries(entries):
    # Relocation changes inodes, ownership, timestamps and directory metadata.
    return [{key: entry[key] for key in ("path", "kind", "sha256", "bytes", "executable") if key in entry}
            for entry in entries]


def inspect_tree(root_fd, *, copy_fd=None):
    root_info = os.fstat(root_fd)
    expected_device, expected_uid = root_info.st_dev, root_info.st_uid
    seen = set()
    entries = []

    def walk(directory_fd, relative, target_fd):
        before = os.fstat(directory_fd)
        if (not stat.S_ISDIR(before.st_mode) or before.st_dev != expected_device
                or before.st_uid != expected_uid or identity(before) in seen):
            raise Refused("Directory alias, mount or foreign owner: " + relative)
        seen.add(identity(before))
        names = sorted(os.listdir(directory_fd))
        entries.append({"path": relative, "kind": "directory", "stat": stamp(before)})
        for name in names:
            child_name(name)
            path = name if relative == "." else relative + "/" + name
            observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if observed.st_dev != expected_device or observed.st_uid != expected_uid:
                raise Refused("Mount or foreign owner: " + path)
            if stat.S_ISDIR(observed.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                dir_fd=directory_fd)
                destination = None
                try:
                    if stamp(os.fstat(child)) != stamp(observed):
                        raise Refused("Directory changed before opening: " + path)
                    if target_fd is not None:
                        os.mkdir(name, mode=0o700, dir_fd=target_fd)
                        destination = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                              dir_fd=target_fd)
                    walk(child, path, destination)
                finally:
                    if destination is not None:
                        os.close(destination)
                    os.close(child)
            elif stat.S_ISREG(observed.st_mode) and observed.st_nlink == 1:
                # O_NONBLOCK prevents a swapped FIFO from hanging before fstat.
                descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                                     dir_fd=directory_fd)
                destination = None
                try:
                    opened = os.fstat(descriptor)
                    if stamp(opened) != stamp(observed) or identity(opened) in seen:
                        raise Refused("File changed or aliased before opening: " + path)
                    seen.add(identity(opened))
                    executable = bool(opened.st_mode & 0o111)
                    if target_fd is not None:
                        destination = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                              0o700 if executable else 0o600, dir_fd=target_fd)
                    digest = hashlib.sha256()
                    count = 0
                    while True:
                        data = os.read(descriptor, CHUNK)
                        if not data:
                            break
                        count += len(data)
                        digest.update(data)
                        if destination is not None:
                            remaining = memoryview(data)
                            while remaining:
                                written = os.write(destination, remaining)
                                if written <= 0:
                                    raise OSError("Copy made no write progress")
                                remaining = remaining[written:]
                    if (stamp(os.fstat(descriptor)) != stamp(opened) or count != opened.st_size
                            or stamp(os.stat(name, dir_fd=directory_fd, follow_symlinks=False)) != stamp(opened)):
                        raise Refused("File changed while reading: " + path)
                    if destination is not None:
                        os.fsync(destination)
                    entries.append({"path": path, "kind": "file", "stat": stamp(opened),
                                    "bytes": count, "sha256": digest.hexdigest(), "executable": executable})
                finally:
                    if destination is not None:
                        os.close(destination)
                    os.close(descriptor)
            else:
                raise Refused("Symlink, hardlink or special file: " + path)
        if sorted(os.listdir(directory_fd)) != names or stamp(os.fstat(directory_fd)) != stamp(before):
            raise Refused("Directory changed while reading: " + relative)
        if target_fd is not None:
            os.fsync(target_fd)

    walk(root_fd, ".", copy_fd)
    return entries


def require_source(source, boundary):
    source, boundary = absolute(source), absolute(boundary)
    if not source.is_relative_to(boundary):
        raise Refused("Source is outside the explicitly selected legacy boundary")
    return source, boundary


def inventory(source, boundary):
    require_platform()
    source, boundary = require_source(source, boundary)
    with pin_directory(source) as descriptor:
        entries = inspect_tree(descriptor)
        # Second full pass detects changes after a child was first inspected.
        if inspect_tree(descriptor) != entries:
            raise Refused("Source changed between inventory passes")
        with pin_directory(source) as current:
            if identity(os.fstat(current)) != identity(os.fstat(descriptor)):
                raise Refused("Source root was replaced")
    value = {"schema": SCHEMA, "source": str(source), "sourceBoundary": str(boundary), "entries": entries}
    return {**value, "inventorySha256": fingerprint(value),
            "contentSha256": fingerprint(content_entries(entries)),
            "fileCount": sum(entry["kind"] == "file" for entry in entries),
            "totalBytes": sum(entry.get("bytes", 0) for entry in entries)}


def publish_noreplace(parent_fd, source_name, target_name):
    # Both names are siblings on one pinned filesystem. Never substitute rename.
    library = ctypes.CDLL(None, use_errno=True)
    try:
        function = library.renameat2
    except AttributeError as error:
        raise Refused("renameat2(NOREPLACE) is required; staging retained") from error
    function.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    function.restype = ctypes.c_int
    if function(parent_fd, os.fsencode(source_name), parent_fd, os.fsencode(target_name), 1) != 0:
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), target_name)


def copy_project(source, boundary, destination_root, name, expected_inventory_sha256):
    require_platform()
    source, boundary = require_source(source, boundary)
    destination_root, name = absolute(destination_root), child_name(name)
    if source.is_relative_to(destination_root) or destination_root.is_relative_to(source):
        raise Refused("Source and destination root must be disjoint")
    if (not isinstance(expected_inventory_sha256, str) or len(expected_inventory_sha256) != 64
            or any(c not in "0123456789abcdef" for c in expected_inventory_sha256)):
        raise Refused("An explicit reviewed inventory SHA-256 is required")
    expected = inventory(source, boundary)
    if expected["inventorySha256"] != expected_inventory_sha256:
        raise Refused("Source no longer matches the reviewed inventory")
    stage_name = ".foldgpt-import-" + uuid.uuid4().hex
    stage_path = str(destination_root / stage_name)
    published = False
    with pin_directory(source) as source_fd, pin_directory(destination_root) as parent_fd:
        try:
            os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            raise Refused("Destination already exists; nothing will be replaced")
        os.mkdir(stage_name, mode=0o700, dir_fd=parent_fd)
        stage_fd = None
        try:
            stage_fd = os.open(stage_name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                               dir_fd=parent_fd)
            copied_source = inspect_tree(source_fd, copy_fd=stage_fd)
            if copied_source != expected["entries"] or inspect_tree(source_fd) != expected["entries"]:
                raise Refused("Source changed during relocation")
            copied = inspect_tree(stage_fd)
            if content_entries(copied) != content_entries(expected["entries"]):
                raise Refused("Destination content verification failed")
            # Check both public root names still designate the pinned directories.
            with pin_directory(source) as current_source, pin_directory(destination_root) as current_parent:
                if (identity(os.fstat(current_source)) != identity(os.fstat(source_fd))
                        or identity(os.fstat(current_parent)) != identity(os.fstat(parent_fd))):
                    raise Refused("Source or destination root was replaced")
            if identity(os.stat(stage_name, dir_fd=parent_fd, follow_symlinks=False)) != identity(os.fstat(stage_fd)):
                raise Refused("Staging directory was replaced")
            publish_noreplace(parent_fd, stage_name, name)
            published = True
            os.fsync(parent_fd)
            if content_entries(inspect_tree(stage_fd)) != content_entries(expected["entries"]):
                raise Refused("Published content changed before final verification")
            with pin_directory(destination_root) as current_parent:
                if (identity(os.fstat(current_parent)) != identity(os.fstat(parent_fd))
                        or identity(os.stat(name, dir_fd=parent_fd, follow_symlinks=False))
                        != identity(os.fstat(stage_fd))):
                    raise Refused("Published directory or its root was replaced")
            return {"schema": COPY_SCHEMA, "copied": True, "published": True,
                    "source": str(source), "destination": str(destination_root / name),
                    "sourceInventorySha256": expected_inventory_sha256,
                    "contentSha256": expected["contentSha256"], "fileCount": expected["fileCount"],
                    "totalBytes": expected["totalBytes"], "sourceDeleted": False,
                    "threadMetadataChanged": False}
        except Exception as error:
            retained = str(destination_root / name) if published else stage_path
            raise Refused(str(error), retained_stage=retained, published=published,
                          errno=getattr(error, "errno", None)) from error
        finally:
            if stage_fd is not None:
                os.close(stage_fd)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inventory", "copy"))
    parser.add_argument("--source", required=True)
    parser.add_argument("--source-boundary", required=True)
    parser.add_argument("--destination-root")
    parser.add_argument("--name")
    parser.add_argument("--expected-inventory-sha256")
    args = parser.parse_args(argv)
    try:
        if args.operation == "inventory":
            result = inventory(args.source, args.source_boundary)
        else:
            if not all((args.destination_root, args.name, args.expected_inventory_sha256)):
                raise Refused("copy requires destination-root, name and expected-inventory-sha256")
            result = copy_project(args.source, args.source_boundary, args.destination_root,
                                  args.name, args.expected_inventory_sha256)
        print(json.dumps(result, ensure_ascii=True, indent=2))
        return 0
    except (Refused, OSError) as error:
        print(json.dumps({"passed": False, "error": str(error),
                          "errno": getattr(error, "errno", None),
                          "published": getattr(error, "published", False),
                          "retainedStage": getattr(error, "retained_stage", None)}, ensure_ascii=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
