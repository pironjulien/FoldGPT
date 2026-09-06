"""Read-only independent collection of a fixed completed Android lifecycle probe.

Targets derive from a validated pr-* fixture and Package Manager, never reports.
Failure evidence is preserved without inventing PASS/completion artifacts. No
fixture execution, installation, model request, account access or signaling.
"""
import argparse
import ast
import base64
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import zipfile

SOURCES = ('tools/executor/exec_server.py', 'tools/executor/native_files.py',
    'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
    'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
    'tools/executor/native_processes.py', 'tools/executor/test_native_processes_live.py',
    'tools/executor/native_processes_android_fixture.py')
SUITE = 'tools/executor/test_native_processes_live.py'
WRAPPER = 'tools/executor/native_processes_android_fixture.py'
METHODS = {'process/start', 'process/read', 'process/write', 'process/signal', 'process/terminate'}
PASS_COUNTS = {1: 3, 2: 12, 3: 6, 4: 10, 5: 5, 6: 3, 7: 12, 8: 10, 9: 3,
    10: 3, 11: 4, 12: 6, 13: 3, 14: 1, 15: 6, 16: 6, 17: 4, 18: 3, 19: 3, 20: 1}
NATIVE_COUNTS = {1: 1, 2: 1, 3: 1, 4: 2, 5: 1, 6: 1, 7: 4, 8: 2, 9: 0,
    10: 1, 11: 0, 12: 1, 13: 1, 14: 0, 15: 2, 16: 1, 17: 1, 18: 0, 19: 0, 20: 0}
UID_FIELDS = {'uidTasksObserved', 'uidTaskBudget', 'uidNprocLimit', 'inheritedNprocSoft', 'inheritedNprocHard'}
NATIVE_FD_ABI = {'MFD_CLOEXEC': 1, 'MFD_ALLOW_SEALING': 2, 'F_ADD_SEALS': 1033,
    'F_GET_SEALS': 1034, 'F_SEAL_SEAL': 1, 'F_SEAL_SHRINK': 2, 'F_SEAL_GROW': 4, 'F_SEAL_WRITE': 8}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs,
        parse_constant=lambda value: require(False, 'Nonfinite JSON number'))


def inspect_context(observed, uid, native_dir):
    require(observed['uid'] == observed['gid'] == uid and observed['machine'] == 'aarch64'
        and observed['status']['Uid'].split() == observed['status']['Gid'].split() == [str(uid)] * 4
        and observed['status']['Seccomp'] == '2' and observed['status']['TracerPid'] == '0'
        and int(observed['status']['CapEff'], 16) == int(observed['status']['CapPrm'], 16) == 0
        and observed['securityContext'].startswith('u:r:untrusted_app')
        and observed['executable'] == native_dir + '/libfoldgpt_python.so', 'Native wrapper context/APK differs')
    require(type(observed['mappedFiles']) is list and
        not any('fake_userns' in target or 'libproot' in target for target in observed['mappedFiles']),
        'Native wrapper used guest compatibility layer')


def decode_chunk(value):
    require(type(value) is str and len(value) <= 2 * 1024 * 1024, 'Invalid or unbounded Base64 chunk')
    data = base64.b64decode(value, validate=True)
    require(base64.b64encode(data).decode('ascii') == value, 'Noncanonical Base64 bytes')
    return data


def inspect_read(value):
    require(set(value) == {'chunks', 'nextSeq', 'exited', 'exitCode', 'closed', 'failure', 'sandboxDenied'}
        and all(type(value[key]) is bool for key in ('exited', 'closed', 'sandboxDenied'))
        and type(value['nextSeq']) is int and value['nextSeq'] >= 1
        and (value['exitCode'] is None or type(value['exitCode']) is int and 0 <= value['exitCode'] <= 255)
        and (value['failure'] is None or type(value['failure']) is str)
        and type(value['chunks']) is list and len(value['chunks']) <= 50000, 'Malformed process/read response')
    require(not value['sandboxDenied'] and (not value['closed'] or value['exited'])
        and (value['exitCode'] is not None) == value['exited'], 'Invented process state or sandbox denial')
    previous = 0
    byte_count = 0
    for chunk in value['chunks']:
        require(set(chunk) == {'seq', 'stream', 'chunk'} and type(chunk['seq']) is int
            and previous < chunk['seq'] < value['nextSeq'] and chunk['stream'] in ('stdout', 'stderr'),
            'Malformed or reordered read chunk')
        previous = chunk['seq']
        byte_count += len(decode_chunk(chunk['chunk']))
    require(byte_count <= 1024 * 1024, 'Retained read exceeds the official 1 MiB history')


def fixture_context(access='write'):
    return {'permissions': {'type': 'managed', 'file_system': {'type': 'restricted', 'entries': [
        {'path': {'type': 'path', 'path': 'file:///workspace'}, 'access': access},
        {'path': {'type': 'path', 'path': 'file:///workspace/private'}, 'access': 'deny'}]}, 'network': 'restricted'},
        'cwd': 'file:///workspace', 'workspaceRoots': ['file:///workspace'], 'useLegacyLandlock': False,
        'windowsSandboxLevel': 'disabled', 'windowsSandboxPrivateDesktop': False}


def expected_starts(number):
    def start(name='process', args=('stdio',), session='session-one', error=False, **extra):
        return (session, {'processId': name, 'argv': ['native-fixture', *args], 'cwd': 'file:///workspace',
            'env': {}, 'tty': False, 'sandbox': fixture_context(), **extra}, error)
    plans = {
        1: [start()], 2: [start(args=('echo', '5'), pipeStdin=True)], 3: [start(args=('eof',))],
        4: [start('interrupt', ('interrupt',)), start('terminate', ('sleep',))], 5: [start()],
        6: [start(args=('env',), arg0='actual-arg0', env={'EXACT': '\u00e9=ok', 'node_repl_auth_token': 'must-not-inherit',
            'OPENAI_IDENTITY_TOKEN_FILE': 'must-not-inherit', 'CODEX_EXEC_SERVER_EXIT_ON_STDIN_CLOSE': '1'})],
        7: [start(str(index), ('open', '0', 'value', '514', '0' if access == 'write' else '13', 'real-change'),
            sandbox=fixture_context(access)) for index, access in enumerate(('write', 'read', 'deny', 'write'))],
        8: [start('same', ('sleep',)), start('same', ('sleep',), error=True), start('same', ('eof',), session='other')],
        9: [start('holding', ('sleep',)), start('waiting', ('eof',), error=True)],
        10: [start(args=('fork-exit',))],
        11: [start(error=True, **extra) for extra in ({'tty': True}, {'envPolicy': {'inherit': 'none'}},
            {'managedNetwork': {}}, {'sandbox': None})],
        12: [start(args=('sleep',), pipeStdin=True)], 13: [start(args=('output',))], 14: [start(error=True)],
        15: [start('timeout', ('sleep',)), start('limited', ('output',))],
        16: [start(args=('sleep',), pipeStdin=True)], 17: [start(args=('sleep',))],
        18: [start(args=('sleep',)), start('refused-after-loss', ('eof',), error=True)],
        19: [start(args=('sleep',))], 20: [],
    }
    return plans[number]


def stream_bytes(chunks, stream='stdout'):
    return b''.join(decode_chunk(item['chunk']) for item in chunks if item['stream'] == stream)


def inspect_native_groups(entries):
    """Use cumulative notification prefixes once; never sum repeated snapshots."""
    completions, notifications = [], []
    for index, entry in enumerate(entries):
        if 'nativeResult' not in entry:
            continue
        require(index > 0 and entries[index - 1].get('method') == 'process/read'
            and 'result' in entries[index - 1] and set(entries[index - 1]['params']) == {'processId'},
            'Native completion is not bound to its preceding full process/read')
        previous = entries[index - 1]
        require(entry['notifications'][:len(notifications)] == notifications,
            'Cumulative notification history changed between real completions')
        notifications = entry['notifications']
        completions.append((entry, previous))
    generations, active = [], {}
    for event in notifications:
        require(type(event) is dict and set(event) == {'method', 'params'} and type(event['params']) is dict,
            'Malformed process notification')
        method, params = event['method'], event['params']
        require(method in ('process/output', 'process/exited', 'process/closed'), 'Unexpected notification method')
        fields = {'processId', 'seq'} | ({'stream', 'chunk'} if method == 'process/output'
            else {'exitCode', 'sandboxDenied'} if method == 'process/exited' else set())
        require(set(params) == fields and type(params['processId']) is str and type(params['seq']) is int,
            'Invalid official process notification fields')
        process_id = params['processId']
        if process_id not in active or active[process_id]['closed']:
            require(params['seq'] == 1, 'Notification sequence did not begin at one')
            group = {'processId': process_id, 'events': [], 'chunks': [], 'closed': False, 'exitCode': None}
            active[process_id] = group
            generations.append(group)
        group = active[process_id]
        require(params['seq'] == len(group['events']) + 1, 'Process notification sequence has a gap or duplicate')
        group['events'].append(event)
        if method == 'process/output':
            require(params['stream'] in ('stdout', 'stderr'), 'Unknown output stream')
            require(0 < len(decode_chunk(params['chunk'])) <= 65536, 'Invalid native output chunk size')
            group['chunks'].append({key: params[key] for key in ('seq', 'stream', 'chunk')})
        elif method == 'process/exited':
            require(group['exitCode'] is None and type(params['exitCode']) is int and 0 <= params['exitCode'] <= 255
                and params['sandboxDenied'] is False, 'Invalid or duplicate process exit notification')
            group['exitCode'] = params['exitCode']
        else:
            require(group['exitCode'] is not None, 'Closed notification precedes actual exit')
            group['closed'] = True
    require(len(generations) == len(completions), 'Native completions and unique notification generations differ')
    native_bytes = 0
    records = []
    for (entry, preceding), group in zip(completions, generations):
        started, final, read = entry['nativeStarted'], entry['nativeResult'], preceding['result']
        require(set(started) == {'type', 'pid', 'profile'} | UID_FIELDS
            and started['type'] == 'started' and started['profile'] == 'managed-process-v1'
            and type(started['pid']) is int and started['pid'] > 0, 'Missing actual native exec event')
        require(all(type(started[key]) is int and 0 <= started[key] <= (1 << 64) - 1 for key in UID_FIELDS)
            and started['uidTasksObserved'] > 0 and started['uidTaskBudget'] == 128
            and started['uidTasksObserved'] + started['uidTaskBudget'] <= (1 << 64) - 1
            and started['uidNprocLimit'] == min(started['uidTasksObserved'] + started['uidTaskBudget'],
                started['inheritedNprocSoft'], started['inheritedNprocHard'])
            and started['uidNprocLimit'] > started['uidTasksObserved'], 'Incorrect native UID task accounting')
        require(set(final) == {'type', 'outcome', 'exitCode', 'signal', 'cleanupComplete', 'started', 'grants',
            'denials', 'stdoutBytes', 'stderrBytes', 'stage', 'errno'} and final['type'] == 'result'
            and final['started'] is True and final['cleanupComplete'] is True
            and final['outcome'] in ('exited', 'cancelled', 'timeout', 'output_limit')
            and all(type(final[key]) is int for key in ('exitCode', 'signal', 'grants', 'denials', 'stdoutBytes',
                'stderrBytes', 'stage', 'errno')) and final['stage'] == final['errno'] == 0
            and all(final[key] >= 0 for key in ('signal', 'grants', 'denials', 'stdoutBytes', 'stderrBytes')),
            'Incomplete or malformed actual native cleanup result')
        require((final['signal'] == 0 and 0 <= final['exitCode'] <= 255)
            or (0 < final['signal'] < 128 and final['exitCode'] == -1), 'Inconsistent native wait status')
        exit_code = 128 + final['signal'] if final['signal'] else final['exitCode']
        require(read['exited'] and read['closed'] and group['closed'] and read['exitCode'] == group['exitCode'] == exit_code
            and preceding['params']['processId'] == group['processId']
            and read['nextSeq'] == len(group['events']) + 1, 'Native wait/notification/read state differs')
        require(read['failure'] == (f"Native process ended with {final['outcome']}"
            if final['outcome'] in ('timeout', 'output_limit') else None), 'Native failure was hidden or invented')
        chunks = group['chunks']
        if read['chunks']:
            require(chunks[-len(read['chunks']):] == read['chunks'], 'Retained output is not the actual notification suffix')
        else:
            require(not chunks, 'All output disappeared from retained history')
        stdout, stderr = stream_bytes(chunks), stream_bytes(chunks, 'stderr')
        require(final['stdoutBytes'] == len(stdout) and final['stderrBytes'] == len(stderr),
            'Native counters differ from unique actual output bytes')
        native_bytes += len(stdout) + len(stderr)
        records.append({'native': final, 'stdout': stdout, 'stderr': stderr, 'read': read,
            'session': preceding['session'], 'processId': preceding['params']['processId']})
    return records, native_bytes, len(notifications)


def inspect_passing_case(entries, number, uid):
    actual_starts = [entry for entry in entries if entry.get('method') == 'process/start']
    plans = expected_starts(number)
    require(len(actual_starts) == len(plans), 'Missing or extra actual process/start')
    for entry, (session, params, error) in zip(actual_starts, plans):
        require(entry['session'] == session and entry['params'] == params and ('error' in entry) is error,
            'Actual launch input/session/admission differs from reviewed case')
    records, native_bytes, notifications = inspect_native_groups(entries)
    require(len(records) == NATIVE_COUNTS[number], 'Wrong actual native completion count')
    if records:
        require([(record['session'], record['processId']) for record in records]
            == [(session, params['processId']) for session, params, error in plans if not error],
            'Native completions belong to different launch sessions or caller process ids')
    actual_errors = [entry['error']['error'] for entry in entries if 'error' in entry]
    expected_errors = {
        3: [(-32602, 'writeId must not be empty')],
        8: [(-32600, 'Process id already exists in this session')],
        9: [(-32603, 'Native process supervision failed')],
        11: [(-32602, 'TTY, shell snapshots and managed networking are outside the static native profile'),
            (-32602, 'The static native profile currently accepts exact explicit environments only'),
            (-32602, 'TTY, shell snapshots and managed networking are outside the static native profile'),
            (-32602, 'Native launch requires its complete matching portable sandbox context')],
        12: [(-32603, 'Failed to write to process stdin')],
        14: [(-32603, 'Native process failed before verified exec')],
        18: [(-32603, 'Native workspace cleanup is unknown; subsequent acquisition is refused')],
    }.get(number, [])
    require(actual_errors == [{'code': code, 'message': message} for code, message in expected_errors],
        'Actual admission, cancellation, write or quarantine errors differ')
    writes = [entry for entry in entries if entry.get('method') == 'process/write']
    def write(write_id, data, status, process='process', session='session-one'):
        return (session, {'processId': process, 'writeId': write_id,
            'chunk': base64.b64encode(data).decode('ascii')}, status)
    expected_writes = {2: [write('exactly-once', b'\0\xffABC', 'accepted')] * 9,
        3: [write('a', b'', 'unknownProcess', process='unknown'), write('', b'', 'error', process='unknown'),
            write('b', b'', 'stdinClosed')], 8: [write('x', b'', 'starting', process='same', session='other')],
        12: [write('filled', b'x' * (1024 * 1024), 'accepted'), write('waiting', b'a', 'error')],
        16: [write('one', b'a' * (1024 * 1024), 'accepted')] * 2}.get(number, [])
    require(len(writes) == len(expected_writes), 'Write-id/backpressure call coverage differs')
    for entry, (session, params, status) in zip(writes, expected_writes):
        require(entry['session'] == session and entry['params'] == params
            and (('error' in entry) if status == 'error' else entry.get('result') == {'status': status}),
            'Actual stdin bytes/write-id/status differ')
    signals = [entry for entry in entries if entry.get('method') == 'process/signal']
    require(len(signals) == (1 if number == 4 else 0), 'Signal coverage differs')
    if signals:
        require(signals[0]['params'] == {'processId': 'interrupt', 'signal': 'interrupt'}
            and signals[0]['result'] == {}, 'Real interrupt request differs')
    terminated = [entry for entry in entries if entry.get('method') == 'process/terminate']
    expected_terminated = {4: [('session-one', 'terminate', True), ('session-one', 'terminate', False)],
        8: [('other', 'same', False), ('session-one', 'same', True)], 9: [('session-one', 'waiting', True)],
        12: [('session-one', 'process', True)], 16: [('session-one', 'process', True)],
        17: [('session-one', 'process', True)], 19: [('session-one', 'process', False)]}.get(number, [])
    require([(item['session'], item['params']['processId'], item['result']['running']) for item in terminated]
        == expected_terminated, 'Real terminate/session semantics differ')
    for index, record in enumerate(records):
        final, stdout, stderr, read = (record[key] for key in ('native', 'stdout', 'stderr', 'read'))
        expected_outcome = 'cancelled' if number in (12, 16, 17) or number in (4, 8) and index == (1 if number == 4 else 0) else (
            ('timeout', 'output_limit')[index] if number == 15 else 'exited')
        expected_exit = 137 if expected_outcome != 'exited' else {1: 17, 4: 42, 5: 17, 10: 19}.get(number, 0)
        require(final['outcome'] == expected_outcome and read['exitCode'] == expected_exit
            and (final['signal'] == 9 if expected_outcome != 'exited' else final['signal'] == 0),
            'Genuine command exit, interruption or native failure differs')
        expected_stderr = b'\xfe\0ERR' if number in (1, 5) else b''
        require(stderr == expected_stderr, 'Actual stderr bytes differ')
        expected_stdout = {1: b'\0\xff\x80OUT', 2: b'\0\xffABC', 3: b'EOF', 5: b'\0\xff\x80OUT',
            6: 'ARG0=actual-arg0\nEXACT=\u00e9=ok\n'.encode()}.get(number, b'')
        if number == 4 and index == 0:
            expected_stdout = b'READYINTERRUPTED'
            require(b'READY' in stdout and b'INTERRUPTED' in stdout, 'Actual interrupt output absent')
        elif number == 7:
            expected_stdout = b'DENIED:13\n' if index in (1, 2) else b''
        elif number == 8 and index == 1:
            expected_stdout = b'EOF'
        elif number == 10:
            require(re.fullmatch(rb'CHILD:[1-9][0-9]*\n', stdout), 'No real forked child output')
        elif number == 13:
            require(len(stdout) == 2 * 1024 * 1024 and stdout == b'\xa5' * len(stdout)
                and read['chunks'] and read['chunks'][0]['seq'] > 1 and stream_bytes(read['chunks'])
                == b'\xa5' * len(stream_bytes(read['chunks'])), 'Actual output retention evidence differs')
        elif number == 15 and index == 1:
            expected_stdout = b'\xa5' * 32768
        if number not in (10, 13) and not (number == 4 and index == 0):
            require(stdout == expected_stdout, 'Actual native stdout bytes differ')
        # Native denials include acquisitions rejected before portable policy
        # dispatch. The lifecycle trace has no pathname decision list, so it
        # cannot attribute all of them to the explicit testcase request. Keep
        # their actual counters and require the demonstrated minimum only.
        require(final['grants'] == (1 if number == 7 and index in (0, 3) else 0)
            and final['denials'] >= (1 if number == 7 and index in (1, 2) else 0), 'Actual policy grant/denial counts differ')
    reads = [entry for entry in entries if entry.get('method') == 'process/read']
    if number == 4:
        polls = [entry for entry in reads if entry['params'].get('waitMs') == 100]
        require(1 <= len(polls) <= 30 and len(reads) == len(polls) + 2
            and all(entry['params'] == {'processId': 'interrupt', 'waitMs': 100} for entry in polls)
            and b'READY' in stream_bytes(polls[-1]['result']['chunks']),
            'Real interrupt readiness was not observed')
    elif number == 5:
        require(len(reads) == 3, 'Cursor read coverage differs')
        full, limited, rest = [entry['result'] for entry in reads]
        require(reads[1]['params'] == {'processId': 'process', 'maxBytes': 0} and len(limited['chunks']) == 1
            and limited['chunks'] == full['chunks'][:1] and limited['nextSeq'] == limited['chunks'][0]['seq'] + 1
            and reads[2]['params'] == {'processId': 'process', 'afterSeq': limited['chunks'][0]['seq']}
            and rest['chunks'] == full['chunks'][1:] and rest['nextSeq'] == full['nextSeq'], 'Whole-chunk cursor semantics differ')
    elif number in (18, 19):
        require(len(reads) == 1 and reads[0]['result'] == {'chunks': [], 'nextSeq': 1, 'exited': False,
            'exitCode': None, 'closed': False, 'failure': 'Native descendant cleanup is unknown; workspace remains quarantined',
            'sandboxDenied': False}, 'Supervisor loss invented output, exit or cleanup proof')
    if number == 20:
        value = entries[0]
        require(set(value) == {'test', 'memfdRoute', 'sealRoute', 'actualSeals', 'actualSize', 'pythonMemfdExposed',
            'pythonConstants', 'verifiedNativeAbi', 'writeShrinkGrowResealDenied'}
            and value['memfdRoute'] == 'libc.memfd_create' and value['sealRoute'] == 'libc.fcntl'
            and type(value['actualSeals']) is int and value['actualSeals'] == 15
            and type(value['actualSize']) is int and value['actualSize'] == len(b'EXPLICIT=value\0')
            and type(value['pythonMemfdExposed']) is bool and value['verifiedNativeAbi'] == NATIVE_FD_ABI
            and value['writeShrinkGrowResealDenied'] is True and set(value['pythonConstants']) == set(NATIVE_FD_ABI)
            and all(item is None or type(item) is int and item == NATIVE_FD_ABI[key]
                for key, item in value['pythonConstants'].items()), 'Real libc memfd/seal/denial evidence differs')
    return {'uniqueNativeOutputBytes': native_bytes, 'nativeCompletions': len(records),
        'uniqueNotifications': notifications,
        'nativeGrants': sum(record['native']['grants'] for record in records),
        'nativeDenials': sum(record['native']['denials'] for record in records)}


def inspect_matrix(matrix, output, suite_source, absolute):
    require(set(matrix) == {'schema', 'uid', 'successful', 'observations'}
        and matrix['schema'] == 'foldgpt.native-process-lifecycle.v1'
        and type(matrix['successful']) is bool and type(matrix['uid']) is int and matrix['uid'] > 0,
        'Wrong lifecycle conformance schema or native UID')
    classes = [node for node in ast.parse(suite_source.decode('utf-8')).body
        if isinstance(node, ast.ClassDef) and node.name == 'NativeProcessTests']
    require(len(classes) == 1, 'Missing packaged lifecycle test class')
    tests = sorted(node.name for node in classes[0].body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith('test_'))
    require(len(tests) in (19, 20) and [int(name[5:7]) for name in tests] == list(range(1, len(tests) + 1)),
        'Packaged lifecycle suite changed and needs independent review')
    statuses = re.findall(r'^(test_[a-zA-Z0-9_]+) \(__main__\.NativeProcessTests\.\1\) \.\.\. (ok|FAIL|ERROR|skipped[^\n]*)$', output, re.M)
    require([name for name, _ in statuses] == tests, 'Unittest output does not cover the packaged suite exactly once')
    runs = re.findall(r'^Ran ([0-9]+) tests in [0-9.]+s$', output, re.M)
    require(runs == [str(len(tests))], 'Missing or inconsistent unittest completion count')
    failures = [name for name, status in statuses if status != 'ok']
    require(matrix['successful'] is (not failures), 'Unittest status contradicts lifecycle matrix')
    require(bool(re.search(r'^OK$', output, re.M)) if not failures else bool(re.search(r'^FAILED \(', output, re.M)),
        'Missing successful/failed unittest terminator')
    observations = matrix['observations']
    require(type(observations) is list and len(observations) <= 1000, 'Unbounded lifecycle observations')
    counts, methods, errors, grouped = Counter(), Counter(), [], {name: [] for name in tests}
    previous_test = ''
    for entry in observations:
        name = entry['test'].removeprefix('__main__.NativeProcessTests.')
        require(entry['test'] == '__main__.NativeProcessTests.' + name and name in tests and name >= previous_test,
            'Unknown or reordered observed test')
        previous_test = name
        counts[name] += 1
        grouped[name].append(entry)
        if 'method' in entry:
            require(set(entry) in ({'test', 'method', 'session', 'params', 'result'},
                {'test', 'method', 'session', 'params', 'error'}) and entry['method'] in METHODS
                and entry['session'] in ('session-one', 'other') and type(entry['params']) is dict,
                'Invalid recorded backend call envelope')
            methods[entry['method']] += 1
            params = entry['params']
            require(type(params.get('processId')) is str and bool(params['processId'])
                and '\0' not in params['processId'], 'Invalid lifecycle process id')
            if 'error' in entry:
                error = entry['error']
                require(set(error) == {'id', 'error'} and type(error['id']) is int and error['id'] > 0
                    and type(error['error']) is dict and set(error['error']) == {'code', 'message'}
                    and type(error['error']['code']) is int and type(error['error']['message']) is str,
                    'Malformed actual RPC error envelope')
                errors.append({'test': name, 'method': entry['method'], **error})
            else:
                require(type(entry['result']) is dict, 'Invalid backend response')
                value = entry['result']
                if entry['method'] == 'process/read':
                    require(set(params) <= {'processId', 'afterSeq', 'maxBytes', 'waitMs'}
                        and all(type(value) is int and value >= 0 for key, value in params.items() if key != 'processId'),
                        'Malformed read cursor/budget/wait input')
                    inspect_read(value)
                elif entry['method'] == 'process/start':
                    require(value == {'processId': params['processId'], 'sandboxType': 'linuxSeccomp'},
                        'Native start invented an unsupported sandbox response')
                elif entry['method'] == 'process/write':
                    require(set(value) == {'status'} and value['status'] in ('accepted', 'unknownProcess', 'starting', 'stdinClosed'),
                        'Unknown native stdin result')
                elif entry['method'] == 'process/terminate':
                    require(set(params) == {'processId'} and set(value) == {'running'} and type(value['running']) is bool,
                        'Malformed terminate response')
                else:
                    require(value == {}, 'Invalid process/signal response')
        elif 'memfdRoute' in entry:
            require(name.startswith('test_20_'), 'Memfd evidence assigned to another testcase')
        else:
            require(set(entry) == {'test', 'nativeStarted', 'nativeResult', 'notifications'}, 'Invalid native completion envelope')
    native_summary = {'uniqueNativeOutputBytes': 0, 'nativeCompletions': 0, 'uniqueNotifications': 0,
        'nativeGrants': 0, 'nativeDenials': 0}
    for name, status in statuses:
        number = int(name[5:7])
        require(counts[name] <= PASS_COUNTS[number] + (29 if number == 4 else 0), 'Unexpected extra lifecycle observations')
        if status == 'ok':
            require(PASS_COUNTS[number] <= counts[name] <= PASS_COUNTS[number] + (29 if number == 4 else 0),
                'Passing testcase lacks reviewed lifecycle observation coverage')
            inspected = inspect_passing_case(grouped[name], number, matrix['uid'])
            for key in native_summary:
                native_summary[key] += inspected[key]
    return {'testsRun': len(tests), 'passed': len(tests) - len(failures), 'failedTests': failures,
        'observations': len(observations), 'methodCounts': dict(methods),
        **native_summary,
        'caseCoverage': {name: {'status': status, 'observations': counts[name],
            'expectedMinimumOnPass': PASS_COUNTS[int(name[5:7])], 'expectedMaximumOnPass':
            PASS_COUNTS[int(name[5:7])] + (29 if name.startswith('test_04_') else 0)} for name, status in statuses},
        'observedRpcErrors': errors, 'missingMemfdCreateErrorObserved':
            "AttributeError: module 'os' has no attribute 'memfd_create'" in output}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('serial', 'fixture'):
        parser.add_argument('--' + name, required=True)
    for name in ('apk', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'pr-[0-9]{1,20}', args.fixture), 'Expected exact Android pr fixture name')
    remote, absolute = 'cache/' + args.fixture, '/data/data/app.foldgpt/cache/' + args.fixture
    adb = ['adb', '-s', args.serial]
    apk_sha = sha(args.apk.read_bytes())
    collector_source = Path(__file__).read_bytes()

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
        require(digest == apk_sha, 'Installed APK differs from the supplied tested APK')
        return {'path': target, 'sha256': digest}

    before = installed_apk()
    native_dir = str(PurePosixPath(before['path']).parent / 'lib/arm64')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'collector-source.py').write_bytes(collector_source)
    uid = int(shell('id', '-u').strip())
    require(uid > 0, 'Expected nonroot Android app UID')
    file_metadata = {}

    def metadata(target, directory=False):
        fields = shell('stat', '-c', '%f %u %g %s %d %i %a %h', target).decode().split()
        require(len(fields) == 8, 'Malformed native file metadata')
        mode = int(fields[0], 16)
        info = dict(zip(('uid', 'gid', 'bytes', 'device', 'inode', 'mode', 'links'),
            [int(value, 8 if index == 6 else 10) for index, value in enumerate(fields[1:], 1)]))
        require((stat.S_ISDIR(mode) if directory else stat.S_ISREG(mode)) and info['uid'] == uid
            and not info['mode'] & 0o077 and (directory or info['links'] == 1), 'Not a private ordinary diagnostic target: ' + target)
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
        require(info['bytes'] <= (64 if relative == 'lifecycle-tests.json' else 8) * 1024 * 1024, 'Diagnostic exceeds collection bound')
        # shell-v2 retains remote exit codes; base64 survives Windows adb CRLF conversion.
        data = base64.b64decode(b''.join(shell('base64', target).splitlines()), validate=True)
        require(len(data) == info['bytes'] and remote_hash(target) == sha(data), 'Diagnostic changed during collection')
        file_metadata[relative] = {**info, 'sha256': sha(data)}
        output = args.output / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return data

    lifecycle_data = read_fixed('lifecycle-tests.json')
    output_data = read_fixed('fixture-output.txt')
    context_before = strict_json(read_fixed('android-context-before.json'))
    inspect_context(context_before, uid, native_dir)
    optional = {name: present(name) for name in ('report.json', 'android-completion.txt')}
    optional_data = {name: read_fixed(name) for name, exists in optional.items() if exists}
    source_data, libraries = {}, {}
    with zipfile.ZipFile(args.apk) as apk:
        require(len(apk.namelist()) == len(set(apk.namelist())), 'Duplicate APK entries')
        prefix = 'assets/process-rpc-probe/'
        require({name[len(prefix):] for name in apk.namelist() if name.startswith(prefix) and not name.endswith('/')} == set(SOURCES),
            'Packaged lifecycle diagnostic source set differs')
        for name in SOURCES:
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
    for name in ('libfoldgpt_python.so', 'libfoldgpt-native-process-runner.so', 'libfoldgpt-native-process-fixture.so', 'libfoldgpt-native-files.so'):
        require(name in libraries, 'Missing executed lifecycle program')
    matrix = strict_json(lifecycle_data)
    require(matrix['uid'] == uid, 'Lifecycle matrix belongs to a different UID')
    coverage = inspect_matrix(matrix, output_data.decode('utf-8'), source_data[SUITE], absolute)
    report = None
    if matrix['successful']:
        require(all(optional.values()), 'Passing suite lacks actual wrapper report or Android completion')
        report = strict_json(optional_data['report.json'])
        require(report.get('schema') == 'foldgpt.native-processes-android.v1' and report.get('status') == 'PASS'
            and report['uid'] == uid and report['observations'] == coverage['observations'], 'Incomplete wrapper PASS report')
        require(optional_data['android-completion.txt'] == f'PASS uid={uid}\n'.encode(), 'Invalid Android completion')
        require(report['runnerSha256'] == libraries['libfoldgpt-native-process-runner.so']
            and report['fixtureSha256'] == libraries['libfoldgpt-native-process-fixture.so']
            and report['filesHelperSha256'] == libraries['libfoldgpt-native-files.so']
            and report['suiteSha256'] == sha(source_data[SUITE]) and report['lifecycleTestsSha256'] == sha(lifecycle_data),
            'Wrapper does not bind the executed programs/suite/lifecycle matrix')
        require(report['addressSpaceBytes'] == (33 + 1) << 28, 'Scudo virtual address contract differs')
        require(report['observationBefore'] == context_before, 'Wrapper before-context differs from preserved context')
        for field in ('observationBefore', 'observationAfter'):
            inspect_context(report[field], uid, native_dir)
        require(re.search(r'^\{"status": "PASS", "observations": ' + str(coverage['observations']) + r'\}$',
            output_data.decode('utf-8'), re.M), 'Missing real wrapper stdout completion')
    else:
        require(not any(optional.values()), 'Failed native suite unexpectedly has PASS artifacts')
        require('RuntimeError: The actual native lifecycle backend suite failed' in output_data.decode('utf-8'),
            'Failed suite lacks the actual wrapper error')
    # The suite removes transient case files in tearDown. Check only the known
    # parent; recorded command paths and process IDs are never collection targets.
    cases_empty = not shell('ls', '-A', remote + '/cases').strip()
    require(cases_empty, 'Completed conformance suite left case workspaces')
    for name, info in file_metadata.items():
        require(metadata(remote + '/' + name) == {key: value for key, value in info.items() if key != 'sha256'}
            and remote_hash(remote + '/' + name) == info['sha256'], 'Evidence drifted during collection')
    require({name: present(name) for name in optional} == optional, 'Optional completion artifacts changed during collection')
    for name, digest in libraries.items():
        require(remote_hash(native_dir + '/' + name) == digest, 'Installed native library changed during collection')
    after = installed_apk()
    require(before == after and sha(args.apk.read_bytes()) == apk_sha, 'APK changed during collection')
    require(Path(__file__).read_bytes() == collector_source, 'Collector source changed during collection')
    result = {'schema': 'foldgpt.native-processes-independent.v1', 'status': 'PASS' if matrix['successful'] else 'OBSERVED_FAILURE',
        'fixture': args.fixture, 'collectedAtUtc': datetime.now(timezone.utc).isoformat(), 'uid': uid,
        'apkSha256': apk_sha, 'installedApkBefore': before, 'installedApkAfter': after,
        'optionalArtifactsPresent': optional, 'librariesSha256': libraries,
        'privateSourcesSha256': {name: sha(data) for name, data in source_data.items()},
        'wrapperSha256': sha(source_data[WRAPPER]), 'coverage': coverage, 'casesDirectoryEmpty': cases_empty,
        'contextEvidenceAvailable': True,
        'nativeContext': {'observationBefore': context_before, 'observationAfter': report['observationAfter'] if report else None},
        'fixtureFiles': file_metadata, 'evidenceSha256': {path.relative_to(args.output).as_posix(): sha(path.read_bytes())
            for path in args.output.rglob('*') if path.is_file()}, 'collectorSha256': sha(collector_source),
        'scope': 'Fixed static lifecycle backend calls and recorded native events. This is direct backend conformance, not stdio RPC transport, normal Desktop or model routing. Removed case bytes, historical timing, process liveness and lock ownership cannot be reconstructed independently. Denial counters do not identify rejected paths. RPC error IDs are envelope-checked only: the fixture records its completion-time sequence, not an independent transport correlation.'}
    (args.output / 'independent-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'fixture', 'apkSha256', 'optionalArtifactsPresent', 'coverage')}, indent=2))


if __name__ == '__main__':
    main()
