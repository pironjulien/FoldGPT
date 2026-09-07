"""Collect the one fixed Android qualification without launching or retrying it.

Three independent records must agree: app RPC/transport, private actual native
process evidence, and device/package/fixture snapshots. Failure evidence is kept
even when a process failed before a native record could be written.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys

BASE = '/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2'
PACKAGE = 'app.foldgpt.kernelqualification'
PROOFS = frozenset({'memoryRead', 'memoryWrite', 'pidfdGetfd', 'sharedOffset',
    'privateReadDenied', 'protectedWriteDenied', 'rawChdirDenied', 'networkDenied',
    'ioctlDenied', 'binderDenied', 'threadMemory', 'threadPidfdGetfd'})
FIXTURE = {'input': b'pin-memory-ok\n', 'private/secret': b'probe-private-unchanged\n',
           'directory/marker': b'marker\n'}


def strict(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON key: ' + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=object_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))


def exact(left, right):
    """Compare JSON values without treating false as integer zero."""
    return json.dumps(left, sort_keys=True, allow_nan=False) == json.dumps(right, sort_keys=True, allow_nan=False)


def transport_clean(app, native):
    """Only actual process and JNI wait records permit workspace inspection."""
    if type(app) is not dict or type(native) is not dict:
        return False
    transport, result = app.get('transport'), native.get('nativeResult')
    return (type(transport) is dict and type(result) is dict
        and app.get('schema') == 'foldgpt.android-kernel-rpc.v1'
        and native.get('schema') == 'foldgpt.bionic-kernel-qualification.private.v1'
        and transport.get('schema') == 'foldgpt.shizuku.transport.v1'
        and app.get('transportCleanupComplete') is True
        and transport.get('bootstrapReaped') is True and transport.get('cleanupComplete') is True
        and transport.get('ownerRetained') is False and transport.get('quarantined') is False
        and transport.get('transportFailed') is False and transport.get('refusedBeforeFork') is False
        and type(transport.get('waitStatus')) is int and transport['waitStatus'] in (0, 70 << 8)
        and native.get('quarantined') is False and native.get('supervisorWaited') is True
        and native.get('processClosed') is True and result.get('cleanupComplete') is True
        and type(native.get('supervisorReturncode')) is int
        and all(type(native.get(name)) is int and native[name] > 0 for name in ('bootstrapPid', 'supervisorPid')))


def verify_rpc(app, streams):
    """Require the complete observed exchange, not an app's success summary."""
    read, frames = app['read'], app['frames']
    if (type(read) is not dict or read.get('exited') is not True or read.get('closed') is not True
            or not exact(read.get('exitCode'), 0) or 'failure' not in read or read['failure'] is not None
            or read.get('sandboxDenied') is not False or type(read.get('chunks')) is not list
            or type(frames) is not list or not 5 <= len(frames) <= 128):
        raise ValueError('Incomplete or failed actual RPC lifecycle')
    replies, notifications, output = {}, [], []
    for frame in frames:
        if type(frame) is not dict or 'error' in frame:
            raise ValueError('Invalid or refused RPC frame')
        if 'id' in frame:
            key = frame['id']
            if type(key) is not int or key not in (1, 2, 3) or key in replies or type(frame.get('result')) is not dict:
                raise ValueError('Unexpected or duplicate RPC response')
            replies[key] = frame['result']
            continue
        method, params = frame.get('method'), frame.get('params')
        if (method not in ('process/output', 'process/exited', 'process/closed') or type(params) is not dict
                or params.get('processId') != 'kernel-qualification' or type(params.get('seq')) is not int
                or params['seq'] != len(notifications) + 1):
            raise ValueError('Unrelated, missing or reordered native process event')
        notifications.append((method, params))
        if method == 'process/output':
            output.append({key: value for key, value in params.items() if key != 'processId'})
    if (set(replies) != {1, 2, 3} or not exact(replies[3], read)
            or not exact(replies[2], {'processId': 'kernel-qualification', 'sandboxType': 'linuxSeccomp'})
            or not replies[1].get('sessionId') or type(replies[1].get('environmentInfo')) is not dict
            or not notifications or notifications[-1][0] != 'process/closed'
            or sum(method == 'process/closed' for method, _ in notifications) != 1
            or sum(method == 'process/exited' for method, _ in notifications) != 1
            or not exact(read.get('nextSeq'), len(notifications) + 1)
            or not exact(read['chunks'], output)):
        raise ValueError('RPC responses, output and terminal notifications do not agree')
    for method, params in notifications:
        if method == 'process/exited' and (not exact(params.get('exitCode'), 0) or params.get('sandboxDenied') is not False):
            raise ValueError('Actual exit notification is not successful')
    rpc_streams = {'stdout': b'', 'stderr': b''}
    for row in output:
        if row.get('stream') not in rpc_streams or type(row.get('chunk')) is not str:
            raise ValueError('Unexpected process output stream')
        rpc_streams[row['stream']] += base64.b64decode(row['chunk'], validate=True)
    if rpc_streams != streams or sum(map(len, rpc_streams.values())) > 8192:
        raise ValueError('Actual RPC bytes differ from the bounded native bytes')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--apk', required=True, type=Path)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--package', choices=(PACKAGE, 'app.foldgpt.shizukuprobe'), default=PACKAGE)
    parser.add_argument('--lab-report-version', choices=(2, 3, 4), type=int, default=2,
                        help='Fixed laboratory report generation; does not change the native fixture')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    checks, collected = {}, {}

    def read_json(name, command):
        try:
            result = subprocess.run([args.adb, '-s', args.serial, 'shell', '-T', shlex.join(command)],
                                    capture_output=True, timeout=30)
        except subprocess.TimeoutExpired as error:
            (args.output / (name + '.stdout')).write_bytes(error.stdout or b'')
            (args.output / (name + '.stderr')).write_bytes(error.stderr or b'')
            collected[name] = {'collected': False, 'timedOut': True}
            return None
        (args.output / (name + '.stdout')).write_bytes(result.stdout)
        (args.output / (name + '.stderr')).write_bytes(result.stderr)
        if result.returncode or result.stderr:
            collected[name] = {'collected': False, 'returncode': result.returncode}
            return None
        try:
            raw = base64.b64decode(result.stdout.replace(b'\r', b'').replace(b'\n', b''), validate=True)
            parsed = strict(raw)
            if type(parsed) is not dict:
                raise ValueError('Evidence must be a JSON object')
            (args.output / (name + '.json')).write_bytes(raw)
            collected[name] = {'collected': True, 'sha256': hashlib.sha256(raw).hexdigest()}
            return parsed
        except (ValueError, TypeError) as error:
            collected[name] = {'collected': False, 'error': str(error)}
            return None

    report_file = (f'files/kernel-v{args.lab_report_version}/report.json'
                   if args.package == 'app.foldgpt.shizukuprobe' else 'files/report.json')
    app = read_json('app-report', ['run-as', args.package, 'base64', report_file])
    native = read_json('native-evidence', ['base64', BASE + '/evidence.json'])
    # Do not traverse a workspace whose actual native ownership is unresolved.
    clean = transport_clean(app, native)
    command = [sys.executable, '-B', str(Path(__file__).with_name('snapshot-native-qualification.py')),
        '--adb', args.adb, '--serial', args.serial, '--output', str(args.output / 'after'),
        '--before', str(args.before), '--package', 'app.foldgpt', '--package', 'app.foldgpt.shizukuprobe',
        '--package', args.package]
    if clean:
        command += ['--workspace', BASE + '/workspace']
        for field in ('supervisorPid', 'bootstrapPid'):
            pid = native.get(field)
            if type(pid) is int and pid > 0:
                command += ['--absent-pid', str(pid)]
    try:
        snapshot_process = subprocess.run(command, capture_output=True, timeout=120)
        snapshot_returncode = snapshot_process.returncode
        snapshot_stdout, snapshot_stderr = snapshot_process.stdout, snapshot_process.stderr
    except subprocess.TimeoutExpired as failure:
        snapshot_returncode = None
        snapshot_stdout, snapshot_stderr = failure.stdout or b'', failure.stderr or b''
        collected['after-command'] = {'collected': False, 'timedOut': True}
    (args.output / 'snapshot-command.stdout').write_bytes(snapshot_stdout)
    (args.output / 'snapshot-command.stderr').write_bytes(snapshot_stderr)
    try:
        after = strict((args.output / 'after/snapshot.json').read_bytes())
    except (OSError, ValueError) as failure:
        collected['after'] = {'collected': False, 'error': str(failure)}
        after = None
    checks['recordsCollected'] = app is not None and native is not None and after is not None
    error = None
    try:
        if not checks['recordsCollected']:
            raise ValueError('One or more actual evidence records are unavailable')
        before = strict(args.before.read_bytes())
        checks['beforeSnapshotValid'] = (before.get('schema') == 'foldgpt.native-device-snapshot.v1'
            and before.get('collectionComplete') is True and before.get('errors') == []
            and before.get('bootStableDuringCollection') is True and before.get('serial') == args.serial)
        checks['recordSchemasAndPhases'] = (app.get('schema') == 'foldgpt.android-kernel-rpc.v1'
            and native.get('schema') == 'foldgpt.bionic-kernel-qualification.private.v1'
            and native.get('phase') == 'process-finished' and native.get('lifetimeScope') == 'native-process-only'
            and native.get('bootstrapAliveDuringReport') is True and native.get('startError') is None
            and 'failure' in native and native['failure'] is None and native.get('setupDiagnostic') == ''
            and not any(key in app for key in ('error', 'cleanupError')) and 'error' not in native)
        checks['nativeAndroidIdentity'] = (native.get('androidExecution') is True and native.get('platform') == 'android'
            and type(native.get('uid')) is int and native['uid'] == 2000
            and type(native.get('gid')) is int and native['gid'] == 2000)
        identity = native.get('bootstrapIdentity', {})
        status = identity.get('status', {})
        checks['actualBootstrapShellContext'] = (identity.get('securityContext') == 'u:r:shell:s0'
            and all(type(identity.get(name)) is int and identity[name] == 2000 for name in ('uid', 'euid', 'gid', 'egid'))
            and all(status.get(name, '').split() == ['2000'] * 4 for name in ('Uid', 'Gid'))
            and all(status.get(name) and int(status[name], 16) == 0 for name in ('CapInh', 'CapPrm', 'CapEff', 'CapAmb'))
            and not identity.get('readError'))
        checks['bootstrapPidConsistent'] = (type(identity.get('pid')) is int
            and identity['pid'] == native.get('bootstrapPid')
            and status.get('Pid') == str(identity['pid']) and status.get('Tgid') == str(identity['pid'])
            and native.get('supervisorPid') != identity['pid'])
        checks['nativeSuccess'] = native.get('success') is True
        checks['cleanNativeAndTransport'] = clean
        transport = app.get('transport', {})
        checks['transportWait'] = (transport.get('bootstrapReaped') is True and transport.get('cleanupComplete') is True
            and transport.get('ownerRetained') is False and transport.get('quarantined') is False
            and transport.get('transportFailed') is False and exact(transport.get('waitStatus'), 0)
            and transport.get('ready') is True and transport.get('refusedBeforeFork') is False
            and transport.get('setupError') is None
            and exact(app.get('shizukuServerUid'), 2000)
            and type(app.get('clientUid')) is int and app['clientUid'] >= 10000)
        result = native.get('nativeResult') or {}
        checks['realExitZero'] = (result.get('started') is True and result.get('outcome') == 'exited'
            and type(result.get('exitCode')) is int and result['exitCode'] == 0
            and all(exact(result.get(name), 0) for name in ('signal', 'errno', 'stage'))
            and result.get('type') == 'result' and exact(native.get('supervisorReturncode'), 0))
        checks['rpcSuccess'] = app.get('rpcSuccess') is True and app.get('state') == 'complete'
        streams = {name: base64.b64decode(native[name + 'Base64'], validate=True) for name in ('stdout', 'stderr')}
        proof = strict(streams['stdout'])
        checks['exactProofFlags'] = (set(proof) == PROOFS | {'type', 'success'} and proof['type'] == 'kernel-qualification'
            and all(proof[name] is True for name in PROOFS | {'success'})
            and len(streams['stdout'].splitlines()) == 1 and streams['stdout'].endswith(b'\n')
            and exact(native.get('proofs'), proof))
        verify_rpc(app, streams)
        checks['actualRpcLifecycleAndBytes'] = True
        checks['byteStreamsAgree'] = (not streams['stderr']
            and all(app[name].encode() == streams[name] and native[name].encode() == streams[name] for name in streams))
        checks['reportedByteCountsAgree'] = all(exact(result.get(name + 'Bytes'), len(streams[name])) for name in streams)
        checks['nativeWorkspace'] = native.get('workspace') == BASE + '/workspace'
        checks['deviceSnapshotValid'] = (snapshot_returncode == 0 and after.get('collectionComplete') is True
            and after.get('schema') == 'foldgpt.native-device-snapshot.v1' and after.get('errors') == []
            and after.get('serial') == args.serial and after.get('bootStableDuringCollection') is True
            and after.get('bootId') == after.get('bootIdAtEnd'))
        comparison = after.get('comparison', {})
        checks['sameDeviceBootAndIndicators'] = all(comparison.get(name) is True
            for name in ('sameDevice', 'sameBoot', 'sameIndicators')) and after.get('observedStockIndicators') is True
        checks['originalPackagesUnchanged'] = all(comparison.get('packagesUnchanged', {}).get(name) is True
            for name in ('app.foldgpt', 'app.foldgpt.shizukuprobe'))
        with args.apk.open('rb') as apk_file:
            apk_sha = hashlib.file_digest(apk_file, 'sha256').hexdigest()
        checks['installedApkMatches'] = list(after.get('packages', {}).get(args.package, {}).values()) == [apk_sha]
        fixture = after.get('fixture', {})
        checks['fixtureUnchanged'] = (fixture.get('sha256') == {name: hashlib.sha256(data).hexdigest() for name, data in FIXTURE.items()}
            and fixture.get('gitConfigAbsent') is True and comparison.get('fixtureUnchanged') is True)
        # NAME may expose argv[0] (the logical worker key), an ELF basename, or
        # the 15-byte Linux comm spelling. Never inspect full private argv.
        worker_names = {'kernel-qualification', 'libfoldgpt_qualification_worker.so', 'libfoldgpt_bionic_supervisor.so'}
        worker_names |= {name[:15] for name in worker_names}
        checks['workerAndSupervisorAbsent'] = after.get('processTableValid') is True and bool(after.get('processes')) and not any(
            row['name'].rsplit('/', 1)[-1] in worker_names for row in after.get('processes', []))
        checks['reportedOwnersAbsent'] = all(type(native.get(field)) is int and native[field] > 0
            and after.get('expectedPidAbsence', {}).get(str(native[field])) is True for field in ('supervisorPid', 'bootstrapPid'))
    except (OSError, KeyError, ValueError, TypeError, AttributeError, IndexError) as failure:
        error = str(failure)
    success = bool(checks) and all(value is True for value in checks.values()) and error is None
    report = {'schema': 'foldgpt.independent-kernel-qualification.v1', 'success': success,
              'checks': checks, 'collected': collected, 'error': error,
              'scope': 'Fixed Shizuku/Bionic worker only; ordinary model commands are not validated'}
    (args.output / 'independent-verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))
    if not success:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
