"""Fetch pinned GNU Bash sources/official fixes and apply reviewed path patches."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent


def digest(path):
    return hashlib.file_digest(path.open('rb'), 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    parser.add_argument('--prefix', required=True)
    args = parser.parse_args()
    if not args.prefix.startswith('/') or any(c in args.prefix for c in '\n\r\"'):
        parser.error('An absolute, single-line Android runtime prefix is required')
    args.output.mkdir(parents=True, exist_ok=False)
    inputs = json.loads((HERE / 'bash-inputs.json').read_text())
    source = inputs['source']
    sources = [('bash-5.3.tar.gz', source['url'], source['sha256'])]
    sources += [(f'bash53-{n}', f'https://mirrors.kernel.org/gnu/bash/bash-5.3-patches/bash53-{n}', sha)
                for n, sha in inputs['patches'].items()]
    def fetch(item):
        name, url, sha = item
        path = args.output / name
        subprocess.run(['curl', '-fsSL', '--retry', '2', url, '-o', str(path)], check=True)
        if digest(path) != sha:
            raise ValueError(f'Pinned source hash differs: {name}')
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(fetch, sources))
    with tarfile.open(args.output / 'bash-5.3.tar.gz') as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe source archive path')
        archive.extractall(args.output, filter='data')
    root = args.output / 'bash-5.3'
    for n in inputs['patches']:
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p0', '-i', str(args.output / f'bash53-{n}')], cwd=root, check=True)
    records = []
    for patch in sorted((HERE / 'termux-bash').glob('*.patch')):
        local = args.output / patch.name
        local.write_text(patch.read_text().replace('@TERMUX_PREFIX@', args.prefix))
        subprocess.run(['patch', '--batch', '--fuzz=0', '-p1', '-i', str(local)], cwd=root, check=True)
        records.append({'name': patch.name, 'originalSha256': digest(patch), 'configuredSha256': digest(local)})
    (args.output / 'source-manifest.json').write_text(json.dumps({
        'upstream': inputs, 'androidPrefix': args.prefix, 'termuxPatches': records,
        'scope': 'Source preparation only. No phone execution or sandbox assertion.'}, indent=2) + '\n')


if __name__ == '__main__':
    main()
