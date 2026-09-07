"""Collect an actual fixed Shizuku run and verify its material Python results.

This never starts a command on behalf of the model or reruns the phone fixture.
The built zipapp is independently checked on the PC after exact byte collection.
"""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import sys
import tarfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--apk', required=True, type=Path)
    parser.add_argument('--probe', required=True, type=Path)
    parser.add_argument('--before', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    adb = [args.adb, '-s', args.serial]
    def read(name, command, binary=False):
        result = subprocess.run(adb + (['exec-out'] if binary else ['shell', '-T'])
                                + [shlex.join(command)], capture_output=True, timeout=30)
        (args.output / (name + ('.bin' if binary else '.txt'))).write_bytes(result.stdout)
        (args.output / (name + '.stderr')).write_bytes(result.stderr)
        if result.returncode or result.stderr:
            raise ValueError('Collection failed: ' + name)
        return result.stdout
    raw = read('report', ['run-as', 'app.foldgpt.shizukuprobe', 'cat', 'files/report.json'])
    report = json.loads(raw)
    if report.get('state') != 'complete' or report.get('success') is not True:
        print(json.dumps({'state': report.get('state'), 'success': report.get('success'),
                          'error': report.get('error'), 'stdout': report.get('stdout'),
                          'stderr': report.get('stderr'), 'output': str(args.output)}))
        raise SystemExit(1)
    assert report['nativeLaunches'] == 1 and report['shizukuServerUid'] == 2000
    assert report['context']['serviceUid'] == 2000
    assert report['context']['authorizedClientUid'] == report['clientUid'] == report['context']['callingUid']
    assert report['cleanup_complete'] and report['processExited'] and report['exitCode'] == 0
    assert report['stdoutComplete'] and report['stderrComplete']
    assert not report['stdoutTruncated'] and not report['stderrTruncated']
    expected_probe = hashlib.sha256(args.probe.read_bytes()).hexdigest()
    assert report['actualSha256'] == report['expectedSha256'] == expected_probe
    actual_probe = read('probe', ['cat', '/data/local/tmp/foldgpt-shizuku-lab/probe'], True)
    assert hashlib.sha256(actual_probe).hexdigest() == expected_probe
    apk_path = read('apk-path', ['pm', 'path', 'app.foldgpt.shizukuprobe']).decode().strip()
    assert apk_path.startswith('package:/data/app/') and apk_path.endswith('/base.apk')
    actual_apk = read('apk', ['cat', apk_path[8:]], True)
    expected_apk = hashlib.sha256(args.apk.read_bytes()).hexdigest()
    assert hashlib.sha256(actual_apk).hexdigest() == expected_apk
    events = []
    for line in report['stdout'].splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    finals = [x for x in events if x.get('type') == 'probe-result']
    fixtures = [x for x in events if x.get('type') == 'fixture-pass']
    restrictions = [x for x in events if x.get('type') == 'restrictions-checked']
    assert len(finals) == len(fixtures) == len(restrictions) == 1
    final, fixture = finals[0], fixtures[0]
    assert final['success'] and final['cleanup_complete'] and final['exitCode'] == 0
    assert fixture['unittest_passes'] == 3 and fixture['zipapp_stdout'] == '42\n'
    assert fixture['denials_in_interpreter'] == 6 and fixture['empty_child_environment']
    denials = [x for x in events if x.get('denied') is True]
    assert len({x['check'] for x in denials}) == 6
    # The fixed script forwards its captured unittest stderr to its own stdout.
    assert 'Ran 3 tests' in report['stdout'] and 'OK' in report['stdout']
    material = read('workspace', ['tar', '-cf', '-', '-C', '/data/local/tmp/foldgpt-shizuku-lab',
                                 'workspace', 'outside-sentinel'], True)
    hashes = {}
    with tarfile.open(fileobj=io.BytesIO(material)) as archive:
        for member in archive:
            path = PurePosixPath(member.name)
            assert not path.is_absolute() and '..' not in path.parts
            assert member.isdir() or member.isfile()
            target = args.output / 'material' / path
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                data = archive.extractfile(member).read()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                hashes[str(path)] = hashlib.sha256(data).hexdigest()
    result_root = args.output / 'material'
    assert (result_root / 'outside-sentinel').read_bytes() == b'outside readable only before confinement\n'
    source = result_root / 'workspace/project/calculator.py'
    assert source.read_text() == 'def add(a, b):\n    return a + b\n\ndef answer():\n    return 42\n'
    physical = json.loads((result_root / 'workspace/qualification-result.json').read_text())
    assert physical == fixture
    built = result_root / 'workspace/dist/calculator.pyz'
    assert built.stat().st_size == fixture['zipapp_bytes']
    with zipfile.ZipFile(built) as archive:
        assert archive.testzip() is None
        assert archive.read('calculator.py') == source.read_bytes()
    # The PC uses its platform's stdout newline (CRLF on Windows); compare
    # this text result using universal newlines. Device bytes remain exact.
    pc = subprocess.run([sys.executable, '-B', str(built)], capture_output=True,
                        text=True, encoding='utf-8', timeout=10)
    assert pc.returncode == 0 and pc.stdout == '42\n' and not pc.stderr
    boot_after = read('boot-id', ['cat', '/proc/sys/kernel/random/boot_id']).decode().strip()
    before_match = re.search(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}', args.before.read_text())
    assert before_match and boot_after == before_match.group()
    indicators = {}
    for key in ['ro.boot.warranty_bit', 'ro.boot.verifiedbootstate', 'ro.boot.flash.locked']:
        indicators[key] = read(key, ['getprop', key]).decode().strip()
    indicators['selinux'] = read('selinux', ['getenforce']).decode().strip()
    assert list(indicators.values()) == ['0', 'green', '1', 'Enforcing']
    processes = read('processes', ['ps', '-A', '-o', 'UID,PID,PPID,NAME,ARGS']).decode()
    live_pids = {int(x.split()[1]) for x in processes.splitlines()[1:] if len(x.split()) > 2}
    for key in ['supervisorPid', 'childPid']:
        if key in final:
            assert final[key] not in live_pids, 'A fixture process remains present'
    verified = {'state': 'PASS', 'scope': 'Fixed offline Shizuku/Bionic feasibility test; not normal model routing',
                'apkSha256': expected_apk, 'probeSha256': expected_probe,
                'python': fixture['python'], 'unittestPasses': 3, 'pythonDenials': 6,
                'zipappOutput': '42\n', 'independentPcZipappCheck': True,
                'bootUnchanged': True, 'indicators': indicators, 'nativeFinal': final,
                'materialSha256': hashes}
    (args.output / 'independent-verification.json').write_text(json.dumps(verified, indent=2) + '\n')
    print(json.dumps(verified))


if __name__ == '__main__':
    main()
