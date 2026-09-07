"""Restore ignored assets alongside a fresh Git clone without replacing sources."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    source = args.snapshot.resolve(strict=True)
    project = args.project.resolve(strict=True)
    if source == project or source.is_relative_to(project) or project.is_relative_to(source):
        raise RuntimeError("Snapshot and fresh clone must be separate directories")
    git = ["git", "-C", str(project)]
    if Path(subprocess.check_output(git + ["rev-parse", "--show-toplevel"], text=True).strip()).resolve() != project:
        raise RuntimeError("Project must be the root of a Git clone")
    entries = subprocess.check_output(git + ["ls-files", "--stage", "-z"]).split(b"\0")
    submodules = {entry.split(b"\t", 1)[1].decode() for entry in entries if entry.startswith(b"160000 ")}
    tracked_boundaries = set()
    for entry in entries:
        if not entry:
            continue
        relative = Path(entry.split(b"\t", 1)[1].decode())
        tracked_boundaries.add(relative.as_posix())
        tracked_boundaries.update(parent.as_posix() for parent in relative.parents)
    pending = [source]
    selections = []
    while pending:
        paths = [path for directory in pending for path in sorted(directory.iterdir())]
        pending = []
        candidates = []
        for path in paths:
            relative = path.relative_to(source).as_posix()
            if path.name == ".git" or relative in submodules:
                continue
            directory_entry = path.is_dir() and not path.is_symlink()
            probe = relative + "/" if directory_entry else relative
            candidates.append((path, relative, directory_entry, probe))
        if not candidates:
            continue
        # One binary-safe Git request per directory depth avoids thousands of
        # Windows-mounted process launches while preserving Git's own rules.
        probes = b"".join(os.fsencode(row[3]) + b"\0" for row in candidates)
        classified = subprocess.run(git + ["check-ignore", "-z", "--stdin"],
                                    input=probes, capture_output=True)
        if classified.returncode not in (0, 1):
            raise RuntimeError("Cannot classify archive entries: " + os.fsdecode(classified.stderr))
        ignored = {os.fsdecode(value) for value in classified.stdout.split(b"\0") if value}
        for path, relative, directory_entry, probe in candidates:
            if probe in ignored and relative not in tracked_boundaries:
                destination = project / relative
                if destination.exists() or destination.is_symlink():
                    raise RuntimeError(f"Existing asset preserved; hydrate only a fresh clone: {relative}")
                selections.append((path, destination, relative))
            elif directory_entry:
                pending.append(path)
    # Validate all conflicts before any copies. Git-tracked files are never selected.
    restored = []
    for path, destination, relative in selections:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if path.is_symlink():
            os.symlink(os.readlink(path), destination)
        elif path.is_dir():
            shutil.copytree(path, destination, symlinks=True)
        else:
            shutil.copy2(path, destination, follow_symlinks=False)
        restored.append(relative)
    report = {"sourceCommit": subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip(),
              "restoredIgnoredRoots": restored, "sourceFilesOverwritten": False}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
