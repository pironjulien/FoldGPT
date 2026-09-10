"""Extract reviewable files from an exact ASAR copy without running client code."""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import struct

ROOT = Path(__file__).resolve().parents[2]
REVIEW_SUFFIXES = {'.js', '.cjs', '.mjs', '.json', '.map', '.node', '.wasm', '.html', '.css'}


def safe_path(name):
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '\\' in name or ':' in name
            or any(part in ('', '.', '..') for part in name.split('/'))):
        raise ValueError('Unsafe archive path: ' + repr(name))
    return path


def save(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asar', type=Path, required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.asar.resolve(strict=True).relative_to(ROOT)
    output = args.output.resolve()
    output.relative_to(ROOT / 'work')
    if output == ROOT / 'work':
        raise ValueError('Choose a dedicated output directory')
    source = args.asar.read_bytes()
    digest = hashlib.sha256(source).hexdigest()
    if digest != args.sha256:
        raise ValueError('Archive differs from its observed SHA-256')
    size_size, header_size, payload_size, json_size = struct.unpack_from('<IIII', source)
    if size_size != 4 or payload_size + 4 != header_size or json_size > payload_size - 4:
        raise ValueError('Unexpected ASAR header')
    base = 8 + header_size
    if base > len(source) or 16 + json_size > base:
        raise ValueError('ASAR header outside file')
    header = json.loads(source[16:16+json_size])
    if os.name == 'nt':
        output = Path('\\\\?\\' + str(output))
    output.mkdir(parents=True, exist_ok=False)
    rows = []

    def visit(directory, prefix=''):
        for name, node in directory['files'].items():
            path = safe_path(prefix + name)
            if 'files' in node:
                visit(node, str(path) + '/')
                continue
            row = {'path': str(path), 'bytes': node.get('size'), 'unpacked': node.get('unpacked', False)}
            if 'link' in node:
                row['link'] = node['link']
                row['extracted'] = False
            elif row['unpacked']:
                row['extracted'] = False
                row['reason'] = 'Bytes are outside the ASAR; separate installed-file collection required'
            else:
                start = base + int(node['offset'])
                end = start + int(node['size'])
                if start < base or end < start or end > len(source):
                    raise ValueError('Member outside ASAR: ' + str(path))
                data = source[start:end]
                row['sha256'] = hashlib.sha256(data).hexdigest()
                integrity = node.get('integrity')
                if integrity:
                    if integrity.get('algorithm') != 'SHA256':
                        raise ValueError('Unsupported member integrity: ' + str(path))
                    if integrity.get('hash') != row['sha256']:
                        raise ValueError('Member integrity mismatch: ' + str(path))
                    row['integrityVerified'] = True
                row['extracted'] = path.suffix in REVIEW_SUFFIXES
                if row['extracted']:
                    save(output / 'asar' / Path(str(path)), data)
            rows.append(row)

    visit(header)
    unchanged = hashlib.sha256(args.asar.read_bytes()).hexdigest() == digest
    if not unchanged:
        raise ValueError('Input archive changed during extraction')
    save(output / 'asar-inventory.json', json.dumps(rows, indent=2).encode())
    report = {'asarSha256': digest, 'asarBytes': len(source), 'asarEntries': len(rows),
              'extractedEntries': sum(row.get('extracted', False) for row in rows),
              'unpackedEntriesNotCollected': sum(row['unpacked'] for row in rows),
              'inputUnchanged': unchanged, 'clientCodeExecuted': False,
              'scope': 'Static byte extraction of packed scripts and reviewable assets; not native decompilation or runtime validation'}
    save(output / 'report.json', json.dumps(report, indent=2).encode())
    print(json.dumps(report))


if __name__ == '__main__':
    main()
