"""Read-only independent collection of completed native managed Android probes.

Targets derive only from a validated mg-* fixture and Package Manager. A failed
unittest run is retained as OBSERVED_FAILURE, never promoted to PASS. No account,
model request, fixture execution, installation or process signaling is involved.
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
    'tools/executor/native-managed-test.py', 'tools/executor/native_managed_android_fixture.py')
SUITE = 'tools/executor/native-managed-test.py'
WRAPPER = 'tools/executor/native_managed_android_fixture.py'
# Exact static ARM64 case counts from the reviewed v1 conformance suite. A test
# that fails early may have fewer observations; a passing test may not.
CASE_COUNTS = {1: 1, 2: 7, 3: 6, 4: 3, 5: 8, 6: 5, 7: 1, 8: 2, 9: 1, 10: 3, 11: 1, 12: 1}
UID_CASE_COUNTS = {**CASE_COUNTS, 13: 1, 14: 1, 15: 3, 16: 1, 17: 1}
UID_FIELDS = {'uidTasksObserved', 'uidTaskBudget', 'uidNprocLimit', 'inheritedNprocSoft', 'inheritedNprocHard'}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_number(name):
    match = re.match(r'test_([0-9]{2})_', name)
    require(match is not None, 'Unknown conformance test name')
    return int(match[1])


def expected_args(number):
    def opened(target='value', flags=0, error=0, marker='', kind=0):
        return ['open', str(kind), target, str(flags), str(error), marker]
    return {
        1: [opened()],
        2: [opened(flags=514, marker='first-write'), opened(), opened(flags=1, error=13),
            opened(error=13), opened(flags=1, error=13), opened('private/readable'), opened(flags=513, marker='last-write')],
        3: [opened('private/secret', flags=flags, error=13) for flags in (0, 1, 2)] +
            [opened('private/readable'), opened('private/readable', flags=1, error=13),
             opened('private/secret', flags=513, marker='explicit-write')],
        4: [opened('.git/config', flags=513, error=13), opened('nested/.agents/config', flags=513, error=13),
            opened('.git/config', flags=513, marker='explicit-metadata')],
        5: [value for kind in (0, 1) for value in (opened(kind=kind), opened('private/secret', error=13, kind=kind),
            opened('@absolute-value', kind=kind))] + [opened('@absolute-outside', error=1), opened('../outside', error=1)],
        6: [opened('new', flags=193, marker='created'), opened('new', flags=193, error=17), opened('absent', error=2),
            opened('private/new', flags=65, error=13), opened('.codex', flags=65, error=13)],
        7: [['exit', '17']], 8: [['sleep'], ['sleep']], 9: [['fork']],
        10: [opened(flags=513, marker='must-not-write')] * 3,
        11: [opened(flags=513, error=116)], 12: [opened()],
        13: [['resources']], 14: [['isolation']],
        15: [opened(flags=524288), opened(flags=2048), opened(flags=1025)],
        16: [opened()], 17: [opened(kind=1)],
    }[number]


def inspect_native(observation, uid_accounting=False):
    """Validate recorded native transport independently of unittest assertions."""
    require(set(observation) == {'test', 'args', 'returncode', 'events', 'stdoutHex', 'stderrHex', 'decisions'},
        'Unexpected native observation envelope')
    for field in ('stdoutHex', 'stderrHex'):
        require(isinstance(observation[field], str) and re.fullmatch(r'(?:[0-9a-f]{2})*', observation[field]),
            'Malformed native byte stream')
    stdout, stderr = (bytes.fromhex(observation[field]) for field in ('stdoutHex', 'stderrHex'))
    events = observation['events']
    require(type(events) is list and len(events) in (1, 2) and events[-1].get('type') == 'result',
        'Incomplete native event sequence')
    final = events[-1]
    require(set(final) == {'type', 'outcome', 'exitCode', 'signal', 'cleanupComplete', 'started', 'grants',
        'denials', 'stdoutBytes', 'stderrBytes', 'stage', 'errno'}, 'Unexpected native result fields')
    require(type(final['started']) is bool and type(final['cleanupComplete']) is bool,
        'Native booleans have the wrong type')
    require(all(type(final[key]) is int for key in ('exitCode', 'signal', 'grants', 'denials', 'stdoutBytes', 'stderrBytes', 'stage', 'errno'))
        and type(observation['returncode']) is int, 'Native integers have the wrong type')
    require(all(final[key] >= 0 for key in ('signal', 'grants', 'denials', 'stdoutBytes', 'stderrBytes', 'stage', 'errno')),
        'Negative native counters')
    require(final['stdoutBytes'] == len(stdout) and final['stderrBytes'] == len(stderr),
        'Native byte counters differ from actual recorded streams')
    require(final['outcome'] in {'exited', 'timeout', 'cancelled', 'broker_error', 'setup_error', 'output_limit', 'cleanup_error'},
        'Unknown native outcome')
    require(observation['returncode'] == (0 if final['outcome'] == 'exited' else 1),
        'Supervisor return code does not describe the native outcome')
    require(final['cleanupComplete'] or final['outcome'] == 'cleanup_error', 'Incomplete cleanup hidden by another outcome')
    if final['started']:
        require(len(events) == 2 and set(events[0]) == {'type', 'pid', 'profile'} | (UID_FIELDS if uid_accounting else set())
            and events[0]['type'] == 'started' and events[0]['profile'] == 'managed-acquisition-v1'
            and type(events[0]['pid']) is int and events[0]['pid'] > 0, 'Missing kernel startup event')
        if uid_accounting:
            started = events[0]
            require(all(type(started[key]) is int and 0 <= started[key] <= (1 << 64) - 1 for key in UID_FIELDS),
                'Malformed UID task accounting')
            require(started['uidTasksObserved'] > 0 and started['uidTaskBudget'] == 128
                and started['uidTasksObserved'] + started['uidTaskBudget'] <= (1 << 64) - 1
                and started['uidNprocLimit'] == min(started['uidTasksObserved'] + started['uidTaskBudget'],
                    started['inheritedNprocSoft'], started['inheritedNprocHard'])
                and started['uidNprocLimit'] > started['uidTasksObserved'], 'UID task ceiling formula or inherited limit differs')
    else:
        require(len(events) == 1 and final['outcome'] in {'setup_error', 'timeout', 'cancelled', 'broker_error', 'cleanup_error'},
            'A nonstarted command was described as executed')
    if final['signal']:
        require(final['exitCode'] == -1, 'Signaled child also has a normal exit code')
    else:
        require(-1 <= final['exitCode'] <= 255, 'Invalid child exit code')
    args = observation['args']
    require(type(args) is list and args and all(isinstance(value, str) and '\0' not in value for value in args), 'Invalid fixture argv')
    for decision in observation['decisions']:
        require(set(decision) == {'path', 'reading', 'writing', 'allowed', 'syscall'}
            and isinstance(decision['path'], str) and decision['path'].startswith('file:///workspace/')
            and all(type(decision[key]) is bool for key in ('reading', 'writing', 'allowed'))
            and type(decision['syscall']) is int and decision['syscall'] in (56, 437), 'Invalid ARM64 policy decision')
    return final, stdout, stderr


def inspect_passing_case(observation, number, index, uid_accounting=False):
    final, stdout, stderr = inspect_native(observation, uid_accounting)
    require(final['cleanupComplete'] and final['started'] and final['stage'] == 0, 'Passing test lacks startup/cleanup proof')
    expected_outcome = ('timeout', 'cancelled')[index] if number == 8 else {9: 'timeout', 10: 'broker_error'}.get(number, 'exited')
    require(final['outcome'] == expected_outcome, 'Passing testcase has the wrong native outcome')
    require(stderr == b'', 'Passing testcase has actual stderr bytes')
    args = observation['args']
    if expected_outcome != 'exited':
        require(final['signal'] == 9 and final['exitCode'] == -1 and final['grants'] == 0,
            'Expected termination did not kill/reap the native command')
        require(final['errno'] == (71 if number == 10 else 0), 'Native termination errno differs')
        if number == 9:
            require(args == ['fork'] and re.fullmatch(rb'CHILD:[1-9][0-9]*\n', stdout), 'No real forked child was recorded')
        else:
            require(stdout == b'', 'Unexpected output in a terminated testcase')
            require(args == ['sleep'] if number == 8 else args == ['open', '0', 'value', '513', '0', 'must-not-write'],
                'Unexpected timeout/corrupt-response fixture arguments')
        return
    require(final['exitCode'] == (17 if number == 7 else 0) and final['signal'] == 0 and final['errno'] == 0,
        'Passing normal command has the wrong child status')
    if number == 7:
        require(args == ['exit', '17'] and stdout == b'' and not observation['decisions'], 'Nonzero command evidence differs')
        return
    if number in (13, 14):
        limit = observation['events'][0]['uidNprocLimit']
        expected = f'{limit}:{limit}\n'.encode() if number == 13 else b'ISOLATION\n'
        require(args == (['resources'] if number == 13 else ['isolation']) and stdout == expected
            and not observation['decisions'] and final['grants'] == 0, 'Actual installed UID limit or isolation output differs')
        return
    require(len(args) == 6 and args[0] == 'open' and args[1] in ('0', '1'), 'Expected native open fixture')
    kind, target, flags, expected_errno, marker = int(args[1]), args[2], int(args[3]), int(args[4]), args[5]
    require(kind == 0 or number in (5, 17), 'openat2 was substituted into another testcase')
    if expected_errno:
        require(stdout == f'DENIED:{expected_errno}\n'.encode() and final['grants'] == 0 and final['denials'] >= 1,
            'Expected denial bytes/grant counters differ')
    elif marker or (flags & 3) == 1:
        require(stdout == b'' and final['grants'] == 1, 'Expected real write grant is absent')
    else:
        expected = b'narrower-read' if target == 'private/readable' else b'first-write' if number == 2 else b'first-native-value'
        require(stdout == expected and final['grants'] == 1, 'Native read bytes differ from fixed fixture content')
    decisions = observation['decisions']
    if expected_errno == 1:  # outside-root rejection happens before policy dispatch
        require(not decisions, 'Outside-root path unexpectedly reached the policy resolver')
    else:
        require(len(decisions) == 1 and decisions[0]['syscall'] == (437 if kind else 56), 'Native acquisition syscall coverage differs')
        decision = decisions[0]
        relative = 'value' if target.startswith('/') else target
        require(decision['path'] == 'file:///workspace/' + relative and decision['reading'] is ((flags & 3) != 1)
            and decision['writing'] is bool((flags & 3) != 0 or flags & (64 | 512)), 'Native decision differs from actual open flags/path')
        # Existence/stale-identity checks may refuse after a legitimate policy grant.
        require(decision['allowed'] is (expected_errno not in (13,)), 'Policy refusal/grant differs')


def inspect_matrix(matrix, output, suite_source, absolute):
    require(matrix.get('schema') == 'foldgpt.native-managed-acquisition.v1' and type(matrix.get('successful')) is bool
        and isinstance(matrix.get('platform'), list) and matrix['platform'][0] == 'Linux'
        and matrix['platform'][-1] == 'aarch64', 'Wrong native conformance schema/platform')
    module = ast.parse(suite_source.decode('utf-8'))
    classes = [node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'ManagedKernelTests']
    require(len(classes) == 1, 'Missing packaged conformance test class')
    tests = sorted(node.name for node in classes[0].body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_'))
    numbers = {test_number(name) for name in tests}
    require(numbers in (set(CASE_COUNTS), set(UID_CASE_COUNTS)), 'Conformance suite changed: review observation counts')
    uid_accounting = numbers == set(UID_CASE_COUNTS)
    case_counts = UID_CASE_COUNTS if uid_accounting else CASE_COUNTS
    if uid_accounting:
        budgets = [node.value.value for node in module.body if isinstance(node, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == 'UID_TASK_BUDGET' for target in node.targets)
            and isinstance(node.value, ast.Constant)]
        require(budgets == [128], 'Packaged UID task budget changed: review its contract')
    statuses = re.findall(r'^(test_[a-zA-Z0-9_]+) \(__main__\.ManagedKernelTests\.\1\) \.\.\. (ok|FAIL|ERROR|skipped[^\n]*)$', output, re.M)
    require([name for name, _ in statuses] == tests, 'Unittest output does not cover every packaged testcase exactly once')
    runs = re.findall(r'^Ran ([0-9]+) tests in [0-9.]+s$', output, re.M)
    require(runs == [str(len(tests))], 'Missing or inconsistent unittest completion count')
    status_map = dict(statuses)
    failures = [name for name, status in statuses if status != 'ok']
    require(matrix['successful'] is (not failures), 'Unittest status contradicts kernel-tests.json')
    require(bool(re.search(r'^OK$', output, re.M)) if not failures else bool(re.search(r'^FAILED \(', output, re.M)),
        'Missing successful/failed unittest terminator')
    observations = matrix.get('observations')
    require(type(observations) is list and len(observations) <= sum(case_counts.values()), 'Wrong observation collection')
    counts = Counter()
    failed_observations = []
    previous_test = ''
    for observation in observations:
        name = observation['test'].removeprefix('__main__.ManagedKernelTests.')
        require(observation['test'] == '__main__.ManagedKernelTests.' + name and name in tests and name >= previous_test,
            'Observation belongs to an unknown or reordered testcase')
        previous_test = name
        number = test_number(name)
        index = counts[name]
        counts[name] += 1
        require(counts[name] <= case_counts[number], 'Unexpected extra native command')
        final, stdout, stderr = inspect_native(observation, uid_accounting)
        # Validate recorded absolute fixture paths without ever reading them.
        if observation['args'][0] == 'open' and len(observation['args']) == 6 and observation['args'][2].startswith('/'):
            require(re.fullmatch(re.escape(absolute) + r'/cases/managed-kernel-[A-Za-z0-9_-]+/(workspace/value|outside)', observation['args'][2]),
                'Absolute fixture argument is outside the named diagnostic')
        recorded_args = list(observation['args'])
        if recorded_args[0] == 'open' and len(recorded_args) == 6 and recorded_args[2].startswith('/'):
            recorded_args[2] = '@absolute-value' if recorded_args[2].endswith('/workspace/value') else '@absolute-outside'
        require(recorded_args == expected_args(number)[index], 'Actual native command sequence differs from reviewed coverage')
        if status_map[name] == 'ok':
            inspect_passing_case(observation, number, index, uid_accounting)
        else:
            failed_observations.append({'test': name, 'observationIndex': index, 'outcome': final['outcome'],
                'exitCode': final['exitCode'], 'signal': final['signal'], 'cleanupComplete': final['cleanupComplete'],
                'stdoutHex': stdout.hex(), 'stderrHex': stderr.hex()})
    for name, status in statuses:
        if status == 'ok':
            require(counts[name] == case_counts[test_number(name)], 'Passing testcase is missing native observations')
    return {'testsRun': len(tests), 'passed': len(tests) - len(failures), 'failedTests': failures,
        'observations': len(observations), 'expectedFullObservations': sum(case_counts.values()),
        'uidTaskAccounting': uid_accounting,
        'caseCoverage': {name: {'status': status_map[name], 'observations': counts[name],
            'expectedOnPass': case_counts[test_number(name)]} for name in tests}, 'failedObservations': failed_observations}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('serial', 'fixture'):
        parser.add_argument('--' + name, required=True)
    for name in ('apk', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(re.fullmatch(r'mg-[0-9]{1,20}', args.fixture), 'Expected exact Android mg fixture name')
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
        require(info['bytes'] <= 8 * 1024 * 1024, 'Diagnostic exceeds collection bound')
        # shell-v2 retains remote exit codes; base64 survives Windows adb CRLF conversion.
        data = base64.b64decode(b''.join(shell('base64', target).splitlines()), validate=True)
        require(len(data) == info['bytes'] and remote_hash(target) == sha(data), 'Diagnostic changed during collection')
        file_metadata[relative] = {**info, 'sha256': sha(data)}
        output = args.output / relative
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(data)
        return data

    kernel_data = read_fixed('kernel-tests.json')
    output_data = read_fixed('fixture-output.txt')
    optional = {name: present(name) for name in ('report.json', 'android-completion.txt')}
    optional_data = {name: read_fixed(name) for name, exists in optional.items() if exists}
    source_data, libraries = {}, {}
    with zipfile.ZipFile(args.apk) as apk:
        require(len(apk.namelist()) == len(set(apk.namelist())), 'Duplicate APK entries')
        prefix = 'assets/managed-process-probe/'
        require({name[len(prefix):] for name in apk.namelist() if name.startswith(prefix) and not name.endswith('/')} == set(SOURCES),
            'Packaged managed diagnostic source set differs')
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
    for name in ('libfoldgpt_python.so', 'libfoldgpt-native-managed-runner.so', 'libfoldgpt-native-managed-fixture.so'):
        require(name in libraries, 'Missing executed managed program')
    matrix = json.loads(kernel_data)
    require(matrix['uid'] == uid, 'Kernel matrix belongs to a different UID')
    coverage = inspect_matrix(matrix, output_data.decode('utf-8'), source_data[SUITE], absolute)
    report = None
    if matrix['successful']:
        require(all(optional.values()), 'Passing suite lacks actual wrapper report or Android completion')
        report = json.loads(optional_data['report.json'])
        require(report.get('schema') == 'foldgpt.native-managed-android.v1' and report.get('status') == 'PASS'
            and report['uid'] == uid and report['observations'] == coverage['observations'], 'Incomplete wrapper PASS report')
        require(optional_data['android-completion.txt'] == f'PASS uid={uid}\n'.encode(), 'Invalid Android completion')
        require(report['runnerSha256'] == libraries['libfoldgpt-native-managed-runner.so']
            and report['fixtureSha256'] == libraries['libfoldgpt-native-managed-fixture.so']
            and report['suiteSha256'] == sha(source_data[SUITE]) and report['kernelTestsSha256'] == sha(kernel_data),
            'Wrapper does not bind the executed programs/suite/kernel matrix')
        require(report['addressSpaceBytes'] == (33 + 1) << 28, 'Scudo virtual address contract differs')
        for field in ('observationBefore', 'observationAfter'):
            observed = report[field]
            require(observed['uid'] == observed['gid'] == uid and observed['machine'] == 'aarch64'
                and observed['status']['Uid'].split() == observed['status']['Gid'].split() == [str(uid)] * 4
                and observed['status']['Seccomp'] == '2' and observed['status']['TracerPid'] == '0'
                and int(observed['status']['CapEff'], 16) == int(observed['status']['CapPrm'], 16) == 0
                and observed['securityContext'].startswith('u:r:untrusted_app')
                and observed['executable'] == native_dir + '/libfoldgpt_python.so', 'Native wrapper context/APK differs')
            require(not any('fake_userns' in target or 'libproot' in target for target in observed['mappedFiles']),
                'Native wrapper used guest compatibility layer')
        require(re.search(r'^\{"status": "PASS", "observations": ' + str(coverage['observations']) + r'\}$',
            output_data.decode('utf-8'), re.M), 'Missing real wrapper stdout completion')
    else:
        require(not any(optional.values()), 'Failed native suite unexpectedly has PASS artifacts')
        require('RuntimeError: The actual native acquisition conformance suite failed' in output_data.decode('utf-8'),
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
    result = {'schema': 'foldgpt.native-managed-independent.v1', 'status': 'PASS' if matrix['successful'] else 'OBSERVED_FAILURE',
        'fixture': args.fixture, 'collectedAtUtc': datetime.now(timezone.utc).isoformat(), 'uid': uid,
        'apkSha256': apk_sha, 'installedApkBefore': before, 'installedApkAfter': after,
        'optionalArtifactsPresent': optional, 'librariesSha256': libraries,
        'privateSourcesSha256': {name: sha(data) for name, data in source_data.items()},
        'wrapperSha256': sha(source_data[WRAPPER]), 'coverage': coverage, 'casesDirectoryEmpty': cases_empty,
        'contextEvidenceAvailable': report is not None,
        'nativeContext': {name: report[name] for name in ('observationBefore', 'observationAfter')} if report else None,
        'fixtureFiles': file_metadata, 'evidenceSha256': {path.relative_to(args.output).as_posix(): sha(path.read_bytes())
            for path in args.output.rglob('*') if path.is_file()}, 'collectorSha256': sha(collector_source),
        'scope': 'Fixed static managed acquisition diagnostics and their real recorded kernel events; no general process, shell, TTY, network, model or Desktop routing. Removed case bytes and historical process liveness cannot be reconstructed by this collector.'}
    (args.output / 'independent-verification.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: result[key] for key in ('status', 'fixture', 'apkSha256', 'optionalArtifactsPresent', 'coverage')}, indent=2))


if __name__ == '__main__':
    main()
