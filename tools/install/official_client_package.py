"""Authenticate and inventory an official client input without installing it.

The Android coordinator owns the installation lease and readiness. This bounded
helper prepares a digest-bound dpkg input, or verifies its packaged files in an
inactive root. It never extracts archives, runs maintainer scripts, downloads an
unversioned package, modifies a rootfs, or claims complete runtime readiness.
"""
import argparse
import contextlib
import fcntl
import gzip
import hashlib
import io
import json
import lzma
import os
from pathlib import Path
import re
import stat
import tarfile


FORMAT = "foldgpt.official-client-input.v1"
SOURCE_URL = "https://persistent.oaistatic.com/codex-app-prod/linux/deb/latest/chatgpt_arm64.deb"
SOURCE_DOCUMENT = "https://learn.chatgpt.com/docs/linux/linux-app"
DESCRIPTOR_FIELDS = {"format", "sourceUrl", "sourceDocument", "package", "version",
                     "architecture", "sha256", "bytes", "maxTarBytes", "maxMembers"}
CHUNK = 1024 * 1024
CONTROL_LIMIT = 4 * CHUNK
CORE_EXECUTABLES = {"usr/lib/chatgpt/ChatGPT", "usr/lib/chatgpt/resources/codex"}


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def descriptor(value):
    """The caller must authenticate this descriptor independently of the input."""
    if set(value) != DESCRIPTOR_FIELDS:
        raise ValueError("Unexpected client descriptor fields")
    if (value["format"] != FORMAT or value["sourceUrl"] != SOURCE_URL
            or value["sourceDocument"] != SOURCE_DOCUMENT or value["package"] != "chatgpt"
            or value["architecture"] != "arm64"):
        raise ValueError("Unexpected official acquisition channel or package identity")
    if (not isinstance(value["version"], str)
            or re.fullmatch(r"[0-9][A-Za-z0-9.+:~\-]*", value["version"]) is None
            or not isinstance(value["sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None):
        raise ValueError("Invalid pinned version or SHA-256")
    for field in ("bytes", "maxTarBytes", "maxMembers"):
        if type(value[field]) is not int or not 0 < value[field] < 2 ** 63:
            raise ValueError("Invalid descriptor resource bound")
    return value


def exact(stream, size):
    data = stream.read(size)
    if len(data) != size:
        raise ValueError("Truncated package")
    return data


def copy_hash(stream, output=None, limit=None):
    digest, count = hashlib.sha256(), 0
    while True:
        block = stream.read(CHUNK if limit is None else min(CHUNK, limit - count + 1))
        if not block:
            break
        count += len(block)
        if limit is not None and count > limit:
            raise ValueError("Input exceeds authenticated size bound")
        digest.update(block)
        if output is not None:
            output.write(block)
    return digest.hexdigest(), count


def authenticate(stream, expected):
    stream.seek(0)
    sha, size = copy_hash(stream, limit=expected["bytes"])
    if (sha, size) != (expected["sha256"], expected["bytes"]):
        raise ValueError("Client package digest or size mismatch")
    stream.seek(0)


def ar_members(stream, total):
    if exact(stream, 8) != b"!<arch>\n":
        raise ValueError("Client is not a Debian ar archive")
    members = []
    while stream.tell() < total:
        header = exact(stream, 60)
        if header[58:] != b"`\n":
            raise ValueError("Invalid ar header")
        name = header[:16].decode("ascii").rstrip(" ").removesuffix("/")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise ValueError("Unsupported extended ar name")
        size_field = header[48:58].decode("ascii").strip()
        if not re.fullmatch(r"[0-9]+", size_field):
            raise ValueError("Invalid ar member size")
        size = int(size_field)
        offset = stream.tell()
        if offset + size + size % 2 > total:
            raise ValueError("ar member exceeds package")
        members.append((name, offset, size))
        stream.seek(offset + size)
        if size % 2 and exact(stream, 1) != b"\n":
            raise ValueError("Invalid ar alignment")
    names = [item[0] for item in members]
    if (len(names) not in (3, 4) or names[0] != "debian-binary"
            or names[1] not in ("control.tar.xz", "control.tar.gz")
            or names[2] not in ("data.tar.xz", "data.tar.gz")
            or (len(names) == 4 and names[3] != "_gpgorigin")):
        raise ValueError("Unsupported or duplicate Debian archive members")
    stream.seek(members[0][1])
    if members[0][2] != 4 or exact(stream, 4) != b"2.0\n":
        raise ValueError("Unsupported Debian format")
    return members


class Slice(io.RawIOBase):
    def __init__(self, stream, offset, size):
        self.stream, self.remaining = stream, size
        stream.seek(offset)

    def readable(self):
        return True

    def read(self, size=-1):
        size = self.remaining if size < 0 else min(size, self.remaining)
        data = self.stream.read(size)
        if len(data) != size:
            raise ValueError("Truncated compressed member")
        self.remaining -= size
        return data


class Bounded(io.RawIOBase):
    def __init__(self, stream, limit):
        self.stream, self.limit, self.count = stream, limit, 0

    def read(self, size=-1):
        size = self.limit + 1 if size < 0 else size
        data = self.stream.read(min(size, self.limit - self.count + 1))
        self.count += len(data)
        if self.count > self.limit:
            raise ValueError("Expanded tar exceeds authenticated resource bound")
        return data


def safe_name(name, directory=False):
    if directory and name in (".", "./"):
        return ""
    if name.startswith("./"):
        name = name[2:]
    if directory:
        name = name.removesuffix("/")
    if name == "" and directory:
        return name
    if (not name or name.startswith("/") or "\\" in name
            or any(ord(char) < 32 or ord(char) == 127 for char in name)
            or len(name.encode("utf-8")) >= 4096
            or any(part in ("", ".", "..") or len(part.encode("utf-8")) > 255 for part in name.split("/"))):
        raise ValueError("Unsafe package path")
    return name


def safe_link(name, target):
    if (not target or "\\" in target or len(target.encode("utf-8")) >= 4096
            or any(ord(char) < 32 or ord(char) == 127 for char in target)):
        raise ValueError("Unsafe package symlink")
    parts = [] if target.startswith("/") else name.split("/")[:-1]
    for part in target.split("/"):
        if part == "..":
            if not parts:
                raise ValueError("Package symlink escapes guest root")
            parts.pop()
        elif part not in ("", "."):
            parts.append(part)


def deb822(data):
    fields, previous = {}, None
    for line in data.decode("utf-8").splitlines():
        if not line:
            raise ValueError("Multiple or empty Debian control records")
        if line[0] in " \t":
            if previous is None:
                raise ValueError("Orphan control continuation")
            fields[previous] += "\n" + line[1:]
            continue
        match = re.fullmatch(r"([A-Za-z0-9][A-Za-z0-9-]*):[ \t]*(.*)", line)
        if not match:
            raise ValueError("Malformed Debian control field")
        key, value = match.groups()
        if key.lower() in fields:
            raise ValueError("Duplicate Debian control field")
        previous = key.lower()
        fields[previous] = value
    return fields


def inventory_tar(stream, member, expected, control=False):
    name, offset, size = member
    source = Slice(stream, offset, size)
    decoder = lzma.LZMAFile(source) if name.endswith(".xz") else gzip.GzipFile(fileobj=source)
    limit = CONTROL_LIMIT if control else expected["maxTarBytes"]
    bounded = Bounded(decoder, limit)
    entries, contents = {}, {}
    try:
        with tarfile.open(fileobj=bounded, mode="r|") as archive:
            for item in archive:
                if len(entries) >= expected["maxMembers"]:
                    raise ValueError("Too many package members")
                path = safe_name(item.name, item.isdir())
                if path in entries:
                    raise ValueError("Duplicate package path")
                if item.pax_headers or item.sparse is not None:
                    raise ValueError("Unsupported PAX or sparse package member")
                # Keep original regular-file modes; a verifier cannot silently
                # remove an official setuid bit and still claim unchanged files.
                record = {"path": path, "mode": item.mode}
                if item.isdir():
                    if item.size:
                        raise ValueError("Directory contains unexpected payload")
                    record["kind"] = "directory"
                elif item.issym() and not control:
                    if item.size:
                        raise ValueError("Symlink contains unexpected payload")
                    safe_link(path, item.linkname)
                    record.update(kind="symlink", target=item.linkname)
                elif item.isreg():
                    if item.size < 0 or item.size > limit:
                        raise ValueError("Invalid package file size")
                    file_stream = archive.extractfile(item)
                    if control:
                        content = file_stream.read(CONTROL_LIMIT + 1)
                        if len(content) != item.size:
                            raise ValueError("Truncated control file")
                        contents[path] = content
                        sha = hashlib.sha256(content).hexdigest()
                    else:
                        prefix = file_stream.read(min(64, item.size))
                        digest, count = hashlib.sha256(prefix), len(prefix)
                        while True:
                            block = file_stream.read(CHUNK)
                            if not block:
                                break
                            digest.update(block)
                            count += len(block)
                        sha = digest.hexdigest()
                        if count != item.size:
                            raise ValueError("Truncated package file")
                        if path in CORE_EXECUTABLES:
                            if (len(prefix) != 64 or prefix[:7] != b"\x7fELF\x02\x01\x01"
                                    or int.from_bytes(prefix[18:20], "little") != 183
                                    or not item.mode & 0o111):
                                raise ValueError("Official core executable is not executable ARM64 ELF")
                            record["elf"] = {"class": 64, "byteOrder": "little", "machine": 183}
                    record.update(kind="file", bytes=item.size, sha256=sha)
                else:
                    raise ValueError("Unsupported package member type")
                entries[path] = record
            # tarfile stops at the first null header. Remaining decoded blocks
            # must be zero padding, never a second hidden archive or payload.
            if archive.fileobj.tell() < archive.offset + 512:
                raise ValueError("Missing tar terminator")
            padding = 0
            while True:
                tail = archive.fileobj.read(CHUNK)
                if not tail:
                    break
                padding += len(tail)
                if any(tail):
                    raise ValueError("Nonzero data after tar terminator")
            if padding < 512:
                raise ValueError("Missing second tar terminator block")
        if bounded.count % 512:
            raise ValueError("Truncated tar alignment")
    finally:
        decoder.close()
    for path in entries:
        parts = path.split("/")
        for index in range(1, len(parts)):
            ancestor = "/".join(parts[:index])
            if ancestor in entries and entries[ancestor]["kind"] != "directory":
                raise ValueError("Package traverses a non-directory ancestor")
    return sorted(entries.values(), key=lambda item: item["path"]), contents, bounded.count


def inspect(stream, expected):
    expected = descriptor(expected)
    before = os.fstat(stream.fileno())
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("Package input must be a regular file")
    authenticate(stream, expected)
    members = ar_members(stream, expected["bytes"])
    control, content, _ = inventory_tar(stream, members[1], expected, control=True)
    if "control" not in content:
        raise ValueError("Missing Debian control file")
    fields = deb822(content["control"])
    for field in ("package", "version", "architecture"):
        if fields.get(field) != expected[field]:
            raise ValueError("Pinned package metadata mismatch: " + field)
    files, _, tar_bytes = inventory_tar(stream, members[2], expected)
    cores = {item["path"] for item in files if "elf" in item}
    if cores != CORE_EXECUTABLES:
        raise ValueError("Official package is missing a required ARM64 core executable")
    after = os.fstat(stream.fileno())
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise ValueError("Package changed during validation")
    result = {"format": FORMAT, "descriptor": expected, "controlFields": fields,
            "controlFiles": control, "files": files, "tarBytes": tar_bytes,
            "embeddedSignaturePresent": len(members) == 4,
            "embeddedSignatureVerified": False}
    if len(canonical(result)) > CONTROL_LIMIT:
        raise ValueError("Client inventory exceeds format size bound")
    return result


@contextlib.contextmanager
def directory(path, private=False):
    path = Path(path).absolute()
    if path.resolve(strict=True) != path:
        raise ValueError("Directory path contains symlink aliases")
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if private and (info.st_uid != os.geteuid() or info.st_mode & 0o077):
            raise ValueError("Preparation directory must belong to caller with private permissions")
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def regular(name, flags=os.O_RDONLY, parent=None):
    fd = os.open(name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=parent)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Expected a regular file")
        with os.fdopen(fd, "r+b" if flags & os.O_RDWR else "rb", closefd=False) as stream:
            yield stream
    finally:
        os.close(fd)


def read_json(name, parent=None):
    with regular(name, parent=parent) as stream:
        data = stream.read(CONTROL_LIMIT + 1)
        if len(data) > CONTROL_LIMIT:
            raise ValueError("JSON input exceeds size bound")
    return json.loads(data, object_pairs_hook=unique_json)


def publish_json(parent, name, value):
    temporary = name + ".partial"
    # Partial metadata is never authoritative. Recreate only this named scratch
    # file while the directory lock is held, without following a planted link.
    try:
        os.unlink(temporary, dir_fd=parent)
    except FileNotFoundError:
        pass
    with regular(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL, parent) as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.rename(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
    os.fsync(parent)


def prepare(source, expected, stage):
    """Resume the same pinned input in an existing coordinator-owned directory.

    The caller creates its own private stage and holds the installation lease.
    A supplementary per-stage flock serializes this bounded operation. A crash
    can leave .partial bytes; a retry reuses only a completely authenticated .deb.
    """
    expected = descriptor(expected)
    with directory(stage, private=True) as parent:
        with regular("client-input.lock", os.O_RDWR | os.O_CREAT, parent) as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            allowed = {"client-input.lock", "descriptor.json", "descriptor.json.partial",
                       "package.deb", "package.deb.partial", "inventory.json", "inventory.json.partial"}
            if set(os.listdir(parent)) - allowed:
                raise ValueError("Client input stage contains unrelated files")
            names = set(os.listdir(parent))
            if "descriptor.json" in names:
                if read_json("descriptor.json", parent) != expected:
                    raise ValueError("Preparation stage belongs to a different pinned client")
            elif names - {"client-input.lock", "descriptor.json.partial"}:
                raise ValueError("Unbound preparation content cannot be adopted")
            else:
                publish_json(parent, "descriptor.json", expected)
            if "package.deb" not in names:
                if source is None:
                    raise ValueError("Source package is required for unfinished copy")
                try:
                    os.unlink("package.deb.partial", dir_fd=parent)
                except FileNotFoundError:
                    pass
                with regular(source) as incoming, regular(
                        "package.deb.partial", os.O_RDWR | os.O_CREAT | os.O_EXCL, parent) as output:
                    sha, size = copy_hash(incoming, output, expected["bytes"])
                    if (sha, size) != (expected["sha256"], expected["bytes"]):
                        raise ValueError("Copied package digest or size mismatch")
                    output.flush()
                    os.fsync(output.fileno())
                    result = inspect(output, expected)
                os.rename("package.deb.partial", "package.deb", src_dir_fd=parent, dst_dir_fd=parent)
                os.fsync(parent)
            else:
                with regular("package.deb", parent=parent) as stream:
                    result = inspect(stream, expected)
            if "inventory.json" in names:
                if read_json("inventory.json", parent) != result:
                    raise ValueError("Existing package inventory does not match actual package")
            else:
                publish_json(parent, "inventory.json", result)
            return result


@contextlib.contextmanager
def parent_for(root, path):
    parts = path.split("/")
    opened = []
    current = root
    try:
        for part in parts[:-1]:
            current = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            opened.append(current)
        yield current, parts[-1]
    finally:
        for fd in reversed(opened):
            os.close(fd)


def verify_files(root, inventory):
    """Read-only packaged-file verification; no dpkg/dependency/readiness claim.

    The inventory must come from inspect() on the authenticated immutable input.
    Parent directories never follow links. Guest absolute symlinks are compared
    as text, never interpreted against Android/the host's filesystem.
    """
    checked = 0
    with directory(root) as root_fd:
        identity = os.fstat(root_fd)
        for item in inventory["files"]:
            path = safe_name(item["path"], item["kind"] == "directory")
            if not path:
                continue  # package root metadata does not own the stage root
            with parent_for(root_fd, path) as (parent, leaf):
                before = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                kind = item["kind"]
                if kind == "directory":
                    if not stat.S_ISDIR(before.st_mode):
                        raise ValueError("Packaged directory differs: " + path)
                    # Shared Debian directories are not solely owned by client.
                elif kind == "symlink":
                    if not stat.S_ISLNK(before.st_mode) or os.readlink(leaf, dir_fd=parent) != item["target"]:
                        raise ValueError("Packaged symlink differs: " + path)
                elif kind == "file":
                    with regular(leaf, parent=parent) as stream:
                        start = os.fstat(stream.fileno())
                        sha, size = copy_hash(stream, limit=item["bytes"])
                        end = os.fstat(stream.fileno())
                    if ((start.st_dev, start.st_ino) != (before.st_dev, before.st_ino)
                            or (start.st_size, start.st_mtime_ns, start.st_ctime_ns)
                            != (end.st_size, end.st_mtime_ns, end.st_ctime_ns)
                            or (sha, size) != (item["sha256"], item["bytes"])
                            or stat.S_IMODE(start.st_mode) != item["mode"]):
                        raise ValueError("Packaged file differs: " + path)
                else:
                    raise ValueError("Unknown inventory member kind")
                after = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if (before.st_dev, before.st_ino, before.st_ctime_ns) != (
                        after.st_dev, after.st_ino, after.st_ctime_ns):
                    raise ValueError("Packaged path changed during verification: " + path)
                checked += 1
    return {"scope": "packaged-files-only", "checked": checked,
            "rootDevice": identity.st_dev, "rootInode": identity.st_ino,
            "packageSha256": inventory["descriptor"]["sha256"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("inspect", "prepare", "verify-files"))
    parser.add_argument("--descriptor", required=True,
                        help="Independently authenticated version/hash/bounds; never generated from untrusted input")
    parser.add_argument("--package", help="Existing official .deb input; optional only for a complete prepare resume")
    parser.add_argument("--stage", help="Empty or matching private directory owned by installation coordinator")
    parser.add_argument("--root", help="Inactive root whose packaged files should be checked")
    args = parser.parse_args()
    expected = descriptor(read_json(args.descriptor))
    if args.operation == "prepare":
        if not args.stage:
            parser.error("prepare requires --stage")
        result = prepare(args.package, expected, args.stage)
    else:
        if not args.package:
            parser.error("inspect and verify-files require --package")
        with regular(args.package) as stream:
            result = inspect(stream, expected)
        if args.operation == "verify-files":
            if not args.root:
                parser.error("verify-files requires --root")
            result = verify_files(args.root, result)
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == "__main__":
    main()
