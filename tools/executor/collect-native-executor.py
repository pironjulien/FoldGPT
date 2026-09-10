"""Read-only independent collection of a fixed Android composite probe.

The completed cx-* fixture, APK and Package Manager determine every target.
No fixture execution, installation, account access or process signaling occurs.
Partial failures remain failures and retain their nine real case directories.
"""
import argparse
import ast
import base64
from collections import Counter
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import zipfile

SHARED = Path(__file__).with_name('collect-native-processes.py')
spec = importlib.util.spec_from_file_location('lifecycle_collector', SHARED)
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)
require, sha, strict_json = lifecycle.require, lifecycle.sha, lifecycle.strict_json
SOURCES = ('tools/executor/exec_server.py', 'tools/executor/native_files.py',
    'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
    'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
    'tools/executor/native_processes.py', 'tools/executor/native_file_streams.py',
    'tools/executor/native_environment.py', 'tools/executor/native_environment_unicode.py',
    'tools/executor/native_executor_backend.py', 'tools/executor/private_exec_broker.py',
    'tools/executor/test_native_processes_live.py', 'tools/executor/test_native_executor_transport.py',
    'tools/executor/native_executor_android_fixture.py')
SUITE = 'tools/executor/test_native_executor_transport.py'
WRAPPER = 'tools/executor/native_executor_android_fixture.py'
PROGRAMS = {'runner': 'libfoldgpt-native-process-runner.so', 'fixture': 'libfoldgpt-native-process-fixture.so',
    'files_helper': 'libfoldgpt-native-files.so', 'handle_helper': 'libfoldgpt_file_handle.so',
    'bridge': 'libfoldgpt-exec-bridge.so'}


def inspect_matrix(matrix, output, suite_source, child_source, cases_parent, native_dir=None):
    require(set(matrix) == {'scope', 'passed', 'tests', 'failures', 'errors', 'uid', 'observations', 'artifacts'}
        and type(matrix['uid']) is int and matrix['uid'] > 0 and type(matrix['passed']) is bool,
        'Malformed composite matrix or native UID')
    classes = [node for node in ast.parse(suite_source).body if isinstance(node, ast.ClassDef)
        and node.name == 'CompositeTransportTests']
    require(len(classes) == 1, 'Missing packaged composite test class')
    tests = sorted(node.name for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'))
    require(len(tests) == 9 and [int(name[5:7]) for name in tests] == list(range(1, 10)),
        'Packaged composite suite changed and needs review')
    inventories = any(isinstance(node, ast.FunctionDef) and node.name == 'process_children_snapshot'
        for node in ast.parse(child_source).body)
    statuses = re.findall(r'^(test_[a-zA-Z0-9_]+) \(__main__\.CompositeTransportTests\.\1\) \.\.\. (ok|FAIL|ERROR)$', output, re.M)
    require([name for name, _ in statuses] == tests and re.findall(r'^Ran ([0-9]+) tests in [0-9.]+s$', output, re.M) == ['9'],
        'Unittest output does not cover exactly the nine packaged cases')
    counts = Counter(status for _, status in statuses)
    require(matrix['tests'] == 9 and matrix['failures'] == counts['FAIL'] and matrix['errors'] == counts['ERROR']
        and matrix['passed'] is (counts['ok'] == 9), 'Matrix contradicts actual unittest outcome')
    require(bool(re.search(r'^OK$', output, re.M)) if matrix['passed'] else bool(re.search(r'^FAILED \(', output, re.M)),
        'Missing unittest completion')
    if matrix['passed']:
        require(all(value not in output for value in ('exit status already read', 'will report returncode 255',
            'exception in shielded future')), 'Passing composite still exhibits an ownership warning')
    uid = matrix['uid']
    require(type(matrix['observations']) is list and len(matrix['observations']) == 9,
        'Completed composite suite lacks its nine teardown observations')
    require(set(matrix['artifacts']) == set(PROGRAMS), 'Composite program closure differs')
    for key, item in matrix['artifacts'].items():
        require(set(item) == {'path', 'sha256'} and re.fullmatch(r'[0-9a-f]{64}', item['sha256'])
            and (native_dir is None or item['path'] == native_dir + '/' + PROGRAMS[key]), 'Composite program identity differs')
    coverage, directories = {}, []
    for (name, status), case in zip(statuses, matrix['observations']):
        require(set(case) == {'test', 'uid', 'events', 'caseDirectory', 'caseRetained', 'valueDevice',
            'valueInode', 'finalValueBase64', 'privateSha256'} and case['test'] == '__main__.CompositeTransportTests.' + name
            and case['uid'] == uid and type(case['caseRetained']) is bool
            and (native_dir is None or case['caseRetained']), 'Wrong retained composite case identity')
        number = int(name[5:7])
        path = PurePosixPath(case['caseDirectory'])
        require(str(path.parent) == cases_parent and re.fullmatch(r'fcomp-[a-z0-9_]+', path.name)
            and case['caseDirectory'] == str(path) and str(path) not in directories,
            'Case report escaped its fixed diagnostic parent')
        directories.append(str(path))
        require(type(case['valueDevice']) is int and case['valueDevice'] >= 0
            and type(case['valueInode']) is int and case['valueInode'] > 0,
            'Missing real value inode/device')
        expected_value = b'native-change' if number == 1 else b'after' if number == 3 else b'original'
        require(lifecycle.decode_chunk(case['finalValueBase64']) == expected_value
            and case['privateSha256'] == sha(b'private-intact'), 'Retained fixture bytes or denied secret changed')
        require(type(case['events']) is list and len(case['events']) <= 10000, 'Unbounded composite events')
        pending, pairs, notes, snapshots, sessions, ready, guests = {}, [], [], [], [], [], []
        methods, events = Counter(), Counter()
        session = 0
        for event in case['events']:
            require(type(event) is dict, 'Malformed composite event')
            shape = set(event)
            if shape == {'direction', 'message'}:
                direction, message = event['direction'], event['message']
                require(direction in ('request', 'response') and type(message) is dict, 'Malformed RPC direction')
                if direction == 'request':
                    if 'id' not in message:
                        require(message == {'method': 'initialized', 'params': {}}, 'Unexpected client notification')
                        continue
                    require(set(message) == {'id', 'method', 'params'} and type(message['id']) is int
                        and message['id'] > 0 and type(message['method']) is str and type(message['params']) is dict,
                        'Malformed RPC request')
                    if message['method'] == 'initialize':
                        require(not pending and message['id'] == 1, 'Reinitialization abandoned pending requests')
                        session += 1
                    require(session > 0 and message['id'] not in pending, 'Uninitialized or duplicate pending request')
                    pending[message['id']] = (message, session)
                    methods[message['method']] += 1
                elif 'id' in message:
                    require(set(message) in ({'id', 'result'}, {'id', 'error'}) and message['id'] in pending,
                        'Uncorrelated or duplicate transport response')
                    request, request_session = pending.pop(message['id'])
                    pairs.append((request_session, request, message))
                    if 'error' in message:
                        require(set(message['error']) == {'code', 'message'} and type(message['error']['code']) is int
                            and type(message['error']['message']) is str, 'Malformed real transport error')
                    else:
                        result = message['result']
                        require(type(result) is dict, 'Non-object official response')
                        if request['method'] == 'process/read':
                            lifecycle.inspect_read(result)
                        elif request['method'] == 'process/start':
                            require(result == {'processId': request['params']['processId'], 'sandboxType': 'linuxSeccomp'},
                                'Start fabricated an unsupported sandbox or process identity')
                        elif request['method'] == 'initialize':
                            caps = result['environmentInfo']['capabilities']
                            require(result['environmentInfo']['cwd'] == 'file:///workspace'
                                and {key for key, value in caps.items() if value} == {'sandboxedFileStreaming'}
                                and type(result['sessionId']) is str and result['sessionId'] not in sessions,
                                'Composite advertised unsupported capability or reused session')
                            sessions.append(result['sessionId'])
                else:
                    require(set(message) == {'method', 'params'} and message['method'] in
                        ('process/output', 'process/exited', 'process/closed'), 'Unknown native process notification')
                    require(type(message['params']) is dict and type(message['params'].get('seq')) is int
                        and message['params']['seq'] > 0 and type(message['params'].get('processId')) is str,
                        'Malformed native notification identity/sequence')
                    notes.append((session, message))
            elif shape == {'childSnapshot'}:
                require(inventories, 'Unpackaged child observer evidence')
                lifecycle.inspect_child_snapshot(event['childSnapshot'], uid)
                snapshots.append(event['childSnapshot'])
            elif shape == {'nativeBrokerContext'}:
                require(native_dir is not None, 'Android context in host-only evidence')
                lifecycle.inspect_context(event['nativeBrokerContext'], uid, native_dir)
            elif shape == {'guestBridgeContext'}:
                value = event['guestBridgeContext']
                require(native_dir is not None and set(value) == {'pid', 'prootPid', 'uid', 'tracerPid', 'executable', 'gnuLibcMapped'}
                    and type(value['pid']) is int and value['pid'] > 0 and type(value['prootPid']) is int and value['prootPid'] > 0
                    and value['pid'] != value['prootPid'] and value['tracerPid'] == value['prootPid'] and value['uid'] == uid
                    and value['gnuLibcMapped'] is True and value['executable'] == native_dir + '/libproot-loader.so',
                    'Actual GNU bridge did not retain the expected PRoot/UID identity')
                guests.append(value)
            elif shape == {'broker'}:
                value = event['broker']
                require(type(value) is dict and type(value.get('event')) is str, 'Malformed broker event')
                events[value['event']] += 1
                if value['event'] == 'ready':
                    require(value['socket'] == str(path / 'ipc/exec.sock') and value['uid'] == value['peerUid'] == uid
                        and type(value['pid']) is int and value['pid'] > 0
                        and value['transport'] == 'AF_UNIX/SOCK_STREAM/SO_PEERCRED', 'Broker endpoint/credentials differ')
                    ready.append(value['pid'])
                elif value['event'] == 'session-open':
                    require(value['peer']['uid'] == value['peer']['gid'] == uid, 'Broker authenticated another UID')
            elif shape == {'brokerExit', 'brokerStderrBase64'}:
                diagnostic = lifecycle.decode_chunk(event['brokerStderrBase64'])
                require(type(event['brokerExit']) is int, 'Missing actual broker returncode')
                if number < 7:
                    require(event['brokerExit'] == 0 and diagnostic == b'', 'Clean broker shutdown produced an error')
                if status == 'ok':
                    require(all(value not in diagnostic for value in (b'exit status already read',
                        b'will report returncode 255', b'exception in shielded future')),
                        'Passing broker stderr retains an ownership warning')
            else:
                require(shape in ({'actualLeaseReleased', 'independentDescendantReaped'},
                    {'actualLeaseReleased', 'independentPidsReaped'}, {'nativeSupervisorKilled', 'independentOrphanReaped',
                    'brokerStillQuarantined', 'restartRefusedWithRetainedMarker'}), 'Unknown independent fixture observation')
        require(not pending or status != 'ok', 'Passing case abandoned actual pending RPC requests')
        if status == 'ok':
            require(len(sessions) == (2 if number == 1 else 0 if number == 9 else 1), 'Passing case lacks reviewed sessions')
            if native_dir is not None:
                require(len(guests) == len(sessions) and len(ready) == (0 if number == 9 else 1),
                    'Passing case lacks actual native broker or GNU bridge observations')
                authenticated = [event['broker']['peer']['pid'] for event in case['events']
                    if 'broker' in event and event['broker']['event'] == 'session-open']
                require(authenticated == [value['pid'] for value in guests], 'Bridge identity differs from SO_PEERCRED')
            if inventories:
                require(len(snapshots) == (3 if number in (5, 6, 7) else 1), 'Passing case lacks child inventories')
                if number in (5, 6, 7):
                    require(snapshots[0]['parent']['pid'] == ready[0] and len(snapshots[0]['children']) == 1
                        and snapshots[1]['parent']['pid'] == snapshots[0]['children'][0]
                        and len(snapshots[1]['children']) == 1, 'Runner/worker observation chain differs')
                require(snapshots[-1]['parent']['pid'] == snapshots[-1]['observerPid'], 'Teardown inventoried another parent')
            starts = [(req, res) for _, req, res in pairs if req['method'] == 'process/start']
            require(len(starts) == {1: 6, 2: 4, 3: 1, 4: 1, 5: 1, 6: 1, 7: 2, 8: 0, 9: 0}[number],
                'Passing case lacks exact native admission/refusal coverage')
            reads = {(req['params']['processId'], res['result']['exitCode']): res['result']
                for _, req, res in pairs if req['method'] == 'process/read' and 'result' in res and res['result']['exited']}
            expected = {1: {'read': (0, b'actual-file-before-process'), 'write': (0, b''), 'denied': (0, b'DENIED:13\n')},
                2: {'process': (0, b'\0\xffABC'), 'binary': (17, b'\0\xff\x80OUT'), 'int': (42, b'READYINTERRUPTED'), 'term': (137, b'')},
                3: {'process': (137, b'')}}.get(number, {})
            for process, (code, data) in expected.items():
                require((process, code) in reads and lifecycle.stream_bytes(reads[(process, code)]['chunks']) == data,
                    'Actual process bytes or exit code differ from conformance expectation')
            if number == 2:
                require(lifecycle.stream_bytes(reads[('binary', 17)]['chunks'], 'stderr') == b'\xfe\0ERR',
                    'Binary stderr was altered')
                for process in expected:
                    messages = [item for _, item in notes if item['params']['processId'] == process]
                    require([item['params']['seq'] for item in messages] == list(range(1, len(messages) + 1))
                        and messages[-1]['method'] == 'process/closed', 'Actual process notifications lost ordering/closure')
            if number == 7:
                values = [res['result'] for _, req, res in pairs if req['method'] == 'process/read' and 'result' in res]
                require(values and all(not value['exited'] and not value['closed'] and value['exitCode'] is None
                    and 'unknown' in (value['failure'] or '') for value in values)
                    and not any(item['method'] in ('process/exited', 'process/closed') for _, item in notes),
                    'Lost supervisor fabricated process exit or cleanup')
        coverage[name] = {'status': status, 'events': len(case['events']), 'methodCounts': dict(methods),
            'correlatedResponses': len(pairs), 'notifications': len(notes), 'childInventories': len(snapshots),
            'sessions': len(sessions), 'caseName': path.name}
    return {'testsRun': 9, 'passed': counts['ok'], 'failedTests': [name for name, status in statuses if status != 'ok'],
        'caseCoverage': coverage, 'childObservationRoute': 'proc-status-ppid' if inventories else 'legacy-task-children'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('serial', 'fixture'):
        parser.add_argument('--' + name, required=True)
    for name in ('apk', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'cx-[0-9]{1,20}', args.fixture), 'Expected exact Android cx fixture name')
    remote, absolute = 'cache/' + args.fixture, '/data/data/app.foldgpt/cache/' + args.fixture
    adb = ['adb', '-s', args.serial]
    apk_sha = sha(args.apk.read_bytes())
    collector_source, shared_source = Path(__file__).read_bytes(), SHARED.read_bytes()

    def shell(*command, app=True):
        argv = ['run-as', 'app.foldgpt', *command] if app else list(command)
        result = subprocess.run(adb + ['shell', '-T', shlex.join(argv)], timeout=30, capture_output=True)
        require(result.returncode == 0 and not result.stderr, 'Native read failed: ' + command[0])
        return result.stdout

    def remote_hash(target):
        digest = shell('sha256sum', target).split(maxsplit=1)[0].decode('ascii')
        require(re.fullmatch(r'[0-9a-f]{64}', digest), 'Invalid native SHA-256 response')
        return digest

    def installed_apk():
        lines = shell('pm', 'path', 'app.foldgpt', app=False).decode().splitlines()
        require(len(lines) == 1 and re.fullmatch(r'package:/data/app/[A-Za-z0-9_+=.~/-]+/base\.apk', lines[0]),
            'Expected one Package Manager base APK')
        target = lines[0][8:]
        require('..' not in PurePosixPath(target).parts, 'Invalid installed APK path')
        digest = remote_hash(target)
        require(digest == apk_sha, 'Installed APK differs from supplied tested APK')
        return {'path': target, 'sha256': digest}

    before = installed_apk()
    native_dir = str(PurePosixPath(before['path']).parent / 'lib/arm64')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'collector-source.py').write_bytes(collector_source)
    (args.output / 'collect-native-processes.py').write_bytes(shared_source)
    uid = int(shell('id', '-u').strip())
    require(uid > 0, 'Expected nonroot Android app UID')
    file_metadata, directory_metadata = {}, {}

    def metadata(target, directory=False):
        fields = shell('stat', '-c', '%f %u %g %s %d %i %a %h', target).decode().split()
        require(len(fields) == 8, 'Malformed native file metadata')
        mode = int(fields[0], 16)
        info = dict(zip(('uid', 'gid', 'bytes', 'device', 'inode', 'mode', 'links'),
            [int(value, 8 if index == 6 else 10) for index, value in enumerate(fields[1:], 1)]))
        require((stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)) and info['uid'] == uid
            and not info['mode'] & 0o077 and (directory or info['links'] == 1),
            'Not a private ordinary diagnostic target: ' + target)
        if directory:
            directory_metadata[target] = info
        return info

    for relative in ('', '/cases', '/sources', '/sources/tools', '/sources/tools/executor', '/sources/tools/policy'):
        metadata(remote + relative, directory=True)

    def present(relative):
        target = shlex.quote(remote + '/' + relative)
        response = shell('sh', '-c', f'if test -e {target} || test -L {target}; then echo present; else echo absent; fi').strip()
        require(response in (b'present', b'absent'), 'Invalid optional diagnostic status')
        return response == b'present'

    def read_fixed(relative):
        target = remote + '/' + relative
        info = metadata(target)
        require(info['bytes'] <= (64 if relative == 'composite-tests.json' else 8) * 1024 * 1024,
            'Diagnostic exceeds collection bound')
        data = base64.b64decode(b''.join(shell('base64', target).splitlines()), validate=True)
        require(len(data) == info['bytes'] and remote_hash(target) == sha(data), 'Diagnostic changed during collection')
        file_metadata[relative] = {**info, 'sha256': sha(data)}
        output = args.output / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return data

    matrix_data = read_fixed('composite-tests.json')
    output_data = read_fixed('fixture-output.txt')
    context_before = strict_json(read_fixed('android-context-before.json'))
    lifecycle.inspect_context(context_before, uid, native_dir)
    optional = {name: present(name) for name in ('report.json', 'android-completion.txt')}
    optional_data = {name: read_fixed(name) for name, exists in optional.items() if exists}
    source_data, libraries = {}, {}
    with zipfile.ZipFile(args.apk) as apk:
        require(len(apk.namelist()) == len(set(apk.namelist())), 'Duplicate APK entries')
        prefix = 'assets/native-executor-probe/'
        expected_sources = lifecycle.source_closure(SOURCES, apk.read(prefix + lifecycle.BACKEND_SOURCE),
            apk.read(prefix + lifecycle.SUITE))
        require({name[len(prefix):] for name in apk.namelist() if name.startswith(prefix) and not name.endswith('/')} == set(expected_sources),
            'Packaged composite source closure differs')
        for name in expected_sources:
            source_data[name] = read_fixed('sources/' + name)
            require(source_data[name] == apk.read(prefix + name), 'Private executed source differs from APK: ' + name)
        for entry in apk.namelist():
            if not entry.startswith('lib/arm64-v8a/') or entry.endswith('/'):
                continue
            name = entry[len('lib/arm64-v8a/'):]
            require(re.fullmatch(r'lib[A-Za-z0-9_.-]+\.so', name), 'Invalid packaged library name')
            digest = sha(apk.read(entry))
            require(remote_hash(native_dir + '/' + name) == digest, 'Installed native library differs: ' + name)
            libraries[name] = digest
    for name in (*PROGRAMS.values(), 'libfoldgpt_python.so', 'libproot.so', 'libproot-loader.so', 'libproot-loader32.so', 'libtalloc.so'):
        require(name in libraries, 'Missing actual composite/guest program')
    matrix = strict_json(matrix_data)
    require(matrix['uid'] == uid, 'Composite matrix belongs to another UID')
    coverage = inspect_matrix(matrix, output_data.decode('utf-8'), source_data[SUITE],
        source_data['tools/executor/test_native_processes_live.py'], absolute + '/cases', native_dir)
    require(all(matrix['artifacts'][key]['sha256'] == libraries[name] for key, name in PROGRAMS.items()),
        'Matrix programs differ from installed APK')
    report = None
    if matrix['passed']:
        require(all(optional.values()), 'Passing suite lacks wrapper report or Android completion')
        report = strict_json(optional_data['report.json'])
        require(report.get('schema') == 'foldgpt.native-executor-android.v1' and report.get('status') == 'PASS'
            and report['uid'] == uid and report['testsRun'] == report['retainedCases'] == 9
            and report['nativeProcessProfile'] == 'managed-process-v2', 'Incomplete composite wrapper PASS')
        require(optional_data['android-completion.txt'] == f'PASS uid={uid}\n'.encode(), 'Invalid Android completion')
        require(report['suiteSha256'] == sha(source_data[SUITE]) and report['matrixSha256'] == sha(matrix_data)
            and report['programsSha256'] == {key: libraries[name] for key, name in PROGRAMS.items()},
            'Wrapper does not bind its actual programs/suite/matrix')
        require(report['addressSpaceBytes'] == (33 + 1) << 28, 'Scudo virtual address contract differs')
        require(report['observationBefore'] == context_before, 'Preserved before-context differs')
        for field in ('observationBefore', 'observationAfter'):
            lifecycle.inspect_context(report[field], uid, native_dir)
        require(re.search(r'^\{"status": "PASS", "testsRun": 9, "retainedCases": 9\}$', output_data.decode('utf-8'), re.M),
            'Missing real wrapper stdout completion')
    else:
        require(not any(optional.values()), 'Failed composite suite has PASS artifacts')
        require('RuntimeError: The actual Android composite transport suite failed' in output_data.decode('utf-8'),
            'Failed suite lacks actual wrapper error')
    # Enumerate the fixed directory independently. Report paths never become
    # targets until matched to this inventory and the exact fcomp basename.
    names = sorted(shell('ls', '-A', remote + '/cases').decode().splitlines())
    require(len(names) == 9 and all(re.fullmatch(r'fcomp-[a-z0-9_]+', name) for name in names)
        and names == sorted(item['caseName'] for item in coverage['caseCoverage'].values()),
        'Physical retained case inventory differs from completed suite')
    cases = {}
    for record in matrix['observations']:
        name = PurePosixPath(record['caseDirectory']).name
        relative = 'cases/' + name
        for directory in ('', '/work', '/work/private', '/ipc', '/home', '/tmp', '/shm'):
            metadata(remote + '/' + relative + directory, directory=True)
        value = read_fixed(relative + '/work/value')
        private = read_fixed(relative + '/work/private/secret')
        info = file_metadata[relative + '/work/value']
        require(value == lifecycle.decode_chunk(record['finalValueBase64']) and private == b'private-intact'
            and info['device'] == record['valueDevice'] and info['inode'] == record['valueInode'],
            'Retained physical bytes or inode/device contradict executed observation')
        number = int(record['test'].split('.test_')[1][:2])
        marker = relative + '/ipc/process-session.json'
        marker_present = present(marker)
        status = coverage['caseCoverage'][record['test'].removeprefix('__main__.CompositeTransportTests.')]['status']
        if status == 'ok':
            require(marker_present is (number in (7, 8)), 'Physical quarantine marker lifetime differs')
        marker_value = strict_json(read_fixed(marker)) if marker_present else None
        require(not present(relative + '/ipc/exec.sock'), 'Completed fixture left a live or stale endpoint')
        if marker_value is not None:
            work_info = directory_metadata[remote + '/' + relative + '/work']
            require(type(marker_value) is dict and set(marker_value) == {'version', 'brokerPid', 'uid', 'workspaceDevice', 'workspaceInode'}
                and marker_value['version'] == 1 and type(marker_value['brokerPid']) is int and marker_value['brokerPid'] > 0
                and marker_value['uid'] == uid and marker_value['workspaceDevice'] == work_info['device']
                and marker_value['workspaceInode'] == work_info['inode'], 'Retained marker lost actual workspace ownership identity')
        physical_names = shell('ls', '-A', remote + '/' + relative).decode().splitlines()
        logs = sorted((name for name in physical_names if re.fullmatch(r'broker-[0-9]+\.stderr', name)),
            key=lambda name: int(name.split('-')[1].split('.')[0]), reverse=True)
        require(set(physical_names) == {'work', 'ipc', 'home', 'tmp', 'shm', *logs},
            'Unexpected retained case artifact')
        physical_logs = [read_fixed(relative + '/' + log) for log in logs]
        recorded_logs = [lifecycle.decode_chunk(event['brokerStderrBase64']) for event in record['events']
            if 'brokerStderrBase64' in event]
        require(physical_logs == recorded_logs, 'Physical broker diagnostics contradict recorded stderr')
        cases[name] = {'valueSha256': sha(value), 'privateSha256': sha(private), 'device': info['device'],
            'inode': info['inode'], 'marker': marker_value}
    for name, info in file_metadata.items():
        require(metadata(remote + '/' + name) == {key: value for key, value in info.items() if key != 'sha256'}
            and remote_hash(remote + '/' + name) == info['sha256'], 'Evidence drifted during collection')
    for target, info in list(directory_metadata.items()):
        require(metadata(target, directory=True) == info, 'Private directory drifted during collection')
    require(sorted(shell('ls', '-A', remote + '/cases').decode().splitlines()) == names,
        'Case directory inventory changed during collection')
    require({name: present(name) for name in optional} == optional, 'Completion artifacts changed during collection')
    for name, digest in libraries.items():
        require(remote_hash(native_dir + '/' + name) == digest, 'Installed library changed during collection')
    after = installed_apk()
    require(before == after and sha(args.apk.read_bytes()) == apk_sha, 'APK changed during collection')
    require(Path(__file__).read_bytes() == collector_source and SHARED.read_bytes() == shared_source,
        'Independent collector source changed during collection')
    result = {'schema': 'foldgpt.native-executor-independent.v1', 'status': 'PASS' if matrix['passed'] else 'OBSERVED_FAILURE',
        'fixture': args.fixture, 'collectedAtUtc': datetime.now(timezone.utc).isoformat(), 'uid': uid,
        'apkSha256': apk_sha, 'installedApkBefore': before, 'installedApkAfter': after,
        'optionalArtifactsPresent': optional, 'librariesSha256': libraries,
        'privateSourcesSha256': {name: sha(data) for name, data in source_data.items()},
        'coverage': coverage, 'retainedCases': cases,
        'nativeContext': {'observationBefore': context_before, 'observationAfter': report['observationAfter'] if report else None},
        'fixtureFiles': file_metadata, 'collectorSha256': sha(collector_source), 'sharedCollectorSha256': sha(shared_source),
        'evidenceSha256': {path.relative_to(args.output).as_posix(): sha(path.read_bytes())
            for path in args.output.rglob('*') if path.is_file()},
        'scope': 'Fixed real GNU/PRoot bridge, AF_UNIX native Bionic composite and retained private case bytes. '
            'Source/APK/program hashes, transcript correlations and final physical inode/bytes are independently checked. '
            'Historical process liveness, timing, locks and proc snapshots remain recorded fixture observations. '
            'Guest runtime libraries beyond the APK program closure are not independently hashed. '
            'No normal Desktop environment, arbitrary command sandbox or model routing is qualified.'}
    (args.output / 'independent-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'fixture', 'apkSha256', 'optionalArtifactsPresent', 'coverage')}, indent=2))


if __name__ == '__main__':
    main()
