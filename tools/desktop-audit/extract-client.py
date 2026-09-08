"""Read-only extraction of a pinned desktop package for interoperability review.

No package code or maintainer script is executed. Original inputs are retained.
Raw proprietary material belongs in the ignored work directory, not source Git.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import struct
import tarfile

ROOT = Path(__file__).resolve().parents[2]


def safe_path(name):
    name = name.removeprefix('./')
    path = PurePosixPath(name)
    if (not name or path.is_absolute() or '\\' in name or ':' in name
            or any(p in ('', '.', '..') for p in name.split('/'))):
        raise ValueError('Unsafe archive path: ' + repr(name))
    return path


def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package', type=Path, required=True)
    parser.add_argument('--descriptor', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.resolve().relative_to(ROOT / 'work')
    if os.name == 'nt':
        args.output = Path('\\\\?\\' + str(args.output.resolve()))
    args.output.mkdir(parents=True, exist_ok=False)
    expected = json.loads(args.descriptor.read_bytes())
    package = args.package.read_bytes()
    digest = hashlib.sha256(package).hexdigest()
    if digest != expected['sha256'] or len(package) != expected['bytes']:
        raise ValueError('Pinned package bytes differ')
    if package[:8] != b'!<arch>\n':
        raise ValueError('Not a Debian ar archive')
    offset = 8
    members = []
    while offset < len(package):
        header = package[offset:offset+60]
        if len(header) != 60 or header[58:] != b'`\n':
            raise ValueError('Malformed ar header')
        size = int(header[48:58])
        name = header[:16].decode('ascii').rstrip().removesuffix('/')
        start = offset + 60
        if size < 0 or start+size > len(package):
            raise ValueError('Invalid ar member size')
        members.append((name, start, size))
        offset = start+size+size%2
    payload, = [row for row in members if row[0] in ('data.tar.xz','data.tar.gz')]
    files = []
    asar = None
    with tarfile.open(fileobj=io.BytesIO(package[payload[1]:payload[1]+payload[2]]), mode='r|*') as archive:
        total = 0
        for entry in archive:
            if entry.name in ('.','./'):
                continue
            path = safe_path(entry.name)
            if len(files) >= expected['maxMembers']:
                raise ValueError('Too many entries')
            row = {'path':str(path),'bytes':entry.size,'mode':entry.mode,
                   'kind':'file' if entry.isfile() else 'directory' if entry.isdir() else 'link'}
            if entry.isfile():
                total += entry.size
                if total > expected['maxTarBytes']:
                    raise ValueError('Too much expanded data')
                data = archive.extractfile(entry).read()
                if len(data) != entry.size:
                    raise ValueError('Truncated entry')
                row['sha256'] = hashlib.sha256(data).hexdigest()
                row['elf'] = data.startswith(b'\x7fELF')
                # Extract all bundled executable scripts and binary modules for review.
                selected = (str(path) == 'usr/lib/chatgpt/resources/app.asar'
                            or path.suffix in ('.js','.cjs','.mjs','.json','.map','.node','.html','.css')
                            or row['elf'])
                if selected:
                    save(args.output/'package'/Path(str(path)), data)
                if str(path) == 'usr/lib/chatgpt/resources/app.asar':
                    asar = data
            elif entry.issym() or entry.islnk():
                row['target'] = entry.linkname  # Inventory only, never create links.
            files.append(row)
    if asar is None or len(asar)<16:
        raise ValueError('Missing desktop archive')
    size_size, header_size, payload_size, json_size = struct.unpack_from('<IIII',asar)
    if size_size != 4 or payload_size+4 != header_size or json_size > payload_size-4:
        raise ValueError('Unexpected Electron ASAR header')
    header = json.loads(asar[16:16+json_size])
    base = 8+header_size
    rows = []
    def visit(directory, prefix=''):
        for name, node in directory['files'].items():
            path = safe_path(prefix+name)
            if 'files' in node:
                visit(node, str(path)+'/')
                continue
            row={'path':str(path),'bytes':node.get('size'),'unpacked':node.get('unpacked',False)}
            if 'link' in node:
                row['link']=node['link']
            elif not row['unpacked']:
                start=base+int(node['offset']); end=start+int(node['size'])
                if start<base or end<start or end>len(asar):
                    raise ValueError('ASAR member outside payload')
                data=asar[start:end]
                row['sha256']=hashlib.sha256(data).hexdigest()
                integrity=node.get('integrity')
                if integrity and integrity.get('algorithm')=='SHA256' and integrity.get('hash')!=row['sha256']:
                    raise ValueError('ASAR integrity differs: '+str(path))
                if path.suffix in ('.js','.cjs','.mjs','.json','.map','.node','.html','.css'):
                    save(args.output/'asar'/Path(str(path)),data)
            rows.append(row)
    visit(header)
    save(args.output/'package-inventory.json',json.dumps(files,indent=2).encode())
    save(args.output/'asar-inventory.json',json.dumps(rows,indent=2).encode())
    report={'packageVersion':expected['version'],'packageSha256':digest,'packageEntries':len(files),
            'asarSha256':hashlib.sha256(asar).hexdigest(),'asarEntries':len(rows),
            'nativeElfCount':sum(r.get('elf',False) for r in files),
            'scope':'Static extraction and byte inventory; not complete decompilation or runtime coverage',
            'officialInputUnchanged':hashlib.sha256(args.package.read_bytes()).hexdigest()==digest}
    save(args.output/'report.json',json.dumps(report,indent=2).encode())
    print(json.dumps(report))


if __name__=='__main__':
    main()
