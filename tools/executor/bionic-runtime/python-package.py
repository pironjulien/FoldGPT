"""Read exact pinned official bytes; never execute the Android interpreter."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

HERE = Path(__file__).resolve().parent
PIN = json.loads((HERE / 'python-inputs.json').read_text())


def package(archive):
    with archive.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != PIN['sha256']:
            raise ValueError('Official CPython Android archive hash differs')
    contents, aliases = {}, {}
    with tarfile.open(archive) as source:
        for item in source:
            path = PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts:
                raise ValueError('Unsafe official package member')
            if not path.as_posix().startswith('prefix/') or item.isdir():
                continue
            name = path.relative_to('prefix').as_posix()
            if name in contents or name in aliases:
                raise ValueError('Duplicate official package member')
            if item.issym():
                target = PurePosixPath(name).parent / item.linkname
                if target.is_absolute() or '..' in target.parts:
                    raise ValueError('Unsafe official package alias')
                aliases[name] = target.as_posix()
            elif item.isreg():
                contents[name] = source.extractfile(item).read()
            else:
                raise ValueError('Unexpected official package object')
    for name, target in aliases.items():
        contents[name] = contents[target]
    required = {'include/python3.14/Python.h', 'include/python3.14/pyconfig.h', 'lib/libpython3.14.so'}
    if not required.issubset(contents):
        raise ValueError('Official package is missing the required compiler inputs')
    return contents


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('archive', type=Path)
    parser.add_argument('prefix', type=Path)
    args = parser.parse_args()
    count = 0
    for name, data in package(args.archive).items():
        if name.startswith('include/') or name == 'lib/libpython3.14.so':
            if (args.prefix / name).read_bytes() != data:
                raise ValueError(f'Compiler input differs from authenticated package: {name}')
            count += 1
    print(f'Authenticated exact {count} Python compiler inputs')
