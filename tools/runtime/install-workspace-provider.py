"""Apply one fingerprint-gated dependency-provider hook to a known client ASAR.

The original archive is preserved. Only the reviewed module receives an added
FoldGPT adapter; every existing byte in every other member is retained. This is
a FoldGPT client integration, never represented as an unchanged official ASAR.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

KNOWN = {
    '1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d': {
        'module': '.vite/build/src-VqXTPopo.js',
        'sha256': '8d056524ea3f5714e5e0a254afd88f018d58465bc6ea026adee3c80ff7799e29',
        'names': ['xB', 'PB', 'QB', 'hB', 'fB'],
    },
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def adapt(source):
    descriptor = KNOWN.get(digest(source))
    if descriptor is None:
        raise ValueError('Client revision not reviewed for the FoldGPT workspace provider')
    _, header_size, payload_size, json_size = struct.unpack_from('<IIII', source)
    if payload_size + 4 != header_size or json_size > payload_size - 4:
        raise ValueError('Unexpected ASAR header')
    base = 8 + header_size
    header = json.loads(source[16:16 + json_size])
    blocks = []
    offset = 0
    changed = []

    def visit(directory, prefix=''):
        nonlocal offset
        for name, member in directory['files'].items():
            location = prefix + name
            if 'files' in member:
                visit(member, location + '/')
            elif 'offset' in member:
                start = base + int(member['offset'])
                data = source[start:start + member['size']]
                if location == descriptor['module']:
                    if digest(data) != descriptor['sha256']:
                        raise ValueError('The dependency module differs from the reviewed bytes')
                    names = descriptor['names']
                    properties = ['resolveManifest', 'downloadFile', 'validatePaths', 'diagnose', 'instructions']
                    entries = ','.join(key + ':' + value for key, value in zip(properties, names))
                    hook = ("\n;/* FoldGPT workspace provider v1 */\n"
                            f"({{{entries}}}=require('/usr/local/lib/foldgpt/foldgpt-workspace-provider.cjs').integrate({{{entries}}}));\n")
                    data += hook.encode()
                    changed.append(location)
                    if 'integrity' in member:
                        size = member['integrity']['blockSize']
                        member['integrity'].update(hash=digest(data),
                            blocks=[digest(data[i:i + size]) for i in range(0, len(data), size)])
                member['offset'] = str(offset)
                member['size'] = len(data)
                blocks.append(data)
                offset += len(data)
    visit(header)
    if changed != [descriptor['module']]:
        raise ValueError('Expected exactly one adapted module')
    raw = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode()
    padded = raw + b'\0' * (-len(raw) % 4)
    header_bytes = struct.pack('<II', len(padded) + 4, len(raw)) + padded
    return struct.pack('<II', 4, len(header_bytes)) + header_bytes + b''.join(blocks), descriptor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asar', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    args = parser.parse_args()
    if args.asar.is_symlink() or not args.asar.is_file():
        raise ValueError('Expected a regular installed ASAR')
    args.state.mkdir(parents=True, exist_ok=True)
    record_path = args.state / 'client-adapter.json'
    current = args.asar.read_bytes()
    before = digest(current)
    if record_path.exists():
        record = json.loads(record_path.read_text())
        if before == record['adaptedSha256']:
            print(json.dumps({'status': 'current', **record}))
            return
    adapted, descriptor = adapt(current)
    backup = args.state / (before + '.official.asar')
    if backup.exists() and digest(backup.read_bytes()) != before:
        raise ValueError('The preserved official ASAR backup differs')
    if not backup.exists():
        with backup.open('xb') as stream:
            stream.write(current)
    # Atomic activation keeps the previous app available if writing fails.
    fd, temporary = tempfile.mkstemp(prefix='.foldgpt-asar-', dir=args.asar.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(adapted)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, args.asar.stat().st_mode & 0o777)
        os.replace(temporary, args.asar)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    record = {'provider': 'FoldGPT', 'officialSha256': before, 'adaptedSha256': digest(adapted),
              'modifiedModule': descriptor['module'], 'backup': str(backup)}
    record_path.write_text(json.dumps(record, indent=2), encoding='utf-8')
    print(json.dumps({'status': 'adapted', **record}))


if __name__ == '__main__':
    main()
