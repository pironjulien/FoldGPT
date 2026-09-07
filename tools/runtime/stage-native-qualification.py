"""Create only the exact disposable workspace for the fixed kernel worker.

Refuses an existing base. No application, runtime, command worker, setting or
kernel feature is started or changed. Failed staging is preserved for inspection.
"""
import argparse
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile
from runtime_qualification_identity import BASE as RUNTIME_BASE, DIRECTORIES, FILES, ENTRIES


def fixture(base):
    if base == RUNTIME_BASE:
        return dict(FILES), {name: set(values) for name, values in ENTRIES.items()}
    if not re.fullmatch(r'/data/local/tmp/foldgpt-bionic-supervisor-qualification-[A-Za-z0-9_-]+', base):
        raise ValueError('Expected a dedicated kernel base or the exact independent runtime base')
    return ({'workspace/input': b'pin-memory-ok\n',
             'workspace/private/secret': b'probe-private-unchanged\n',
             'workspace/directory/marker': b'marker\n'},
            {'workspace': {'.git', 'directory', 'input', 'private'},
             'workspace/private': {'secret'}, 'workspace/directory': {'marker'},
             'workspace/.git': set()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--verify-only', action='store_true', help='Read an existing fixture without creating or changing it')
    args = parser.parse_args()
    try:
        files, entries = fixture(args.base)
    except ValueError as error:
        parser.error(str(error))
    args.output.mkdir(parents=True, exist_ok=False)
    payload = io.BytesIO()
    with tarfile.open(fileobj=payload, mode='w') as archive:
        for name in DIRECTORIES:
            entry = tarfile.TarInfo(name)
            entry.type = tarfile.DIRTYPE
            entry.mode = 0o700
            entry.uid = entry.gid = 2000
            archive.addfile(entry)
        for name, content in files.items():
            entry = tarfile.TarInfo(name)
            entry.size = len(content)
            entry.mode = 0o600
            entry.uid = entry.gid = 2000
            archive.addfile(entry, io.BytesIO(content))
    data = payload.getvalue()
    (args.output / 'fixture.tar').write_bytes(data)
    report = {'schema': 'foldgpt.native-fixture-staging.v1', 'base': args.base,
              'serial': args.serial, 'payloadSha256': hashlib.sha256(data).hexdigest(),
              'files': {name: hashlib.sha256(content).hexdigest() for name, content in files.items()},
              'verified': False, 'verifyOnly': args.verify_only, 'commands': []}

    def run(name, command, input_bytes=None):
        try:
            result = subprocess.run([args.adb, '-s', args.serial, 'shell', '-T', shlex.join(command)],
                                    input=input_bytes, capture_output=True, timeout=30)
        except subprocess.TimeoutExpired:
            report['commands'].append({'name': name, 'argv': command, 'timedOut': True})
            raise
        (args.output / (name + '.stdout')).write_bytes(result.stdout)
        (args.output / (name + '.stderr')).write_bytes(result.stderr)
        report['commands'].append({'name': name, 'argv': command, 'returncode': result.returncode})
        if result.returncode or result.stderr:
            raise RuntimeError('Staging refused or failed at ' + name + '; existing data retained')
        return result.stdout

    try:
        if run('identity', ['id', '-u']).strip() != b'2000':
            raise RuntimeError('The staging operator must be nonroot ADB shell')
        # One shell, literal quoted path, exclusive mkdir. Never merge into or
        # remove an earlier qualification, including a failed partial staging.
        if not args.verify_only:
            run('create', ['sh', '-c', 'umask 077\nmkdir -- ' + shlex.quote(args.base)])
            run('extract', ['tar', '-xf', '-', '-C', args.base], data)
        paths = [args.base] + [args.base + '/' + name for name in DIRECTORIES]
        observed = run('directory-metadata', ['stat', '-c', '%u:%g:%a:%F', *paths]).decode().splitlines()
        if observed != ['2000:2000:700:directory'] * len(paths):
            raise RuntimeError('Unexpected fixture directory ownership or permissions')
        for index, (name, content) in enumerate(files.items()):
            encoded = run('file-' + str(index), ['base64', args.base + '/' + name])
            actual = base64.b64decode(encoded.replace(b'\r', b'').replace(b'\n', b''), validate=True)
            if actual != content:
                raise RuntimeError('Fixture bytes differ after staging')
            metadata = run('file-metadata-' + str(index), ['stat', '-c', '%u:%g:%a:%F', args.base + '/' + name])
            if metadata.strip() != b'2000:2000:600:regular file':
                raise RuntimeError('Unexpected fixture file metadata')
        for index, (name, expected) in enumerate(entries.items()):
            listing = run('directory-entries-' + str(index), ['ls', '-1A', args.base + '/' + name])
            if set(listing.decode().splitlines()) != expected:
                raise RuntimeError('Unexpected fixture directory entry: ' + name)
        report['verified'] = True
    finally:
        (args.output / 'staging.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'verified': report['verified'], 'verifyOnly': args.verify_only, 'base': args.base,
                      'scope': 'Fixture files only; no native execution'}))


if __name__ == '__main__':
    main()
