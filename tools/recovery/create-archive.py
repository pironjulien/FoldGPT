"""Stream a complete workspace snapshot into age, with per-file evidence."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile

EXCLUDED_DIRECTORIES = {".git", ".gradle", ".cxx", "__pycache__", "target"}
CHUNK_SIZE = 1024 ** 3  # GitHub release assets must remain below 2 GiB.


class HashingReader:
    def __init__(self, source):
        self.source = source
        self.digest = hashlib.sha256()

    def read(self, count=-1):
        data = self.source.read(count)
        self.digest.update(data)
        return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", action="append", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--recipient", required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise RuntimeError("Use a fresh output directory; existing recovery artifacts are preserved")
    roots = [root.resolve(strict=True) for root in args.root]
    if len({root.name for root in roots}) != len(roots):
        raise RuntimeError("Archive root names must be distinct")
    if any(output.is_relative_to(root) for root in roots):
        raise RuntimeError("Recovery output must be outside the archived workspaces")
    output.mkdir(parents=True)
    encrypted = output / "workspace.tar.gz.age"
    inventory = []
    started = datetime.now(timezone.utc).isoformat()
    process = subprocess.Popen(["age", "-r", args.recipient, "-o", str(encrypted)], stdin=subprocess.PIPE)
    try:
        with gzip.GzipFile(fileobj=process.stdin, mode="wb", compresslevel=3, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w|") as archive:
                for root in roots:
                    for base, directories, filenames in os.walk(root, followlinks=False):
                        directories[:] = sorted(d for d in directories if d not in EXCLUDED_DIRECTORIES)
                        paths = [Path(base)] + [Path(base) / f for f in sorted(filenames) if f != ".git"]
                        # os.walk does not descend into directory symlinks: preserve the link itself.
                        paths += [Path(base) / d for d in directories if (Path(base) / d).is_symlink()]
                        for path in paths:
                            name = root.name + ("/" + path.relative_to(root).as_posix() if path != root else "")
                            info = archive.gettarinfo(str(path), arcname=name)
                            # Tar stores permissions separately from the file-type field.
                            info.mode &= 0o7777
                            row = {"path": name, "size": info.size, "mode": info.mode, "type": info.type.decode("ascii")}
                            if info.isfile():
                                with path.open("rb") as source:
                                    before = os.fstat(source.fileno())
                                    if before.st_size != info.size:
                                        raise RuntimeError(f"File changed before snapshot: {name}")
                                    reader = HashingReader(source)
                                    archive.addfile(info, reader)
                                    after = os.fstat(source.fileno())
                                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                                        raise RuntimeError(f"File changed during snapshot: {name}")
                                row["sha256"] = reader.digest.hexdigest()
                            else:
                                archive.addfile(info)
                                if info.issym() or info.islnk():
                                    row["link"] = info.linkname
                            inventory.append(row)
                            if len(inventory) % 10000 == 0:
                                print(json.dumps({"entriesArchived": len(inventory), "root": root.name}), flush=True)
                manifest = {"format": 1, "startedUtc": started, "completedUtc": datetime.now(timezone.utc).isoformat(),
                            "sourceRoots": {str(root): root.name for root in roots},
                            "excludedDirectoryNames": sorted(EXCLUDED_DIRECTORIES), "files": inventory}
                payload = (json.dumps(manifest, ensure_ascii=True, indent=2) + "\n").encode()
                info = tarfile.TarInfo("RECOVERY-INVENTORY.json")
                info.size = len(payload)
                info.mode = 0o600
                archive.addfile(info, io.BytesIO(payload))
        process.stdin.close()
        if process.wait() != 0:
            raise RuntimeError("age encryption failed")
    except BaseException:
        process.stdin.close()
        process.wait()
        raise
    parts = []
    total_hash = hashlib.sha256()
    with encrypted.open("rb") as source:
        number = 1
        while True:
            block = source.read(min(CHUNK_SIZE, 8 * 1024 ** 2))
            if not block:
                break
            name = f"workspace.tar.gz.age.part{number:03d}"
            digest = hashlib.sha256()
            size = 0
            with (output / name).open("xb") as destination:
                while block:
                    destination.write(block)
                    digest.update(block)
                    total_hash.update(block)
                    size += len(block)
                    if size == CHUNK_SIZE:
                        break
                    block = source.read(min(CHUNK_SIZE - size, 8 * 1024 ** 2))
            parts.append({"name": name, "bytes": size, "sha256": digest.hexdigest()})
            number += 1
    public = {"format": 1, "startedUtc": started, "completedUtc": datetime.now(timezone.utc).isoformat(),
              "roots": [root.name for root in roots], "entries": len(inventory),
              "uncompressedFileBytes": sum(row["size"] for row in inventory),
              "excludedDirectoryNames": sorted(EXCLUDED_DIRECTORIES),
              "encryptedSha256": total_hash.hexdigest(), "parts": parts}
    (output / "manifest.json").write_text(json.dumps(public, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(public), flush=True)


if __name__ == "__main__":
    main()
