"""Apply one fingerprint-gated dependency-provider hook to a known client ASAR.

The original archive is preserved. Only the reviewed module receives an added
FoldGPT adapter; every existing byte in every other member is retained. This is
a FoldGPT client integration, never represented as an unchanged official ASAR.
"""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
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
    """Retain the in-memory API; installation uses the bounded stream plan."""
    stream = io.BytesIO(source)
    plan, descriptor = adaptation_plan(stream, digest(source))
    return b''.join(plan_chunks(stream, plan)), descriptor


def adaptation_plan(stream, source_sha256):
    descriptor = KNOWN.get(source_sha256)
    if descriptor is None:
        raise ValueError('Client revision not reviewed for the FoldGPT workspace provider')
    stream.seek(0)
    _, header_size, payload_size, json_size = struct.unpack('<IIII', stream.read(16))
    if payload_size + 4 != header_size or json_size > payload_size - 4:
        raise ValueError('Unexpected ASAR header')
    base = 8 + header_size
    header = json.loads(stream.read(json_size))
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
                size = member['size']
                segment = (start, size)
                if location == descriptor['module']:
                    stream.seek(start)
                    data = stream.read(size)
                    if digest(data) != descriptor['sha256']:
                        raise ValueError('The dependency module differs from the reviewed bytes')
                    names = descriptor['names']
                    properties = ['resolveManifest', 'downloadFile', 'validatePaths', 'diagnose', 'instructions']
                    entries = ','.join(key + ':' + value for key, value in zip(properties, names))
                    hook = ("\n;/* FoldGPT workspace provider v1 */\n"
                            f"({{{entries}}}=require('/usr/local/lib/foldgpt/foldgpt-workspace-provider.cjs').integrate({{{entries}}}));\n")
                    data += hook.encode()
                    segment = data
                    size = len(data)
                    changed.append(location)
                    if 'integrity' in member:
                        block_size = member['integrity']['blockSize']
                        member['integrity'].update(hash=digest(data),
                            blocks=[digest(data[i:i + block_size]) for i in range(0, len(data), block_size)])
                member['offset'] = str(offset)
                member['size'] = size
                blocks.append(segment)
                offset += size
    visit(header)
    if changed != [descriptor['module']]:
        raise ValueError('Expected exactly one adapted module')
    raw = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode()
    padded = raw + b'\0' * (-len(raw) % 4)
    header_bytes = struct.pack('<II', len(padded) + 4, len(raw)) + padded
    return [struct.pack('<II', 4, len(header_bytes)) + header_bytes, *blocks], descriptor


CHUNK = 1024 * 1024


def plan_chunks(stream, plan):
    for segment in plan:
        if isinstance(segment, bytes):
            yield segment
            continue
        offset, remaining = segment
        stream.seek(offset)
        while remaining:
            data = stream.read(min(CHUNK, remaining))
            if not data:
                raise ValueError('Truncated reviewed ASAR')
            remaining -= len(data)
            yield data


def stream_digest(stream):
    stream.seek(0)
    result = hashlib.sha256()
    while data := stream.read(CHUNK):
        result.update(data)
    return result.hexdigest()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def exists(path):
    return os.path.lexists(path)


def directory_chain(path):
    """Validate existing ancestors without creating any path or following aliases."""
    for item in reversed((path, *path.parents)):
        if exists(item) and not stat.S_ISDIR(item.lstat().st_mode):
            raise ValueError('Workspace adapter state is not a real directory')


@contextlib.contextmanager
def snapshot(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Expected a regular, unaliased workspace adapter file')
        yield stream
        if identity(os.fstat(stream.fileno())) != identity(before) or identity(path.lstat()) != identity(before):
            raise ValueError('Workspace adapter input changed while being verified')


def verified_backup(path, expected):
    with snapshot(path) as stream:
        if stream_digest(stream) != expected:
            raise ValueError('The preserved official ASAR backup differs')


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate workspace adapter receipt field')
        result[key] = value
    return result


def inspect_client(asar, state):
    """Read-only admission. Receipts never select or authenticate client bytes."""
    directory_chain(state)
    directory_chain(asar.parent)
    if asar.absolute().is_relative_to(state.absolute()):
        raise ValueError('Installed ASAR must be separate from its backup state')
    with snapshot(asar) as stream:
        current_identity = identity(os.fstat(stream.fileno()))
        current = stream_digest(stream)
    official = current if current in KNOWN else None
    original_path = asar if official else None
    if official is None:
        for candidate in KNOWN:
            backup = state / (candidate + '.official.asar')
            if not exists(backup):
                continue
            with snapshot(backup) as stream:
                if stream_digest(stream) != candidate:
                    raise ValueError('The preserved official ASAR backup differs')
                plan, descriptor = adaptation_plan(stream, candidate)
                expected = hashlib.sha256()
                for block in plan_chunks(stream, plan):
                    expected.update(block)
            if expected.hexdigest() == current:
                official, original_path = candidate, backup
                break
    if official is None:
        raise ValueError('Client revision not reviewed for the FoldGPT workspace provider')
    backup = state / (official + '.official.asar')
    if original_path == asar and exists(backup):
        verified_backup(backup, official)
    if original_path == asar:
        with snapshot(original_path) as stream:
            if stream_digest(stream) != official:
                raise ValueError('Reviewed original ASAR changed')
            plan, descriptor = adaptation_plan(stream, official)
            expected = hashlib.sha256()
            for block in plan_chunks(stream, plan):
                expected.update(block)
    record = {'provider': 'FoldGPT', 'officialSha256': official, 'adaptedSha256': expected.hexdigest(),
              'modifiedModule': descriptor['module'], 'backup': str(backup)}
    record_path = state / 'client-adapter.json'
    if exists(record_path):
        with snapshot(record_path) as stream:
            data = stream.read(65537)
        if len(data) > 65536 or json.loads(data, object_pairs_hook=unique_json) != record:
            raise ValueError('Workspace adapter receipt differs from independently reviewed bytes')
    if identity(asar.lstat()) != current_identity:
        raise ValueError('Installed ASAR changed during compatibility validation')
    return record, current_identity, current == official


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_state(path):
    directory_chain(path)
    missing = []
    current = path
    while not exists(current):
        missing.append(current)
        current = current.parent
    for item in reversed(missing):
        item.mkdir(mode=0o700)
        sync_directory(item.parent)


def checkpoint(name):
    """Test injection point; production has no environment-controlled failpoint."""


def atomic_write(path, chunks, mode, before_publish=lambda: None):
    fd, temporary = tempfile.mkstemp(prefix='.foldgpt-adapter-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            for data in chunks:
                stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        before_publish()
        checkpoint('before-rename:' + path.name)
        os.replace(temporary, path)
        checkpoint('after-rename:' + path.name)
        sync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def original_chunks(path, expected):
    with snapshot(path) as stream:
        actual = hashlib.sha256()
        while data := stream.read(CHUNK):
            actual.update(data)
            yield data
        if actual.hexdigest() != expected:
            raise ValueError('Reviewed original ASAR changed before backup publication')


def adapted_chunks(backup, record):
    with snapshot(backup) as stream:
        if stream_digest(stream) != record['officialSha256']:
            raise ValueError('The preserved official ASAR backup differs')
        plan, _ = adaptation_plan(stream, record['officialSha256'])
        actual = hashlib.sha256()
        for block in plan_chunks(stream, plan):
            actual.update(block)
            yield block
        if actual.hexdigest() != record['adaptedSha256']:
            raise ValueError('Recomputed workspace adaptation differs')


def install(asar, state, check_only=False):
    record, observed, original = inspect_client(asar, state)
    if check_only:
        return {'status': 'verified', 'clientState': 'original' if original else 'adapted', **record}
    # Admission precedes even state/lock creation. This lease serializes our
    # installers; it is not a boundary against hostile concurrent same-UID code.
    create_state(state)
    lock_path = state / 'install.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Invalid workspace adapter installation lease')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fsync(lock.fileno())
        sync_directory(state)
        record, observed, original = inspect_client(asar, state)
        backup = state / (record['officialSha256'] + '.official.asar')
        if original:
            if not exists(backup):
                def absent_backup():
                    if exists(backup):
                        raise ValueError('Official ASAR backup appeared during publication')
                atomic_write(backup, original_chunks(asar, record['officialSha256']), 0o600, absent_backup)
            # An earlier process may have died immediately after the rename.
            with snapshot(backup) as stream:
                if stream_digest(stream) != record['officialSha256']:
                    raise ValueError('The preserved official ASAR backup differs')
                os.fsync(stream.fileno())
            sync_directory(state)
            checkpoint('after-backup')
            def unchanged_asar():
                if identity(asar.lstat()) != observed:
                    raise ValueError('Installed ASAR changed before activation')
            atomic_write(asar, adapted_chunks(backup, record), observed[3] & 0o777, unchanged_asar)
            checkpoint('after-asar')
        else:
            # Recovery also makes an earlier ASAR publication durable before
            # publishing its receipt; reconstructing that receipt needs no guess.
            with snapshot(asar) as stream:
                os.fsync(stream.fileno())
            sync_directory(asar.parent)
        record_path = state / 'client-adapter.json'
        if not exists(record_path):
            atomic_write(record_path, [json.dumps(record, indent=2).encode('utf-8')], 0o600)
            checkpoint('after-receipt')
        else:
            with snapshot(record_path) as stream:
                os.fsync(stream.fileno())
            sync_directory(state)
        return {'status': 'adapted' if original else 'current', **record}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asar', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Verify compatibility without creating or changing any file')
    args = parser.parse_args()
    print(json.dumps(install(args.asar, args.state, args.check)))


if __name__ == '__main__':
    main()
