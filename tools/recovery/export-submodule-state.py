"""Preserve submodule working changes without touching its real Git index."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


def export(project: Path, destination: Path) -> None:
    submodule = project / "vendor/termux-x11"
    destination.mkdir(parents=True, exist_ok=True)
    base = subprocess.check_output(["git", "-C", str(submodule), "rev-parse", "HEAD"], text=True).strip()
    temporary_root = project / "work" / "recovery-tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="foldgpt-index-", dir=temporary_root) as directory:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        command = ["git", "-C", str(submodule)]
        subprocess.run(command + ["read-tree", "HEAD"], env=environment, check=True)
        subprocess.run(command + ["add", "-A"], env=environment, check=True)
        patch = subprocess.check_output(command + ["diff", "--cached", "--binary", "--full-index", "HEAD"], env=environment)
    (destination / "termux-x11.patch").write_bytes(patch)
    (destination / "submodules.json").write_text(json.dumps({
        "vendor/termux-x11": {"base": base, "patch": "termux-x11.patch", "sha256": hashlib.sha256(patch).hexdigest()},
        "vendor/proot": {"base": subprocess.check_output(["git", "-C", str(project / "vendor/proot"), "rev-parse", "HEAD"], text=True).strip()},
    }, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[2]
    export(root, root / "recovery/submodules")
