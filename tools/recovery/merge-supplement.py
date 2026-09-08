"""Add verified supplemental ignored files without replacing any existing data.

Run only after restore-archive.py authenticated and verified the source snapshot.
Git sources, submodules, existing bytes and literal link targets are preserved.
All collisions are checked before the first copy. No phone operation occurs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess

from recovery_paths import canonical_path, checked_tree, destination_boundary, linked, plain_path, snapshot_roots


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def merge(source, project):
    source, project = snapshot_roots(source, project)
    git = ['git', '-C', str(project)]
    root = subprocess.check_output(git + ['rev-parse', '--show-toplevel'], text=True).strip()
    if canonical_path(root, strict=True) != project:
        raise ValueError('Project must be the Git root')
    index = subprocess.check_output(git + ['ls-files', '--stage', '-z']).split(b'\0')
    tracked = set()
    for row in filter(None, index):
        _, raw = row.split(b'\t', 1)
        name = os.fsdecode(raw)
        tracked.add(name)
    candidates = []
    for base, directories, files in checked_tree(source):
        directories[:] = sorted(name for name in directories if name != '.git')
        paths = [Path(base) / name for name in sorted(files) if name != '.git']
        paths += [Path(base) / name for name in directories]
        for path in paths:
            relative = path.relative_to(source)
            name = relative.as_posix()
            if name in tracked or any(parent.as_posix() in tracked for parent in relative.parents):
                continue
            candidates.append((path, relative, name))
    classified = subprocess.run(git + ['check-ignore', '-z', '--stdin'],
        input=b''.join(os.fsencode(name + ('/' if path.is_dir() and not path.is_symlink() else '')) + b'\0'
                       for path, _, name in candidates), capture_output=True)
    if classified.returncode not in (0, 1):
        raise RuntimeError('Cannot classify supplemental files')
    ignored = {os.fsdecode(name).removesuffix('/') for name in classified.stdout.split(b'\0') if name}
    pending, missing_directories, identical = [], [], 0
    for path, relative, name in candidates:
        if name not in ignored:
            continue
        destination = project / relative
        mode = path.lstat().st_mode
        destination_boundary(destination, source, project, directory=stat.S_ISDIR(mode))
        if stat.S_ISLNK(mode):
            expected = ('link', os.readlink(path))
        elif stat.S_ISDIR(mode):
            if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
                raise FileExistsError('Existing directory differs; nothing replaced: ' + name)
            if not destination.exists():
                missing_directories.append((path, destination))
            continue
        elif stat.S_ISREG(mode):
            expected = ('file', digest(path))
        else:
            raise ValueError('Unsupported supplemental file type: ' + name)
        if destination.exists() or destination.is_symlink():
            same = (destination.is_symlink() and expected == ('link', os.readlink(destination)))
            if not destination.is_symlink() and destination.is_file() and expected[0] == 'file':
                same = digest(destination) == expected[1]
            if not same:
                raise FileExistsError('Existing data differ; nothing replaced: ' + name)
            identical += 1
        else:
            pending.append((path, destination, name, expected))
    for path, destination in sorted(missing_directories, key=lambda row: len(row[1].parts)):
        destination.mkdir(parents=True, exist_ok=True)
    for path, destination, name, expected in pending:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if expected[0] == 'link':
            os.symlink(expected[1], destination)
        else:
            with path.open('rb') as original, destination.open('xb') as output:
                shutil.copyfileobj(original, output)
            shutil.copystat(path, destination, follow_symlinks=False)
            if digest(destination) != expected[1]:
                raise RuntimeError('Supplement changed while copying: ' + name)
    for path, destination in sorted(missing_directories, key=lambda row: len(row[1].parts), reverse=True):
        shutil.copystat(path, destination, follow_symlinks=False)
    return {'sourceCommit': subprocess.check_output(git + ['rev-parse', 'HEAD'], text=True).strip(),
            'addedFilesAndLinks': len(pending), 'identicalExistingFilesAndLinks': identical,
            'addedDirectories': len(missing_directories),
            'sourceFilesOverwritten': False, 'existingDataReplaced': False,
            'addedPaths': [row[2] for row in pending]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--project', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    args = parser.parse_args()
    report_path = plain_path(args.report).absolute()
    if report_path.exists() or linked(report_path):
        raise FileExistsError('The recovery report must be a new file')
    if any(linked(parent) for parent in report_path.parents):
        raise ValueError('Recovery report parents must not be links or junctions')
    report_path = canonical_path(report_path)
    source, project = snapshot_roots(args.snapshot, args.project)
    if report_path.is_relative_to(source):
        raise ValueError('Recovery report must be outside the snapshot')
    if report_path.is_relative_to(project):
        relative = report_path.relative_to(project)
        ignored = subprocess.run(
            ['git', '-C', str(project), 'check-ignore', '--quiet', '--', relative.as_posix()]
        )
        if relative.parts[0] != 'work' or ignored.returncode != 0:
            raise ValueError('In-project reports must be ignored files under work/')
        snapshot_report = source / relative
        if snapshot_report.exists() or snapshot_report.is_symlink():
            raise ValueError('Recovery report conflicts with a supplemental path')
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the report before any merge and never overwrite a prior result.
    with report_path.open('x', encoding='utf-8') as output:
        report = merge(args.snapshot, args.project)
        output.write(json.dumps(report, indent=2) + '\n')
    print(json.dumps({key: value for key, value in report.items() if key != 'addedPaths'}))


if __name__ == '__main__':
    main()
