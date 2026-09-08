"""Publish an explicit private CI source snapshot without touching the work index."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
REPO = "pironjulien/FoldGPT-workspace"
URL = "https://github.com/" + REPO + ".git"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--python-only", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch(r"codex/native-[a-z0-9-]+", args.branch):
        raise ValueError("Explicit native CI branch required")
    metadata = json.loads(subprocess.check_output(["gh", "repo", "view", REPO, "--json", "isPrivate,url"], cwd=ROOT))
    if metadata != {"isPrivate": True, "url": "https://github.com/" + REPO}:
        raise ValueError("CI repository must remain the existing private workspace")
    def git(*argv, **kwargs):
        result = subprocess.run(["git", *argv], cwd=ROOT, capture_output=True, **kwargs)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace")[-2000:])
        return result.stdout.decode().strip()
    if git("ls-remote", URL, "refs/heads/" + args.branch):
        raise ValueError("An existing CI attempt must be retained")
    parent = git("rev-parse", "HEAD")
    paths = [".github/workflows/native-engine-validation.yml", "tools/ci", "tools/executor", "tools/policy", "recovery/engine"]
    temporary = ROOT / "work/ci-publication"
    temporary.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=temporary) as directory:
        environment = dict(os.environ, GIT_INDEX_FILE=str(Path(directory) / "index"))
        git("read-tree", parent, env=environment)
        git("add", "-A", "--", *paths, env=environment)
        tree = git("write-tree", env=environment)
        commit = git("commit-tree", tree, "-p", parent, input=("Qualify native production startup and official client routing\n").encode())
        git("push", URL, commit + ":refs/heads/" + args.branch)
    record = {"branch": args.branch, "commit": commit, "parent": parent, "paths": paths,
              "pythonOnly": args.python_only, "patch": json.loads((ROOT / "recovery/engine/manifest.json").read_text())["sha256"]}
    output = temporary / (commit + ".json")
    output.write_text(json.dumps(record, indent=2) + "\n")
    subprocess.run(["gh", "workflow", "run", "native-engine-validation.yml", "--repo", REPO,
                    "--ref", args.branch, "-f", "native_python_only=" + str(args.python_only).lower(),
                    "-f", "full_rust_checks=" + str(not args.python_only).lower()], cwd=ROOT, check=True)
    print(json.dumps(record))


if __name__ == "__main__":
    main()
