"""Recover the pinned upstream engine and the exact private integration patch."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    if args.destination.exists():
        raise RuntimeError("Destination already exists; no current engine work will be overwritten")
    records = Path(__file__).resolve().parents[2] / "recovery/engine"
    manifest = json.loads((records / "manifest.json").read_text(encoding="utf-8"))
    patch = records / manifest["patch"]
    if hashlib.sha256(patch.read_bytes()).hexdigest() != manifest["sha256"]:
        raise RuntimeError("Engine recovery patch checksum failed")
    subprocess.run(["git", "clone", "-c", "core.autocrlf=false", "--depth", "1", "--branch", manifest["tag"],
                    manifest["upstream"], str(args.destination)], check=True)
    git = ["git", "-C", str(args.destination)]
    actual = subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip()
    if actual != manifest["base"]:
        raise RuntimeError(f"Upstream tag moved: received {actual}")
    subprocess.run(git + ["switch", "-c", manifest["branch"]], check=True)
    subprocess.run(git + ["apply", "--index", "--check", str(patch)], check=True)
    # Track every restored source in the index, including newly added files.
    # Hydration must distinguish these sources from ignored archived assets.
    subprocess.run(git + ["apply", "--index", str(patch)], check=True)
    # The upstream remote is for fetching. Publish local changes through the
    # private FoldGPT workspace recovery export, never to the public upstream.
    subprocess.run(git + ["remote", "set-url", "--push", "origin", "DISABLED-PUBLIC-UPSTREAM"], check=True)
    print(f"Restored engine at {args.destination.resolve()} from {actual}")


if __name__ == "__main__":
    main()
