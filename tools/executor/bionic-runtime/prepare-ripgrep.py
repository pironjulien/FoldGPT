"""Acquire hash-pinned ripgrep/PCRE2 sources and Cargo's locked source closure.

No Android commands or builds. All output, Cargo caches and temporary files
are confined to the selected project directory. --inputs reuses downloaded
source archives, while Cargo vendor still acquires any missing locked crates.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import tarfile
import tomllib

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def local(path):
    result = path.resolve()
    result.relative_to(ROOT)
    return result


def inventory(root):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Unexpected linked source: " + str(path))
        if path.is_file():
            rows.append({"path": path.relative_to(root).as_posix(),
                         "bytes": path.stat().st_size, "sha256": digest(path)})
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--inputs", type=Path)
    args = parser.parse_args()
    output = local(args.output)
    supplied = local(args.inputs) if args.inputs else None
    pins = json.loads((HERE / "ripgrep-inputs.json").read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=False)
    archives, sources, cargo_home = output / "archives", output / "sources", output / "cargo-home"
    for path in (archives, sources, cargo_home, output / "tmp"):
        path.mkdir()
    environment = os.environ.copy()
    environment.update(CARGO_HOME=str(cargo_home), CARGO_TARGET_DIR=str(output / "cargo-target"),
                       TMP=str(output / "tmp"), TEMP=str(output / "tmp"))
    downloads = [pins["ripgrep"], pins["pcre2"]]

    def acquire(row):
        destination = archives / row["archive"]
        if supplied:
            shutil.copyfile(supplied / row["archive"], destination)
        else:
            subprocess.run(["curl.exe" if os.name == "nt" else "curl", "--fail", "--location",
                            "--retry", "2", "--silent", "--show-error", row["url"],
                            "--output", str(destination)], check=True, timeout=180)
        if digest(destination) != row["sha256"]:
            raise ValueError("Pinned upstream archive differs: " + row["archive"])
        return row["archive"]

    with ThreadPoolExecutor(max_workers=len(downloads)) as pool:
        list(pool.map(acquire, downloads))
    epochs, source_aliases = [], []
    for row in downloads:
        with tarfile.open(archives / row["archive"]) as archive:
            members = archive.getmembers()
            for member in members:
                name = PurePosixPath(member.name)
                if (name.is_absolute() or ".." in name.parts or "\\" in member.name
                        or name.parts[0] != row["directory"]
                        or not (member.isfile() or member.isdir() or member.issym())):
                    raise ValueError("Unsupported upstream archive member: " + member.name)
                if member.issym():
                    # The pinned ripgrep source carries this upstream directory alias.
                    # Materialize it without Windows symlink privileges; reject all others.
                    if not (row["directory"] == "ripgrep-15.2.0"
                            and member.name == "ripgrep-15.2.0/HomebrewFormula"
                            and member.linkname == "pkg/brew"):
                        raise ValueError("Unexpected upstream source alias: " + member.name)
            archive.extractall(sources, members=[m for m in members if not m.issym()], filter="data")
            for member in members:
                if member.issym():
                    destination = sources / member.name
                    target = (destination.parent / member.linkname).resolve()
                    target.relative_to((sources / row["directory"]).resolve())
                    shutil.copytree(target, destination)
                    source_aliases.append({"path": member.name, "target": member.linkname,
                                           "materialization": "directory-copy"})
            epochs.append(int(max(m.mtime for m in members)))
    ripgrep = sources / pins["ripgrep"]["directory"]
    pcre2 = sources / pins["pcre2"]["directory"]
    lock = ripgrep / "Cargo.lock"
    before_lock = digest(lock)
    command = ["cargo", "+" + pins["rustToolchain"], "vendor", "--locked", "--versioned-dirs",
               str(output / "vendor")]
    result = subprocess.run(command, cwd=ripgrep, env=environment, capture_output=True, timeout=600)
    (output / "cargo-vendor.stdout").write_bytes(result.stdout)
    (output / "cargo-vendor.stderr").write_bytes(result.stderr)
    result.check_returncode()
    if digest(lock) != before_lock:
        raise ValueError("Cargo changed the upstream lockfile")
    crates = []
    for directory in sorted((output / "vendor").iterdir()):
        metadata = tomllib.loads((directory / "Cargo.toml").read_text(encoding="utf-8"))["package"]
        checksums = json.loads((directory / ".cargo-checksum.json").read_text(encoding="utf-8"))
        for name, expected in checksums["files"].items():
            if digest(directory / name) != expected:
                raise ValueError("Vendored crate file differs: " + directory.name + "/" + name)
        crates.append({"directory": directory.name, "name": metadata["name"],
                       "version": metadata["version"], "license": metadata.get("license"),
                       "licenseFile": metadata.get("license-file"),
                       "registryPackageSha256": checksums["package"]})
    lockdata = tomllib.loads(lock.read_text(encoding="utf-8"))
    expected_crates = {(p["name"], p["version"], p["checksum"])
                       for p in lockdata["package"] if p.get("source", "").startswith("registry+")}
    actual_crates = {(p["name"], p["version"], p["registryPackageSha256"]) for p in crates}
    if expected_crates != actual_crates:
        raise ValueError("Vendored dependencies differ from the upstream lockfile")
    upstream = {"ripgrep": inventory(ripgrep), "pcre2": inventory(pcre2)}
    manifest = {"schema": "foldgpt.bionic-ripgrep-prepared.v1", "pins": pins,
                "pinsSha256": digest(HERE / "ripgrep-inputs.json"),
                "preparerSha256": digest(Path(__file__)), "cargoLockSha256": before_lock,
                "sourceDateEpoch": max(epochs), "sourceAliases": source_aliases, "upstreamFiles": upstream,
                "vendoredCrates": crates, "vendorFiles": inventory(output / "vendor"),
                "cargoVersion": subprocess.check_output(["cargo", "+" + pins["rustToolchain"],
                    "--version"], env=environment).decode().strip(), "androidExecuted": False}
    (output / "source-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "cargoLockSha256": before_lock,
                      "crates": len(crates), "sourceManifestSha256": digest(output / "source-manifest.json"),
                      "androidExecuted": False}))


if __name__ == "__main__":
    main()
