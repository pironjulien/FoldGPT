"""Fetch pinned GNU Bash sources/official fixes and apply reviewed path patches."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--inputs', type=Path, help='Reuse local pinned GNU archives/patches, without downloading')
    args = parser.parse_args()
    prefix = PurePosixPath(args.prefix)
    if (not prefix.is_absolute() or prefix.as_posix() != args.prefix or args.prefix == '/'
            or '..' in prefix.parts or re.fullmatch(r'/[A-Za-z0-9/_.-]+', args.prefix) is None):
        parser.error('An absolute canonical Android runtime prefix is required')
    # patch runs from the source directory, so its -i paths must be absolute.
    args.output = args.output.resolve()
    if args.inputs is not None:
        args.inputs = args.inputs.resolve(strict=True)
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = json.loads((HERE / 'bash-inputs.json').read_text())
    source = inputs['source']
    sources = [('bash-5.3.tar.gz', source['url'], source['sha256'])]
    sources += [(f'bash53-{n}', f'https://mirrors.kernel.org/gnu/bash/bash-5.3-patches/bash53-{n}', sha)
                for n, sha in inputs['patches'].items()]
    def fetch(item):
        name, url, sha = item
        path = args.output / name
        if args.inputs is None:
            subprocess.run(['curl', '-fsSL', '--retry', '2', url, '-o', str(path)], check=True)
        else:
            original = args.inputs / name
            if original.is_symlink() or not original.is_file() or digest(original) != sha:
                raise ValueError(f'Pinned local source hash differs: {name}')
            shutil.copyfile(original, path)
        if digest(path) != sha:
            raise ValueError(f'Pinned source hash differs: {name}')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, sources))
    with tarfile.open(args.output / 'bash-5.3.tar.gz') as archive:
        members = archive.getmembers()
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe source archive path')
        archive.extractall(args.output, filter='data')
        source_epoch = max(member.mtime for member in members)
    root = args.output / 'bash-5.3'
    for n in inputs['patches']:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p0', '-i', (args.output / f'bash53-{n}').as_posix()], cwd=root, check=True)
    records = []
    for patch in sorted((HERE / 'termux-bash').glob('*.patch')):
        local = args.output / patch.name
        local.write_text(patch.read_text().replace('@TERMUX_PREFIX@', args.prefix), newline='\n')
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', local.as_posix()], cwd=root, check=True)
        records.append({'name': patch.name, 'originalSha256': digest(patch), 'configuredSha256': digest(local)})
    prepared = []
    for path in sorted(root.rglob('*')):
        if path.is_file():
            os.utime(path, (source_epoch, source_epoch))
            prepared.append({'path': path.relative_to(root).as_posix(), 'bytes': path.stat().st_size,
                             'sha256': digest(path)})
    (args.output / 'source-manifest.json').write_text(json.dumps({
        'upstream': inputs, 'androidPrefix': args.prefix, 'termuxPatches': records,
        'sourceDateEpoch': source_epoch, 'preparedFiles': prepared,
        'preparerSha256': digest(Path(__file__)),
        'scope': 'Source preparation only. No phone execution or sandbox assertion.'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
