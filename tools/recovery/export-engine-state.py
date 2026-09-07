"""Export the separate engine's full source changes against its exact release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

BASE = "3d2ee51ca2d5db578f328aa75e20aa22c0197c9a"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--engine", type=Path, required=True)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    output = project / "recovery/engine"
    output.mkdir(parents=True, exist_ok=True)
    git = ["git", "-C", str(args.engine.resolve(strict=True))]
    if subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip() != BASE:
        raise RuntimeError("Engine base differs; update the reviewed recovery contract first")
    temporary_root = project / "work" / "recovery-tmp"
    temporary_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="foldgpt-engine-index-", dir=temporary_root) as directory:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        subprocess.run(git + ["read-tree", BASE], env=environment, check=True)
        subprocess.run(git + ["add", "-A"], env=environment, check=True, capture_output=True)
        patch = subprocess.check_output(git + ["diff", "--cached", "--binary", "--full-index", BASE], env=environment)
        subprocess.run(git + ["read-tree", BASE], env=environment, check=True)
        subprocess.run(git + ["apply", "--cached", "--check", "-"], env=environment, input=patch, check=True)
    (output / "engine.patch").write_bytes(patch)
    manifest = {"upstream": "https://github.com/openai/codex.git", "tag": "rust-v0.153.4", "base": BASE,
                "branch": "codex/android-native-engine", "patch": "engine.patch",
                "sha256": hashlib.sha256(patch).hexdigest(), "appliesToCleanBase": True}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest))


if __name__ == "__main__":
    main()
