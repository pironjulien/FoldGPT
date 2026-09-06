"""Compare a retrieved Android probe inventory with the pinned Debian archive.

Read-only host check; no ADB, network, extraction, account or guest execution.
The inventory is Android's observed filesystem data, not an attestation: the
coordinator must independently retrieve it and inspect the actual on-device tree.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import tarfile

SHA256 = "dd0aac2065057596d4210848eab198f3c3abd43dad2baa4622f5537e4ad3279f"
COMPRESSED_BYTES = 327673156
MEMBERS = 20240
PROOT_BACKEND = "proot-termux-l2s-7266fb3-v1"


def canonical_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Path is outside the guest root")
    return str(path)


def archive_members(archive):
    """Hash and independently parse the same source descriptor, without extraction."""
    expected = {}
    with archive.open("rb") as stream:
        if stream.seek(0, 2) != COMPRESSED_BYTES:
            raise ValueError("Unexpected source archive size")
        stream.seek(0)
        if digest(stream) != SHA256:
            raise ValueError("Source archive differs from pinned artifact")
        stream.seek(0)
        with tarfile.open(fileobj=stream, mode="r|gz") as entries:
            for entry in entries:
                name = canonical_member(entry.name)
                if name in expected:
                    raise ValueError("Duplicate archive member: " + name)
                item = {"mode": entry.mode, "mtime": int(Decimal(
                    entry.pax_headers.get("mtime", str(entry.mtime))) * 1_000_000_000)}
                if entry.isdir():
                    item["type"] = "directory"
                elif entry.issym():
                    item.update(type="symlink", target=entry.linkname)
                elif entry.islnk():
                    item.update(type="hardlink", target=canonical_member(entry.linkname))
                elif entry.isfile():
                    item.update(type="regular", size=entry.size,
                                sha256=digest(entries.extractfile(entry)), links=1)
                else:
                    raise ValueError("Unexpected archive type")
                expected[name] = item
    if len(expected) != MEMBERS:
        raise ValueError("Source archive count differs")
    return expected


def physical_members(logical, backend, root):
    """Project a declared ABI; never infer a hardlink substitute from output."""
    expected = {name: dict(value) for name, value in logical.items()}
    groups = {}
    for name, value in logical.items():
        if value["type"] != "hardlink":
            continue
        source = logical.get(value["target"])
        if (source is None or source["type"] != "regular"
                or any(source[key] != value[key] for key in ("mode", "mtime"))):
            raise ValueError("Unsupported archived hardlink group")
        groups.setdefault(value["target"], []).append(name)
    for source, aliases in groups.items():
        count = len(aliases) + 1
        if backend == "native-posix-v1":
            for name in [source, *aliases]:
                expected[name] = dict(logical[source], links=count)
            continue
        path = PurePosixPath(source)
        intermediate = str(path.with_name(".l2s." + path.name + "0001"))
        backing = intermediate + f".{count:04d}"
        if intermediate in expected or backing in expected:
            raise ValueError("Generated storage name collides with archive")
        expected[backing] = dict(logical[source])
        # This private intermediate has no archived timestamp to reproduce.
        expected[intermediate] = {"type": "symlink", "mode": 0o777,
                                  "target": str(root / backing)}
        for name in [source, *aliases]:
            expected[name] = {"type": "symlink", "mode": 0o777,
                              "mtime": logical[name]["mtime"],
                              "target": str(root / intermediate)}
    return expected, groups


def compare_members(expected, observed):
    if set(expected) != set(observed):
        raise ValueError("Missing or additional physical path")
    for name, item in expected.items():
        actual = observed[name]
        for key in ("type", "mode", "target", "sha256", "size", "links"):
            if key in item and actual.get(key) != item[key]:
                raise ValueError(key + " mismatch: " + name)
        if "mtime" in item:
            actual_ns = int(actual["mtimeSeconds"]) * 1_000_000_000 + actual["mtimeNanoseconds"]
            if not 0 <= item["mtime"] - actual_ns < 1000:
                raise ValueError("mtime mismatch beyond microsecond precision: " + name)


def digest(stream):
    value = hashlib.sha256()
    while block := stream.read(1024 * 1024):
        value.update(block)
    return value.hexdigest()


def load_unique(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate JSON field: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def verify(archive, report_path, inventory_path):
    report_bytes = report_path.read_bytes()
    inventory_bytes = inventory_path.read_bytes()
    if len(report_bytes) > 65536 or len(inventory_bytes) > 16 * 1024 * 1024:
        raise ValueError("Diagnostic output exceeds expected bound")
    report = load_unique(report_bytes)
    document = load_unique(inventory_bytes)
    if (report.get("schema") != "foldgpt.rootfs-probe.v1"
            or report.get("status") != "PASS_PREPARED_INACTIVE"
            or report.get("archiveSha256") != SHA256
            or report.get("activationAttempted") is not False
            or report.get("guestExecuted") is not False
            or report.get("resumedWithoutDownload") is not True
            or report.get("existingRuntimeBefore") != report.get("existingRuntimeAfter")
            or report.get("inventorySha256") != hashlib.sha256(inventory_bytes).hexdigest()
            or document.get("schema") != "foldgpt.rootfs-inventory.v1"
            or document.get("archiveSha256") != SHA256
            or document.get("runId") != report.get("runId")):
        raise ValueError("Probe did not complete its required checks or output identity differs")
    members = document.get("members")
    backend = report.get("storageBackend")
    if backend not in ("native-posix-v1", PROOT_BACKEND) or report.get("logicalMembers") != MEMBERS:
        raise ValueError("Unknown storage backend or logical member count")
    root = PurePosixPath(report.get("rootAbsolute", ""))
    relative = report.get("root", "")
    if (str(root) != report.get("rootAbsolute")
            or not re.fullmatch(r"\.rootfs-(?:proot-)?install-probe/files/\.foldgpt-install/fresh/stages/rootfs-"
                                r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/root", relative)
            or root != PurePosixPath("/data/data/app.foldgpt/files") / relative):
        raise ValueError("Prepared root is outside its fixed private diagnostic stage")
    if not isinstance(members, list) or len(members) != report.get("members"):
        raise ValueError("Invalid member count")
    observed = {}
    for item in members:
        name = item["path"]
        if name in observed or canonical_member(name) != name:
            raise ValueError("Duplicate or ambiguous observed path")
        observed[name] = item
    logical = archive_members(archive)
    expected, groups = physical_members(logical, backend, root)
    compare_members(expected, observed)
    identities = {}
    for name, item in observed.items():
        if item["type"] != "regular":
            continue
        identity = (item["device"], item["inode"])
        logical_source = next((source for source, aliases in groups.items()
                               if name in [source, *aliases]), name) if backend == "native-posix-v1" else name
        if identity in identities and identities[identity] != logical_source:
            raise ValueError("Unexpected shared physical regular inode: " + name)
        identities[identity] = logical_source
    if backend == "native-posix-v1":
        for source, aliases in groups.items():
            for alias in aliases:
                if any(observed[source][key] != observed[alias][key] for key in ("device", "inode")):
                    raise ValueError("Hardlink inode mismatch: " + alias)
    regular_path_bytes = sum(item["size"] for item in expected.values() if item["type"] == "regular")
    if report.get("allRegularPathBytes") != regular_path_bytes:
        raise ValueError("Observed byte total differs")
    return {"runId": report["runId"], "verified_members": len(expected), "logical_members": len(logical),
            "storage_backend": backend,
            "all_regular_path_bytes": regular_path_bytes,
            "hardlink_groups": len(groups), "archive_sha256": SHA256,
            "result": "Android inventory matches every archived path, mode, file byte and link",
            "limit": "Inventory comparison; independent on-device observation remains required"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--inventory", required=True, type=Path)
    arguments = parser.parse_args()
    print(json.dumps(verify(arguments.archive, arguments.report, arguments.inventory), indent=2))
