"""Authenticate downloaded recovery parts, verify every file, optionally restore."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from pathlib import PurePosixPath
import subprocess
import tarfile
import tempfile


def extract_verified_archive(plaintext, destination):
    """Write data first, then restore literal links without following them.

    Build outputs contain legitimate absolute links to the original workspace
    and to Linux system paths. Restoring them last preserves that evidence
    without allowing an archive link to redirect any extracted file write.
    """
    destination = destination.resolve()
    symlinks = []
    with tarfile.open(plaintext, "r:gz") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or "\\" in member.name:
                raise RuntimeError(f"Unsafe archive path: {member.name}")
            if member.issym():
                symlinks.append((member.name, member.linkname))
            else:
                archive.extract(member, destination, filter="data")
    for name, target in symlinks:
        path = destination.joinpath(*PurePosixPath(name).parts)
        if not path.parent.resolve().is_relative_to(destination):
            raise RuntimeError(f"Link parent escaped destination: {name}")
        path.parent.mkdir(parents=True, exist_ok=True)
        # No following data writes occur after this point. Absolute targets are
        # deliberately kept exact; build environments may regenerate such links.
        os.symlink(target, path)
    return len(symlinks)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--identity", type=Path, required=True)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    assets = args.assets.resolve(strict=True)
    manifest = json.loads((assets / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1:
        raise RuntimeError("Unsupported recovery format")
    if args.destination and args.destination.exists():
        raise RuntimeError("Destination must not exist; restore never overwrites a working project")
    with tempfile.TemporaryDirectory(prefix="foldgpt-recovery-") as temporary:
        combined = Path(temporary) / "workspace.age"
        digest = hashlib.sha256()
        with combined.open("xb") as destination:
            for part in manifest["parts"]:
                if Path(part["name"]).name != part["name"]:
                    raise RuntimeError("Invalid asset name")
                part_hash = hashlib.sha256()
                size = 0
                with (assets / part["name"]).open("rb") as source:
                    while block := source.read(8 * 1024 ** 2):
                        digest.update(block)
                        part_hash.update(block)
                        destination.write(block)
                        size += len(block)
                if size != part["bytes"] or part_hash.hexdigest() != part["sha256"]:
                    raise RuntimeError(f"Corrupt or incomplete part: {part['name']}")
        if digest.hexdigest() != manifest["encryptedSha256"]:
            raise RuntimeError("Combined encrypted checksum failed")
        plaintext = Path(temporary) / "workspace.tar.gz"
        # Authentication must finish successfully before any files are extracted.
        subprocess.run(["age", "-d", "-i", str(args.identity), "-o", str(plaintext), str(combined)], check=True)
        observed = {}
        expected = None
        with tarfile.open(plaintext, "r|gz") as archive:
            for member in archive:
                if member.name == "RECOVERY-INVENTORY.json":
                    if expected is not None:
                        raise RuntimeError("Duplicate inventory")
                    expected = json.load(archive.extractfile(member))
                    continue
                if member.name in observed:
                    raise RuntimeError(f"Duplicate archive path: {member.name}")
                row = {"path": member.name, "size": member.size, "mode": member.mode, "type": member.type.decode("ascii")}
                if member.isfile():
                    file_hash = hashlib.sha256()
                    source = archive.extractfile(member)
                    while block := source.read(8 * 1024 ** 2):
                        file_hash.update(block)
                    row["sha256"] = file_hash.hexdigest()
                elif member.issym() or member.islnk():
                    row["link"] = member.linkname
                observed[member.name] = row
        if expected is None or observed != {row["path"]: row for row in expected["files"]}:
            raise RuntimeError("Per-file inventory verification failed")
        if len(observed) != manifest["entries"]:
            raise RuntimeError("Entry count differs from release manifest")
        if args.destination:
            args.destination.mkdir(parents=True)
            symlinks = extract_verified_archive(plaintext, args.destination)
            restored_files = 0
            for row in observed.values():
                path = args.destination.joinpath(*PurePosixPath(row["path"]).parts)
                if "sha256" in row:
                    with path.open("rb") as source:
                        actual = hashlib.file_digest(source, "sha256").hexdigest()
                    if actual != row["sha256"] or path.stat().st_size != row["size"]:
                        raise RuntimeError(f"Restored file differs: {row['path']}")
                    restored_files += 1
                elif row["type"] == "2" and os.readlink(path) != row["link"]:
                    raise RuntimeError(f"Restored symbolic link differs: {row['path']}")
                elif row["type"] == "5" and not path.is_dir():
                    raise RuntimeError(f"Restored directory absent: {row['path']}")
        else:
            symlinks = sum("link" in row and row["type"] == "2" for row in observed.values())
            restored_files = None
        report = {"verified": True, "encryptedSha256": digest.hexdigest(), "entries": len(observed),
                  "files": sum("sha256" in row for row in observed.values()),
                  "fileBytes": sum(row["size"] for row in observed.values()),
                  "symlinks": symlinks,
                  "restoredFilesVerified": restored_files,
                  "restoredTo": str(args.destination.resolve()) if args.destination else None}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report))


if __name__ == "__main__":
    main()
