"""Build a verified tar payload for the shell-owned, fixed Shizuku experiment.

No ADB command, extraction or phone execution occurs here. The original complete
Python distribution and ELF aliases are preserved. Deployment must use a fresh
shell-owned directory, never overwrite an existing workspace.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import posixpath
import tarfile


def safe_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or str(path) != value:
        raise ValueError('Unsafe manifest path: ' + value)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    source = json.loads((args.stage / 'manifest.json').read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    records, names = [], set()
    with tarfile.open(args.output / 'runtime.tar.gz', 'w:gz') as archive:
        def add(name, data=None, target=None, mode=0o400):
            safe_path(name)
            if name in names:
                raise ValueError('Duplicate archive path: ' + name)
            names.add(name)
            info = tarfile.TarInfo(name)
            info.uid = info.gid = 2000
            info.uname = info.gname = 'shell'
            info.mode = mode
            if target is not None:
                resolved = posixpath.normpath(posixpath.join(posixpath.dirname(name), target))
                if not resolved.startswith('native/'):
                    raise ValueError('Alias leaves native runtime')
                info.type = tarfile.SYMTYPE
                info.linkname = target
                archive.addfile(info)
                records.append({'path': name, 'type': 'symlink', 'target': target})
            else:
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
                records.append({'path': name, 'type': 'file', 'mode': oct(mode),
                                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})

        for item in source['nativeFiles']:
            safe_path(item['name'])
            data = (args.stage / 'jniLibs/arm64-v8a' / item['name']).read_bytes()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Native file differs from source manifest')
            add('native/' + item['name'], data=data, mode=0o500)
        for item in source['dataFiles']:
            safe_path(item['path'])
            data = (args.stage / 'assets/bionic-python' / item['path']).read_bytes()
            if hashlib.sha256(data).hexdigest() != item['sha256']:
                raise ValueError('Python data differs from source manifest')
            add('python/' + item['path'], data=data)
        for item in source['runtimeAliases']:
            path = 'python/' + str(safe_path(item['path']))
            target = 'native/' + str(safe_path(item['nativeLibrary']))
            native = next(x for x in records if x['path'] == target)
            if native['sha256'] != item['sha256']:
                raise ValueError('Alias target content differs')
            add(path, target=posixpath.relpath(target, posixpath.dirname(path)))
    manifest = {'schema': 'foldgpt.shizuku.runtime-payload.v1',
                'sourceManifestSha256': hashlib.sha256((args.stage / 'manifest.json').read_bytes()).hexdigest(),
                'payloadSha256': hashlib.sha256((args.output / 'runtime.tar.gz').read_bytes()).hexdigest(),
                'records': records, 'scope': 'Staging only; no execution or policy validation'}
    (args.output / 'payload-manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'entries': len(records), 'payloadSha256': manifest['payloadSha256'],
                      'output': str(args.output)}))


if __name__ == '__main__':
    main()
