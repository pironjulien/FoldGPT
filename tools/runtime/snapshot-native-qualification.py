"""Read-only device evidence around the fixed Shizuku kernel qualification.

This collector never launches the worker, changes a setting, or claims that
unchanged boot indicators prove native execution. Process arguments and private
application data are deliberately not collected. Keep the actual RPC/native
report alongside this independent snapshot.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
from runtime_qualification_identity import BASES as RUNTIME_BASES


def fixture_names(workspace):
    if workspace in tuple(base + '/workspace' for base in RUNTIME_BASES):
        return ('private/secret',)
    if re.fullmatch(r'/data/local/tmp/foldgpt-bionic-supervisor-qualification-[A-Za-z0-9_-]+/workspace', workspace):
        return ('input', 'private/secret', 'directory/marker')
    raise ValueError('Only an exact dedicated qualification workspace may be collected')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--before', type=Path)
    parser.add_argument('--package', action='append', default=[])
    parser.add_argument('--absent-pid', action='append', type=int, default=[])
    parser.add_argument('--workspace')
    args = parser.parse_args()
    for package in args.package:
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+', package):
            parser.error('Invalid Android package name')
    try:
        names = fixture_names(args.workspace) if args.workspace else ()
    except ValueError as error:
        parser.error(str(error))
    if any(pid <= 0 for pid in args.absent_pid):
        parser.error('Expected absent PIDs must be positive')
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'foldgpt.native-device-snapshot.v1',
              'timestamp': datetime.now(timezone.utc).isoformat(),
              'serial': args.serial, 'commands': {}, 'errors': []}

    def read(name, command, *, allow_failure=False):
        # shell-v2 preserves stderr and the remote exit status. This Windows
        # ADB build converts output LF to CRLF even without a PTY; exact file
        # bytes therefore travel as base64 below, not as raw shell output.
        result = subprocess.run([args.adb, '-s', args.serial, 'shell', '-T', shlex.join(command)],
                                capture_output=True, timeout=30)
        (args.output / (name + '.stdout')).write_bytes(result.stdout)
        (args.output / (name + '.stderr')).write_bytes(result.stderr)
        report['commands'][name] = {'argv': command, 'returncode': result.returncode,
            'stdoutSha256': hashlib.sha256(result.stdout).hexdigest(),
            'stderrSha256': hashlib.sha256(result.stderr).hexdigest()}
        if result.returncode or result.stderr:
            if not allow_failure:
                report['errors'].append(name)
            return None
        return result.stdout

    def text(name, command):
        value = read(name, command)
        return value.decode('utf-8', 'strict').strip() if value is not None else None

    report['bootId'] = text('boot-id', ['cat', '/proc/sys/kernel/random/boot_id'])
    report['kernel'] = text('kernel', ['uname', '-r'])
    report['indicators'] = {name: text(name, ['getprop', name]) for name in
        ('ro.boot.warranty_bit', 'ro.boot.verifiedbootstate', 'ro.boot.flash.locked')}
    report['indicators']['selinux'] = text('selinux', ['getenforce'])
    report['adbShellIdentity'] = text('shell-identity', ['id'])
    report['adbShellDomain'] = text('shell-domain', ['cat', '/proc/self/attr/current'])
    report['adbShellStatus'] = text('shell-status', ['cat', '/proc/self/status'])
    report['memory'] = text('memory', ['cat', '/proc/meminfo'])
    process_text = text('processes', ['ps', '-A', '-o', 'UID,PID,PPID,NAME'])
    report['processes'] = []
    process_table_valid = bool(process_text and process_text.splitlines()[0].split() == ['UID', 'PID', 'PPID', 'NAME'])
    if process_text:
        for line in process_text.splitlines()[1:]:
            fields = line.split(None, 3)
            if len(fields) != 4 or not fields[1].isdigit() or not fields[2].isdigit():
                report['errors'].append('malformed-process-record')
                process_table_valid = False
                continue
            report['processes'].append(dict(uid=fields[0], pid=int(fields[1]),
                ppid=int(fields[2]), name=fields[3]))
    live_pids = {item['pid'] for item in report['processes']}
    process_table_valid = process_table_valid and bool(live_pids) and len(live_pids) == len(report['processes'])
    if not process_table_valid:
        report['errors'].append('invalid-process-table')
    report['processTableValid'] = process_table_valid
    report['expectedPidAbsence'] = {str(pid): pid not in live_pids if process_table_valid else None for pid in args.absent_pid}
    report['packages'] = {}
    for package in args.package:
        value = text(package + '-paths', ['pm', 'path', package])
        files = {}
        if not value:
            report['errors'].append('package-unavailable:' + package)
        else:
            for i, line in enumerate(value.splitlines()):
                if not line.startswith('package:/data/app/') or not line.endswith('.apk'):
                    report['errors'].append('unexpected-apk-location:' + package)
                    continue
                path = line.removeprefix('package:')
                digest_line = text(package + '-apk-' + str(i), ['sha256sum', path])
                if not digest_line or not re.match(r'^[0-9a-f]{64}  ', digest_line):
                    report['errors'].append('invalid-apk-digest:' + package)
                else:
                    files[path] = digest_line[:64]
        report['packages'][package] = files
    if args.workspace:
        files = {}
        for name in names:
            encoded = read('fixture-' + name.replace('/', '-'), ['base64', args.workspace + '/' + name])
            value = base64.b64decode(encoded.replace(b'\r', b'').replace(b'\n', b''), validate=True) if encoded is not None else None
            files[name] = hashlib.sha256(value).hexdigest() if value is not None else None
        metadata = read('fixture-git-config', ['stat', '-c', '%F', args.workspace + '/.git/config'],
                        allow_failure=True)
        # A failed stat can mean denied access too. A directory listing supplies
        # independent positive evidence of the protected directory's contents.
        listing = read('fixture-git-list', ['ls', '-A', args.workspace + '/.git'])
        report['fixture'] = {'workspace': args.workspace, 'sha256': files,
                            'gitConfigAbsent': metadata is None and listing == b''}
    report['bootIdAtEnd'] = text('boot-id-end', ['cat', '/proc/sys/kernel/random/boot_id'])
    report['bootStableDuringCollection'] = bool(report['bootId']) and report['bootId'] == report['bootIdAtEnd']
    if not report['bootStableDuringCollection']:
        report['errors'].append('boot-changed-or-unavailable-during-collection')
    report['observedStockIndicators'] = report['indicators'] == {
        'ro.boot.warranty_bit': '0', 'ro.boot.verifiedbootstate': 'green',
        'ro.boot.flash.locked': '1', 'selinux': 'Enforcing'}
    if args.before:
        before = json.loads(args.before.read_text(encoding='utf-8'))
        report['comparison'] = {
            'sameDevice': before['serial'] == report['serial'],
            'sameBoot': before.get('bootStableDuringCollection') is True and report['bootStableDuringCollection'] and before['bootId'] == report['bootId'],
            'sameIndicators': before['indicators'] == report['indicators'],
            'packagesUnchanged': {package: bool(files) and report['packages'].get(package) == files
                                  for package, files in before['packages'].items()}}
        if before.get('fixture') and report.get('fixture'):
            report['comparison']['fixtureUnchanged'] = before['fixture'] == report['fixture']
    report['collectionComplete'] = not report['errors']
    report['scope'] = ('Independent device snapshot only; ADB shell context is not a measurement '
                       'of the Shizuku UserService or a native-execution pass')
    (args.output / 'snapshot.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({key: report[key] for key in ('collectionComplete', 'bootId',
        'observedStockIndicators', 'errors', 'scope')} | {'output': str(args.output)}))
    if report['errors']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
