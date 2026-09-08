"""Restore ignored assets alongside a fresh Git clone without replacing sources."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from recovery_paths import canonical_path, checked_tree, destination_boundary, linked, plain_path, snapshot_roots


def hydrate(source, project):
    source, project = snapshot_roots(source, project)
    git = ["git", "-C", str(project)]
    if canonical_path(subprocess.check_output(git + ["rev-parse", "--show-toplevel"], text=True).strip(), strict=True) != project:
        raise RuntimeError("Project must be the root of a Git clone")
    entries = subprocess.check_output(git + ["ls-files", "--stage", "-z"]).split(b"\0")
    tracked = {os.fsdecode(entry.split(b"\t", 1)[1]) for entry in entries if entry}
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
            if path.is_junction():
                raise ValueError('Junction in recovery snapshot')
            if path.name == ".git" or relative in tracked or any(parent.as_posix() in tracked for parent in Path(relative).parents):
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
                destination_boundary(destination, source, project, directory=directory_entry)
                # The snapshot/report live inside work on the new PC. Descend
                # through their existing ancestors without copying those roots.
                recovery = project / 'work/FoldGPT-recovery'
                if directory_entry and destination.is_dir() and not linked(destination) and (
                    source.is_relative_to(destination) or recovery.is_relative_to(destination)
                ):
                    pending.append(path)
                    continue
                if destination.exists() or destination.is_symlink():
                    raise RuntimeError(f"Existing asset preserved; hydrate only a fresh clone: {relative}")
                if directory_entry:
                    # copytree preserves symlinks but may follow junctions on
                    # Windows, so reject them throughout each selected subtree.
                    for _ in checked_tree(path):
                        pass
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
    return {"sourceCommit": subprocess.check_output(git + ["rev-parse", "HEAD"], text=True).strip(),
            "restoredIgnoredRoots": restored, "sourceFilesOverwritten": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--project", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    source, project = snapshot_roots(args.snapshot, args.project)
    report = plain_path(args.report).absolute()
    if report.exists() or any(linked(parent) for parent in (report, *report.parents)):
        raise ValueError('Recovery report must be fresh and must not traverse links')
    report = canonical_path(report)
    if report.is_relative_to(source):
        raise ValueError('Recovery report must be outside the snapshot')
    if report.is_relative_to(project):
        relative = report.relative_to(project)
        ignored = subprocess.run(['git', '-C', str(project), 'check-ignore', '--quiet', '--', relative.as_posix()])
        if relative.parts[0] != 'work' or ignored.returncode != 0:
            raise ValueError('In-project reports must be ignored files under work/')
        if (source / relative).exists() or linked(source / relative):
            raise ValueError('Recovery report conflicts with a snapshot path')
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open('x', encoding='utf-8') as output:
        result = hydrate(source, project)
        output.write(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == "__main__":
    main()
