"""Admit and verify the exact Rust/NDK runtime notices accompanying native rg.

This packaging attestation is separate from the frozen compiler recipe; adding
documentation never requires changing or recompiling an admitted executable.
"""
import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[3]
PINS = Path(__file__).with_name("ripgrep-toolchain-notices.json")
PREFIX = "notices/ripgrep-toolchain/"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(value):
    if (type(value) is not str or not value or PurePosixPath(value).is_absolute()
            or PurePosixPath(value).as_posix() != value or ".." in PurePosixPath(value).parts
            or "\\" in value or ":" in value):
        raise ValueError("Invalid toolchain notice path")
    return value


def contained(root, value):
    path = root
    for part in PurePosixPath(relative(value)).parts:
        path /= part
        if path.is_symlink() or path.is_junction():
            raise ValueError("Linked toolchain notice evidence")
    path.resolve(strict=True).relative_to(root.resolve(strict=True))
    if not path.is_file():
        raise ValueError("Toolchain notice evidence is not a regular file")
    return path


def specification():
    data = PINS.read_bytes()
    pins = json.loads(data)
    if (pins["schema"] != "foldgpt.ripgrep-toolchain-notices.v1"
            or pins["rustToolchain"] != "1.97.0" or pins["ndkRevision"] != "29.0.14206865"
            or not pins["files"] or len({r["path"] for r in pins["files"]}) != len(pins["files"])):
        raise ValueError("Toolchain notice pins differ from the reviewed build")
    for row in pins["files"]:
        relative(row["path"])
    manifest = {"schema": "foldgpt.ripgrep-toolchain-notices.assets.v1",
                "sourceManifestSha256": pins["captureManifestSha256"],
                "rustToolchain": pins["rustToolchain"], "ndkRevision": pins["ndkRevision"],
                "files": pins["files"]}
    manifest_data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
    return pins, data, manifest_data


def provenance(path):
    pins, pin_data, manifest = specification()
    return {"path": relative(path), "sourceManifestSha256": pins["captureManifestSha256"],
            "pinsSha256": digest(pin_data), "assetManifestSha256": digest(manifest),
            "fileCount": len(pins["files"]), "bytes": sum(row["bytes"] for row in pins["files"]),
            "rustToolchain": pins["rustToolchain"], "ndkRevision": pins["ndkRevision"]}


def production_toolchain_notices(source):
    source = Path(source).absolute()
    # Authenticate every unresolved path component before following the path.
    relative_source = source.relative_to(ROOT).as_posix()
    contained(ROOT, relative_source + "/manifest.json")
    source = source.resolve(strict=True)
    pins, _, manifest_data = specification()
    captured_bytes = contained(source, "manifest.json").read_bytes()
    if digest(captured_bytes) != pins["captureManifestSha256"]:
        raise ValueError("Captured toolchain notice manifest differs")
    captured = json.loads(captured_bytes)
    if (captured["rustToolchain"] != pins["rustToolchain"] or captured["ndkRevision"] != pins["ndkRevision"]
            or [{k: v for k, v in row.items() if k != "source"} for row in captured["files"]] != pins["files"]):
        raise ValueError("Captured toolchain notice inventory differs")
    actual = set()
    for path in source.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Linked toolchain notice file or directory")
        if path.is_file(): actual.add(path.relative_to(source).as_posix())
    if actual != {"manifest.json", *(row["path"] for row in pins["files"])}:
        raise ValueError("Toolchain notice source closure differs")
    assets = {PREFIX + "manifest.json": manifest_data}
    for row in pins["files"]:
        data = contained(source, row["path"]).read_bytes()
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError("Toolchain notice bytes differ: " + row["path"])
        assets[PREFIX + row["path"]] = data
    return assets, provenance(relative_source)


def verify_assets(qualification, read_asset, asset_names):
    """Verify actual package assets against canonical pins, not self-declared hashes."""
    actual = {name for name in asset_names if name.startswith(PREFIX)}
    provided = qualification.get("ripgrepToolchainNotices")
    if "ripgrepBuild" not in qualification:
        if provided is not None or actual:
            raise ValueError("Toolchain notices present without native ripgrep")
        return 0
    if type(provided) is not dict or type(provided.get("path")) is not str:
        raise ValueError("Native ripgrep requires its toolchain notice attestation")
    expected = provenance(provided["path"])
    if provided != expected:
        raise ValueError("Toolchain notice provenance differs from canonical pins")
    pins, _, manifest = specification()
    expected_names = {PREFIX + "manifest.json", *(PREFIX + row["path"] for row in pins["files"])}
    if actual != expected_names:
        raise ValueError("Packaged toolchain notice closure differs")
    if read_asset(PREFIX + "manifest.json") != manifest:
        raise ValueError("Packaged toolchain notice manifest differs")
    for row in pins["files"]:
        data = read_asset(PREFIX + row["path"])
        if len(data) != row["bytes"] or digest(data) != row["sha256"]:
            raise ValueError("Packaged toolchain notice bytes differ: " + row["path"])
    return len(pins["files"])
