"""Restore the source checkpoint's exact vendor modifications after cloning."""
import hashlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    records = root / "recovery/submodules"
    subprocess.run(["git", "-C", str(root), "submodule", "update", "--init", "--recursive"], check=True)
    for relative, item in json.loads((records / "submodules.json").read_text(encoding="utf-8")).items():
        command = ["git", "-C", str(root / relative)]
        actual = subprocess.check_output(command + ["rev-parse", "HEAD"], text=True).strip()
        if actual != item["base"]:
            raise RuntimeError(f"Unexpected submodule base for {relative}: {actual}")
        if "patch" not in item:
            continue
        patch = records / item["patch"]
        if hashlib.sha256(patch.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"Patch checksum failed for {relative}")
        if subprocess.run(command + ["apply", "--reverse", "--check", str(patch)], capture_output=True).returncode == 0:
            print(f"Already restored: {relative}")
            continue
        subprocess.run(command + ["apply", "--check", str(patch)], check=True)
        subprocess.run(command + ["apply", str(patch)], check=True)
        print(f"Restored: {relative}")


if __name__ == "__main__":
    main()
