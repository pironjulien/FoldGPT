"""Collect completed Android private-bridge v1/v2 diagnostics independently.

All targets derive from the validated fixture name or Package Manager, never
report/RPC paths. The installed APK must match --apk before and after collection.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import zipfile

STREAM_BYTES = 37 * 1024 * 1024 + 13
DIAGNOSTICS = ('report.json', 'rpc-transcript.json', 'broker-events.json', 'bridge-command.json',
    'broker-stderr.txt', 'bridge-0-stderr.txt', 'bridge-1-stderr.txt', 'android-completion.txt', 'fixture-output.txt')
SOURCES = ('tools/executor/exec_server.py', 'tools/executor/native_files.py', 'tools/executor/policy_intent.py',
    'tools/policy/managed_policy.py', 'tools/executor/native_files_rpc_fixture.py',
    'tools/executor/private_exec_broker.py', 'tools/executor/private_exec_fixture.py')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pattern(offset, length):
    start = offset % 256
    return (bytes(range(256)) * ((start + length + 255) // 256))[start:start + length]


def policy_context():
    # Independent fixed diagnostic policy, never imported from the producer.
    return {'permissions': {'type': 'managed', 'file_system': {'type': 'restricted', 'entries': [
        {'path': {'type': 'special', 'value': {'kind': 'root'}}, 'access': 'read'},
        {'path': {'type': 'path', 'path': 'file:///workspace'}, 'access': 'write'},
        {'path': {'type': 'path', 'path': 'file:///workspace/private'}, 'access': 'deny'},
        {'path': {'type': 'path', 'path': 'file:///workspace/.git/allowed'}, 'access': 'write'}]},
        'network': 'restricted'}, 'cwd': 'file:///workspace', 'workspaceRoots': ['file:///workspace'],
        'userHomeDir': 'file:///fixture-home', 'temporaryDirectories': ['file:///fixture-tmp'],
        'windowsSandboxLevel': 'disabled'}


def verify_transcript(transcript, report, version):
    """Verify every request, correlation, result, byte block and refusal in order."""
    require(type(transcript) is list and len(transcript) == report['rpcResponses'] == (53 if version == 2 else 32),
        'Incomplete RPC transcript')
    cursor = 0
    for session in range(2):
        identifier = 0

        def consume(method, params, result=None, error=None):
            nonlocal cursor, identifier
            require(cursor < len(transcript), 'Missing RPC')
            item = transcript[cursor]
            cursor += 1
            identifier += 1
            require(set(item) == {'method', 'params', 'response'} and item['method'] == method
                and item['params'] == params, f'Unexpected request at RPC {cursor}: {method}')
            response = item['response']
            require(type(response) is dict and type(response.get('id')) is int and response['id'] == identifier
                and set(response) == {'id', 'error' if error is not None else 'result'}, 'Invalid correlated response')
            if error is not None:
                require(response['error'].get('code') == error and isinstance(response['error'].get('message'), str),
                    f'Missing refusal at RPC {cursor}')
                return response['error']
            if result is not None:
                require(response['result'] == result, f'Result differs at RPC {cursor}: {method}')
            return response['result']

        def path(value):
            return {'path': 'file:///workspace/' + value, 'sandbox': policy_context()}

        initialized = consume('initialize', {'clientName': 'foldgpt-private-guest-bridge'})
        require(initialized['sessionId'] == report['sessions'][session], 'Session ID differs')
        capabilities = initialized['environmentInfo']['capabilities']
        require(all(type(value) is bool for value in capabilities.values())
            and {key for key, value in capabilities.items() if value} ==
            ({'sandboxedFileStreaming'} if version == 2 else set()), 'Unsupported capability advertised')
        consume('environment/status', {}, {'status': 'ready'})
        payload = bytes(range(256)) * 1024 + f'épreuve-{session}-🐍'.encode()
        encoded = base64.b64encode(payload).decode()
        consume('fs/writeFile', {**path('value'), 'dataBase64': encoded}, {})
        consume('fs/readFile', path('value'), {'dataBase64': encoded})
        for name in ('private/forbidden', '.git/config'):
            consume('fs/writeFile', {**path(name), 'dataBase64': 'eA=='}, error=-32000)
        consume('fs/createDirectory', {**path('tree'), 'recursive': True}, {})
        consume('fs/writeFile', {**path('tree/data'), 'dataBase64': encoded}, {})
        consume('fs/readDirectory', path('tree'), {'entries': [{'fileName': 'data', 'isDirectory': False, 'isFile': True}]})
        consume('fs/walk', {**path('tree'), 'options': {'maxDepth': 4, 'maxDirectories': 10, 'maxEntries': 100,
            'followDirectorySymlinks': False}}, {'entries': [{'path': 'file:///workspace/tree/data', 'kind': 'file'}],
            'errors': [], 'truncated': False})
        consume('fs/copy', {'sourcePath': 'file:///workspace/tree', 'destinationPath': 'file:///workspace/copied',
            'recursive': True, 'sandbox': policy_context()}, {})
        consume('fs/copy', {'sourcePath': 'file:///workspace/private', 'destinationPath': 'file:///workspace/forbidden-copy',
            'recursive': True, 'sandbox': policy_context()}, error=-32000)
        consume('fs/remove', {**path('.git'), 'recursive': True}, error=-32000)
        consume('fs/remove', path('tree'), {})
        consume('fs/remove', path('copied'), {})
        if version == 2:
            if session:
                consume('fs/readBlock', {'handleId': 'stream-eof-owned', 'offset': 0, 'len': 1}, error=-32004)
            consume('fs/open', {**path('stream-large.bin'), 'handleId': 'stream-blocks'}, {'handleId': 'stream-blocks'})
            for offset, length in ((0, 1048576), (16 * 1024 * 1024 + 17, 1048576), (STREAM_BYTES - 13, 32), (STREAM_BYTES, 1)):
                size = min(length, max(0, STREAM_BYTES - offset))
                result = consume('fs/readBlock', {'handleId': 'stream-blocks', 'offset': offset, 'len': length})
                require(set(result) == {'chunk', 'eof'} and type(result['eof']) is bool
                    and result['eof'] is (size < length)
                    and base64.b64decode(result['chunk'], validate=True) == pattern(offset, size),
                    'Streaming bytes, offset or EOF differ')
            consume('fs/close', {'handleId': 'stream-blocks'}, {})
            consume('fs/readBlock', {'handleId': 'stream-blocks', 'offset': 0, 'len': 1}, error=-32004)
            consume('fs/open', {**path('private/secret'), 'handleId': 'denied'}, error=-32000)
            consume('fs/open', {**path('absent-stream'), 'handleId': 'absent'}, error=-32004)
            consume('fs/open', {**path('stream-large.bin'), 'handleId': 'stream-eof-owned'}, {'handleId': 'stream-eof-owned'})
        consume('process/start', {'processId': 'unsupported', 'argv': ['/system/bin/true'], 'cwd': 'file:///workspace',
            'env': {}, 'tty': False, 'sandbox': policy_context()}, error=-32601)
    require(cursor == len(transcript), 'Unexpected trailing RPCs')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('serial', 'fixture'):
        parser.add_argument('--' + name, required=True)
    for name in ('apk', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'pex-[0-9]{1,20}', args.fixture), 'Expected exact Android fixture name')
    remote = 'cache/' + args.fixture
    adb = ['adb', '-s', args.serial]
    apk_sha = sha(args.apk.read_bytes())

    def shell(*command, app=True):
        argv = ['run-as', 'app.foldgpt', *command] if app else list(command)
        result = subprocess.run(adb + ['shell', '-T', shlex.join(argv)], timeout=30, capture_output=True)
        require(result.returncode == 0 and not result.stderr, 'Device read failed: ' + command[0])
        return result.stdout

    def remote_hash(target):
        digest = shell('sha256sum', target).split(maxsplit=1)[0].decode('ascii')
        require(re.fullmatch(r'[0-9a-f]{64}', digest), 'Malformed native SHA-256')
        return digest

    def installed_apk():
        lines = shell('pm', 'path', 'app.foldgpt', app=False).decode().splitlines()
        require(len(lines) == 1 and re.fullmatch(r'package:/data/app/[A-Za-z0-9_+=.~/-]+/base\.apk', lines[0]),
            'Expected one Package Manager owned base APK')
        target = lines[0][8:]
        require('..' not in PurePosixPath(target).parts, 'Invalid installed package path')
        digest = remote_hash(target)
        require(digest == apk_sha, 'Installed APK differs from supplied tested APK')
        return {'path': target, 'sha256': digest}

    before = installed_apk()
    native_dir = str(PurePosixPath(before['path']).parent / 'lib/arm64')
    args.output.mkdir(parents=True, exist_ok=False)
    uid = int(shell('id', '-u').strip())
    require(uid > 0 and shell('pwd').decode().strip() in {'/data/user/0/app.foldgpt', '/data/data/app.foldgpt'},
        'Expected nonroot Android app context')
    absolute = '/data/data/app.foldgpt/' + remote  # Service uses getCanonicalFile().
    file_evidence = {}

    def metadata(target, directory=False):
        fields = shell('stat', '-c', '%f %u %g %s %d %i %a %h', target).decode().split()
        require(len(fields) == 8, 'Malformed native metadata')
        mode = int(fields[0], 16)
        values = [int(value, 8 if index == 6 else 10) for index, value in enumerate(fields[1:], 1)]
        info = dict(zip(('uid', 'gid', 'bytes', 'device', 'inode', 'mode', 'links'), values))
        require((stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)) and info['uid'] == uid
            and not info['mode'] & 0o077 and (directory or info['links'] == 1), 'Not a private ordinary fixture target: ' + target)
        return info

    for relative in ('', '/workspace', '/workspace/.git', '/workspace/private', '/ipc', '/sources',
                     '/sources/tools', '/sources/tools/executor', '/sources/tools/policy'):
        metadata(remote + relative, directory=True)

    def read_fixed(relative, maximum):
        target = remote + '/' + relative
        info = metadata(target)
        require(info['bytes'] <= maximum, 'Fixed evidence exceeds bound')
        # Windows adb shell-v2 translates line endings even with -T. Base64
        # preserves exact source/binary bytes while retaining remote exit status.
        data = base64.b64decode(b''.join(shell('base64', target).splitlines()), validate=True)
        digest = sha(data)
        require(len(data) == info['bytes'] and remote_hash(target) == digest, 'Evidence changed during read')
        file_evidence[relative] = {**info, 'sha256': digest}
        return data

    for name in DIAGNOSTICS:
        (args.output / name).write_bytes(read_fixed(name, 16 * 1024 * 1024 if name == 'rpc-transcript.json' else 1024 * 1024))
    report = json.loads((args.output / 'report.json').read_bytes())
    require(report.get('schema') in {'foldgpt.private-exec-fixture.v1', 'foldgpt.private-exec-fixture.v2'}
        and report.get('status') == 'PASS', 'Android fixture did not pass')
    version = int(report['schema'][-1])
    require((args.output / 'android-completion.txt').read_bytes() == f'PASS uid={uid}\n'.encode(), 'Missing app UID completion')
    require(json.loads((args.output / 'fixture-output.txt').read_bytes()) == report, 'Fixture stdout differs from report')
    for name in DIAGNOSTICS:
        if 'stderr' in name:
            require((args.output / name).read_bytes() == b'', 'Fixture stderr not empty: ' + name)
    require(report['workspace'] == absolute + '/workspace', 'Report belongs to a different fixture')
    for name in ('observation', 'brokerObservation'):
        observed = report[name]
        require(observed['uid'] == observed['gid'] == uid and observed['machine'] == 'aarch64'
            and observed['status']['Uid'].split() == observed['status']['Gid'].split() == [str(uid)] * 4
            and observed['status']['Seccomp'] == '2' and observed['status']['TracerPid'] == '0'
            and int(observed['status']['CapEff'], 16) == int(observed['status']['CapPrm'], 16) == 0
            and observed['securityContext'].startswith('u:r:untrusted_app')
            and observed['executable'] == native_dir + '/libfoldgpt_python.so', 'Native context or executing APK differs')
        require(not any('fake_userns' in target or 'libproot' in target for target in observed['mappedFiles']),
            'Native supervisor mapped guest compatibility layer')
    require(len(report['sessions']) == len(set(report['sessions'])) == 2, 'Expected distinct sessions')
    peers = report['authenticatedBridgePeers']
    require(len(peers) == 2 and len({peer['pid'] for peer in peers}) == 2
        and all(peer['uid'] == peer['gid'] == uid and peer['pid'] > 0 for peer in peers), 'Invalid authenticated peers')
    events = json.loads((args.output / 'broker-events.json').read_bytes())
    require([event['event'] for event in events] == ['ready', 'session-open', 'session-closed', 'session-open', 'session-closed', 'stopped'],
        'Incomplete broker lifecycle')
    require(events[0]['socket'] == absolute + '/ipc/exec.sock' and events[0]['uid'] == events[0]['peerUid'] == uid
        and events[0]['transport'] == 'AF_UNIX/SOCK_STREAM/SO_PEERCRED', 'Broker readiness differs')
    for index in range(2):
        require(events[1 + 2 * index]['peer'] == events[2 + 2 * index]['peer'] == peers[index]
            and events[2 + 2 * index]['sessionId'] == report['sessions'][index], 'Session closure differs')
    checks = ['native-broker-uid-context-and-private-socket']
    for index in range(2):
        checks.append(f'guest-tree-rpcs-and-protected-mutation-refusals-{index}')
        if version == 2:
            checks.append(f'guest-streaming-large-binary-offsets-policy-and-fd-cleanup-{index}')
        checks.append(f'guest-bridge-native-rpc-policy-and-eof-cleanup-{index + 1}')
    checks += ['distinct-reconnected-sessions', 'broker-peer-credentials-and-supervisor-socket-cleanup']
    require(report['checks'] == checks, 'Missing physical fixture/lifecycle check')
    transcript = json.loads((args.output / 'rpc-transcript.json').read_bytes())
    verify_transcript(transcript, report, version)
    command_data = (args.output / 'bridge-command.json').read_bytes()
    require(sha(command_data) == report['bridgeCommandFileSha256'], 'Bridge command hash differs')
    command = [native_dir + '/libproot.so', '--kill-on-exit', '--link2symlink', '--sysvipc', '-r',
        '/data/data/app.foldgpt/files/debian', '-i', f'{uid}:{uid}', '-w', '/workspace']
    for binding in ('/dev', '/proc', '/sys', '/system', '/apex', absolute + '/tmp:/tmp', absolute + '/shm:/dev/shm',
        absolute + '/ipc:/tmp/foldgpt-private-ipc', absolute + '/workspace:/workspace', absolute + '/home:/tmp/foldgpt-private-home',
        native_dir + '/libfoldgpt-exec-bridge.so:/tmp/foldgpt-exec-bridge'):
        command.extend(['-b', binding])
    command.extend(['/usr/bin/env', '-i', 'PATH=/usr/bin:/bin', 'HOME=/tmp/foldgpt-private-home', 'LANG=C.UTF-8', '/tmp/foldgpt-exec-bridge'])
    require(json.loads(command_data) == command, 'Fixed GNU bridge argv differs')
    payload = bytes(range(256)) * 1024 + 'épreuve-1-🐍'.encode()
    actual = read_fixed('workspace/value', 1024 * 1024)
    require(actual == payload and sha(actual) == report['valueSha256'], 'Independent final data differ')
    require(read_fixed('workspace/.git/config', 1024) == b'metadata', 'Protected metadata changed')
    streaming = None
    if version == 2:
        require(read_fixed('workspace/private/secret', 1024) == b'fixture-private-stream', 'Private fixture bytes changed')
        target = remote + '/workspace/stream-large.bin'
        info = metadata(target)
        digest = hashlib.sha256()
        for _ in range(37):
            digest.update(pattern(0, 1024 * 1024))
        digest.update(bytes(range(13)))
        require(info['bytes'] == report['streaming']['fileBytes'] == STREAM_BYTES
            and remote_hash(target) == report['streaming']['fileSha256'] == digest.hexdigest(), 'Independent large-file size/bytes differ')
        streaming = {**info, 'sha256': digest.hexdigest(), 'blockResponses': 8, 'reconnectedHandleRefused': True}
        file_evidence['workspace/stream-large.bin'] = {**info, 'sha256': digest.hexdigest()}
    else:
        require(report.get('streaming') is None, 'Unexpected streaming in v1')
    absent = ['workspace/tree', 'workspace/copied', 'workspace/forbidden-copy', 'workspace/private/forbidden', 'ipc/exec.sock']
    if version == 2:
        absent.append('workspace/absent-stream')

    def check_absent():
        for name in absent:
            target = shlex.quote(remote + '/' + name)
            # Include dangling symlinks; shell-v2 returns real remote exit status.
            shell('sh', '-c', f'test ! -e {target} && test ! -L {target}')

    check_absent()
    sources = SOURCES + (('tools/executor/native_file_streams.py',) if version == 2 else ())
    libraries, source_hashes = {}, {}
    with zipfile.ZipFile(args.apk) as apk:
        require(len(apk.namelist()) == len(set(apk.namelist())), 'Duplicate APK entries')
        prefix = 'assets/private-exec-probe/'
        require({name[len(prefix):] for name in apk.namelist() if name.startswith(prefix) and not name.endswith('/')} == set(sources),
            'Packaged diagnostic source set differs')
        for name in sources:
            data = read_fixed('sources/' + name, 1024 * 1024)
            require(data == apk.read(prefix + name), 'Executed private source differs from APK: ' + name)
            output = args.output / 'sources' / name
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(data)
            source_hashes[name] = sha(data)
        for entry in apk.namelist():
            if not entry.startswith('lib/arm64-v8a/') or entry.endswith('/'):
                continue
            name = entry[len('lib/arm64-v8a/'):]
            require(re.fullmatch(r'lib[A-Za-z0-9_.-]+\.so', name), 'Invalid APK library name')
            digest = sha(apk.read(entry))
            require(remote_hash(native_dir + '/' + name) == digest, 'Installed library differs: ' + name)
            libraries[name] = digest
    require(libraries['libfoldgpt-native-files.so'] == report['nativeHelperSha256'], 'Native helper differs from APK')
    for name in ('libfoldgpt_python.so', 'libfoldgpt-exec-bridge.so', 'libproot.so', 'libproot-loader.so', 'libtalloc.so'):
        require(name in libraries, 'Missing execution library')
    if version == 2:
        require(libraries['libfoldgpt_file_handle.so'] == report['streaming']['helperSha256'], 'Streaming helper differs from APK')
    for name, info in file_evidence.items():
        require(metadata(remote + '/' + name) == {key: value for key, value in info.items() if key != 'sha256'}
            and remote_hash(remote + '/' + name) == info['sha256'], 'Evidence drifted during collection: ' + name)
    check_absent()
    for name, digest in libraries.items():
        require(remote_hash(native_dir + '/' + name) == digest, 'Installed library changed during collection')
    after = installed_apk()
    require(after == before and sha(args.apk.read_bytes()) == apk_sha, 'APK identity changed during collection')
    evidence = {path.relative_to(args.output).as_posix(): sha(path.read_bytes()) for path in args.output.rglob('*') if path.is_file()}
    result = {'schema': 'foldgpt.private-exec-independent.v2', 'status': 'PASS', 'fixture': args.fixture,
        'fixtureSchema': report['schema'], 'collectedAtUtc': datetime.now(timezone.utc).isoformat(), 'uid': uid,
        'rpcResponses': len(transcript), 'sessions': 2, 'apkSha256': apk_sha, 'installedApkBefore': before, 'installedApkAfter': after,
        'librariesSha256': libraries, 'privateSourcesSha256': source_hashes,
        'stderrBytes': {name: 0 for name in DIAGNOSTICS if 'stderr' in name}, 'fixtureFiles': file_evidence,
        'absentTargets': absent, 'streaming': streaming, 'evidenceSha256': evidence, 'collectorSha256': sha(Path(__file__).read_bytes()),
        'scope': 'Actual private guest bridge, selected native file/stream policies and completed fixture evidence; no model or general command executor'}
    (args.output / 'independent-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'fixture', 'uid', 'rpcResponses', 'sessions', 'apkSha256')}, indent=2))


if __name__ == '__main__':
    main()
