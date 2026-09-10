"""Read-only independent collection of a completed fixed native GNU probe.

Reads Android files with binary subprocess/adb exec-out. Never installs, starts,
signals, repairs or executes a fixture, its Python files, or its ZIP application.
Historical denials/reaping remain observations of the native probe; current
filesystem, packaged libraries and absence of identifiable workers are checked
independently. This is not a Desktop/model-driven execution proof.
"""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import subprocess
import tarfile
import uuid
import zipfile


def require(value, message):
    if not value:
        raise RuntimeError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'Duplicate JSON field')
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def relative(name):
    require(isinstance(name, str) and name and '\\' not in name and '\0' not in name,
            'Invalid evidence name')
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and str(path) == name,
            'Evidence name is not a normalized relative path')
    return path


class Collector:
    def __init__(self, args):
        self.args = args
        self.adb = [args.adb, '-s', args.serial]
        self.root = Path(__file__).resolve().parents[3]
        self.out = args.output or self.root / 'downloads/gnu-runtime' / ('collected-' + uuid.uuid4().hex)
        self.out.mkdir(parents=True, exist_ok=False)
        self.raw = self.out / 'raw'
        self.raw.mkdir()
        self.records = {}
        self.commands = []

    def command(self, *argv, app=True, check=True, timeout=30, input_data=None):
        command = ['run-as', 'app.foldgpt', *argv] if app else list(argv)
        result = subprocess.run(self.adb + ['exec-out', shlex.join(command)],
            capture_output=True, input=input_data, timeout=timeout)
        # Record commands and hashes, not unsolicited private process contents.
        self.commands.append({'argv':command, 'exitCode':result.returncode,
            'stdoutBytes':len(result.stdout), 'stdoutSha256':sha(result.stdout),
            'stderrBytes':len(result.stderr), 'stderrSha256':sha(result.stderr)})
        if check:
            require(result.returncode == 0 and not result.stderr,
                'Android read failed: ' + argv[0] + ' exit=' + str(result.returncode))
        return result

    def save(self, name, data):
        target = self.raw.joinpath(*relative(name).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return data

    def info(self, path, private=True, kind='file'):
        values = self.command('stat', '-c', '%f %u %g %s %d %i %a %h', path).stdout.decode().split()
        require(len(values) == 8, 'Invalid stat response')
        mode = int(values[0], 16)
        value = {'uid':int(values[1]), 'gid':int(values[2]), 'bytes':int(values[3]),
            'device':int(values[4]), 'inode':int(values[5]), 'mode':int(values[6], 8),
            'links':int(values[7]), 'type':stat.S_IFMT(mode)}
        predicates = {'file':stat.S_ISREG, 'directory':stat.S_ISDIR, 'symlink':stat.S_ISLNK}
        require(predicates[kind](mode), 'Wrong native file type: ' + path)
        if private:
            require(value['uid'] == self.uid and not value['mode'] & 0o077,
                'Evidence is not private app-owned data: ' + path)
        if kind == 'file':
            require(value['links'] == 1, 'Multiply linked evidence: ' + path)
        return value

    def read(self, path, name, private=True, bound=4 * 1024 * 1024):
        before = self.info(path, private)
        require(before['bytes'] <= bound, 'Evidence exceeds read bound')
        data = self.command('cat', path, timeout=60).stdout
        after = self.info(path, private)
        require(before == after and len(data) == before['bytes'], 'Evidence changed during read')
        self.records[path] = {**before, 'sha256':sha(data)}
        return self.save(name, data)

    def native_hash(self, path, algorithm='sha256sum'):
        result = self.command(algorithm, path, timeout=60).stdout.decode().split(maxsplit=1)
        require(len(result) == 2 and re.fullmatch('[0-9a-f]{' + ('64' if algorithm == 'sha256sum' else '32') + '}', result[0]),
            'Invalid native digest')
        return result[0]

    def apk_identity(self):
        paths = self.command('pm', 'path', 'app.foldgpt', app=False).stdout.decode().splitlines()
        require(len(paths) == 1 and re.fullmatch(r'package:/data/app/[A-Za-z0-9_+=.~/-]+/base\.apk', paths[0]),
            'Expected one installed APK')
        path = paths[0][8:]
        require('..' not in PurePosixPath(path).parts, 'Invalid package path')
        return {'path':path, 'sha256':self.native_hash(path)}

    def security(self):
        properties = ('ro.product.model', 'ro.soc.model', 'ro.product.cpu.abi',
            'ro.build.version.sdk', 'ro.build.version.release', 'ro.build.version.oneui',
            'ro.build.version.security_patch', 'ro.boot.warranty_bit',
            'ro.boot.verifiedbootstate', 'ro.boot.flash.locked')
        result = {key:self.command('getprop', key, app=False).stdout.decode().strip() for key in properties}
        result['selinux'] = self.command('getenforce', app=False).stdout.decode().strip()
        result['kernel'] = self.command('uname', '-srmo', app=False).stdout.decode().strip()
        require(result['ro.boot.warranty_bit'] == '0' and result['ro.boot.verifiedbootstate'] == 'green'
            and result['ro.boot.flash.locked'] == '1' and result['selinux'] == 'Enforcing',
            'Current boot/security indicators differ from required unchanged state')
        return result

    def processes(self, fixture, native):
        # Only collect PID/PPID/UID. No conversations, credentials or environments.
        rows = self.command('ps', '-A', '-o', 'PID,PPID,UID').stdout.decode().splitlines()
        observed = []
        for row in rows[1:]:
            fields = row.split()
            require(len(fields) == 3 and all(v.isdigit() for v in fields), 'Unexpected native process row')
            pid, ppid, uid = map(int, fields)
            if uid != self.uid:
                continue
            comm = self.command('cat', f'/proc/{pid}/comm', check=False)
            if comm.returncode:
                continue  # A read-only collector process may have just exited.
            cwd = self.command('readlink', f'/proc/{pid}/cwd', check=False)
            exe = self.command('readlink', f'/proc/{pid}/exe', check=False)
            name = comm.stdout.decode(errors='replace').strip()
            within = cwd.stdout.decode(errors='replace').strip().startswith(fixture + '/')
            launcher = exe.stdout.decode(errors='replace').strip() == native + '/libfoldgpt-gnu-project.so'
            strict_proot = exe.stdout.decode(errors='replace').strip() == native + '/libfoldgpt-strict-proot.so'
            observed.append({'pid':pid, 'ppid':ppid, 'uid':uid, 'comm':name,
                'cwdWithinFixture':within, 'gnuLauncher':launcher, 'strictProot':strict_proot})
        require(not any(p['cwdWithinFixture'] or p['gnuLauncher'] or p['strictProot'] for p in observed),
            'Identifiable GNU probe worker still exists')
        return {'observed':observed, 'identifiableWorkers':0,
            'limit':'Post-run process snapshot cannot reconstruct historical ancestry; native ECHILD/reaping is logged by the fixture.'}

    def collect(self):
        self.save('collector-source.py', Path(__file__).read_bytes())
        self.uid = int(self.command('id', '-u').stdout.strip())
        require(self.uid > 0, 'Expected nonroot app UID')
        require(re.fullmatch(r'gnu-log-[0-9]{1,24}', self.args.log), 'Invalid fixed log directory')
        require(re.fullmatch(r'foldgpt-gnu-project-[A-Za-z0-9]{6}', self.args.fixture), 'Invalid fixed case directory')
        app = '/data/data/app.foldgpt'
        logroot = app + '/cache/' + self.args.log
        case = app + '/cache/' + self.args.fixture
        project = case + '/scratch/project'
        apk_before = self.apk_identity()
        security_before = self.security()
        for directory in (logroot, case, project, case + '/outside', case + '/workspace'):
            self.info(directory, kind='directory')
        logs = {name:self.read(logroot + '/' + name, 'logs/' + name) for name in
            ('stdout.log', 'stderr.log', 'android-exit.txt')}
        stdout = logs['stdout.log'].decode()
        require(logs['android-exit.txt'] == f'exit=0 uid={self.uid}\n'.encode(), 'Native Android launcher failed')
        require(re.findall(r'^uid=([0-9]+) landlock_abi=([0-9]+) inherited_seccomp=([0-9]+)$', stdout, re.M)
            == [(str(self.uid), '6', '2')], 'Unexpected native protection identity')
        require(re.findall(r'^independent_parent_verification=PASS evidence_directory=(.*)$', stdout, re.M)
            == [case], 'Native verification is not bound to requested case')
        require(re.findall(r'^owned_descendant_cleanup=PASS terminated=([0-9]+)$', stdout, re.M) == ['0'],
            'Expected logged normal ECHILD cleanup')
        require('=FAIL' not in stdout and 'bounded worker failed' not in logs['stderr.log'].decode(), 'Failed native observation')
        expected_workers = ('parent_ptrace_access_denied', 'landlock_direct_write_denied',
            'notification_filter_installed', 'notification_listener_sent', 'workspace_chmod_denied',
            'workspace_mode_fd_open', 'workspace_fchmod_denied', 'outside_chmod_denied',
            'outside_read_denied', 'direct_openat2_filtered')
        for name in expected_workers:
            require(len(re.findall(r'^worker ' + name + r'=PASS errno=[0-9]+$', stdout, re.M)) == 1,
                'Missing native worker observation: ' + name)
        require(re.search(r'^scratch_mode_changes=[1-9][0-9]*$', stdout, re.M)
            and re.search(r'scratch_grants=[1-9][0-9]* ', stdout), 'No actual scratch mutations')
        report = strict_json(self.read(project + '/report.json', 'project/report.json'))
        require(set(report) == {'status','uid','python','machine','tests','buildExit','nonzeroExit','denials','artifacts'},
            'Unexpected GNU report fields')
        require(report['status'] == 'PASS' and report['uid'] == self.uid and report['machine'] == 'aarch64'
            and report['tests'] == 3 and report['buildExit'] == 0 and report['nonzeroExit'] == 23,
            'GNU report does not describe successful native project execution')
        expected_denials = [('outside-file-read', 13), ('workspace-symlink-outside-read', 13),
            ('actual-proc-environment-read', 13), ('outside-file-write', 1), ('outside-mode-change', 1),
            ('external-network-socket', 1), ('network-namespace-unshare', 1), ('unsupported-pr-set-dumpable', 95)]
        require(report['denials'] == [{'name':name, 'errno':number} for name, number in expected_denials],
            'Protection denial coverage changed')
        require(isinstance(report['artifacts'], dict) and len(report['artifacts']) == 10, 'Unexpected artifact count')
        artifacts = {}
        for name, expected in report['artifacts'].items():
            relative(name)
            require(re.fullmatch(r'[a-zA-Z0-9_./-]+', name) and re.fullmatch(r'[0-9a-f]{64}', expected), 'Invalid artifact declaration')
            data = self.read(project + '/' + name, 'project/' + name)
            require(sha(data) == expected, 'Changed GNU artifact: ' + name)
            artifacts[name] = data
        inventory = self.command('find', project, '-type', 'f', '-print0').stdout.split(b'\0')
        require(inventory[-1] == b'' and len(inventory) < 100, 'Malformed native project inventory')
        require({x.decode()[len(project)+1:] for x in inventory[:-1]}
            == set(artifacts) | {'report.json'}, 'Missing or extra project files')
        require(self.command('find', project, '-type', 'l', '-print0').stdout == b'', 'Project contains a symlink')
        require(artifacts['app/maths.py'] == b'def doubled(value):\n    return value * 2\n', 'Source edit absent')
        require(artifacts['app/__main__.py'] == b'from maths import doubled\nprint(f"native GNU project: {doubled(21)}")\n',
            'Wrong application entry point')
        tests = ast.parse(artifacts['test_maths.py'])
        require(sorted(n.name for n in ast.walk(tests) if isinstance(n, ast.FunctionDef))
            == ['test_negative', 'test_positive', 'test_zero'], 'Actual test source coverage differs')
        require(re.findall(rb'^test_(negative|positive|zero) \(test_maths\.MathsTests\.test_\1\) \.\.\. ok$',
            artifacts['build.stderr'], re.M) == [b'negative',b'positive',b'zero']
            and re.search(rb'\nRan 3 tests in [0-9.]+s\n\nOK\n$', artifacts['build.stderr']), 'Actual unittest log differs')
        require(artifacts['build.stdout'] == b'' and artifacts['dist/result.txt'] == b'native GNU project: 42\n',
            'Build or packaged execution output differs')
        with zipfile.ZipFile(io.BytesIO(artifacts['dist/app.pyz'])) as archive:
            require(len(archive.namelist()) == len(set(archive.namelist())) and len(archive.namelist()) <= 10,
                'Invalid ZIP application inventory')
            zip_files = {item.filename for item in archive.infolist() if not item.is_dir()}
            require(zip_files == {name[4:] for name in artifacts if name.startswith('app/')}, 'ZIP content differs from source tree')
            for name in zip_files:
                require(archive.read(name) == artifacts['app/' + name], 'ZIP member bytes differ: ' + name)
        for name in [key for key in artifacts if key.endswith('.pyc')]:
            require(len(artifacts[name]) > 16 and artifacts[name][2:4] == b'\r\n', 'Missing CPython bytecode header')
        for name, expected in (('outside/victim.txt', b'Outside file remains intact\n'),
            ('workspace/.git/config', b'Protected metadata remains intact\n'),
            ('workspace/src/.git/config', b'Protected metadata remains intact\n')):
            require(self.read(case + '/' + name, 'protected/' + name) == expected, 'Protected bytes changed')
            require(self.records[case + '/' + name]['mode'] == 0o600, 'Protected mode changed')
        for name in ('workspace/unbrokered.txt','workspace/.git/new-file','workspace/.codex/config.toml',
            'workspace/.agents/settings','scratch/codexhome/auth.json'):
            require(self.command('find', case, '-path', case + '/' + name, '-print0').stdout == b'', 'Forbidden fixture file exists')
        require(self.command('readlink', case + '/workspace/outside-link').stdout == b'../outside\n', 'Escape fixture alias differs')
        native = str(PurePosixPath(apk_before['path']).parent / 'lib/arm64')
        apk_bytes = self.read(apk_before['path'], 'installed.apk', private=False, bound=250*1024*1024)
        require(sha(apk_bytes) == apk_before['sha256'], 'Installed APK changed during transfer')
        build = self.args.build.resolve(strict=True)
        build_manifest_bytes = (build/'manifest.json').read_bytes()
        manifest = strict_json(build_manifest_bytes)
        self.save('provenance/launcher-manifest.json', build_manifest_bytes)
        for name, expected in manifest['files'].items():
            source = build.joinpath(*relative(name).parts).read_bytes()
            require(sha(source) == expected, 'Frozen launcher input differs: ' + name)
            if name.startswith('sources/'):
                self.save('provenance/' + name, source)
        libs = ('libfoldgpt-gnu-project.so','libfoldgpt-strict-proot.so','libproot-loader.so','libproot-loader32.so','libtalloc.so')
        native_manifest_bytes = (self.args.native_build/'manifest.json').read_bytes()
        native_manifest = strict_json(native_manifest_bytes)
        self.save('provenance/native-build-manifest.json', native_manifest_bytes)
        library_identity = {}
        strip_records = {}
        with zipfile.ZipFile(io.BytesIO(apk_bytes)) as apk:
            require(len(apk.namelist()) == len(set(apk.namelist())), 'Duplicate APK entries')
            for name in libs:
                packaged = apk.read('lib/arm64-v8a/' + name)
                actual = self.read(native + '/' + name, 'libraries/' + name, private=False, bound=32*1024*1024)
                require(actual == packaged, 'Extracted native library differs from APK: ' + name)
                build_name = 'libproot.so' if name == libs[1] else name
                expected = manifest['files'][name] if name == libs[0] else native_manifest['artifacts'][build_name]['sha256']
                build_file = build/name if name == libs[0] else self.args.native_build/'runtime/arm64-v8a'/build_name
                require(sha(build_file.read_bytes()) == expected, 'Frozen native build artifact changed')
                if sha(actual) != expected:
                    require(self.args.llvm_strip is not None, 'Stripped APK requires explicit matching NDK llvm-strip')
                    stripped = self.out/('reproduced-stripped-' + name)
                    proc = subprocess.run([str(self.args.llvm_strip), '--strip-unneeded', '-o', str(stripped), str(build_file)],
                        capture_output=True, timeout=30)
                    require(proc.returncode == 0 and stripped.read_bytes() == actual,
                        'Library does not match exact NDK strip output: ' + name)
                    strip_records[name] = {'sourceSha256':expected, 'strippedSha256':sha(actual),
                        'toolSha256':sha(self.args.llvm_strip.read_bytes()), 'arguments':['--strip-unneeded']}
                library_identity[name] = sha(actual)
        service = self.root/'android/app/src/debug/java/app/foldgpt/NativeGnuProjectProbeService.java'
        self.save('provenance/NativeGnuProjectProbeService.java', service.read_bytes())
        derivation = strict_json((Path(__file__).parent/'derivation.json').read_bytes())
        self.save('provenance/derivation-at-collection.json', (Path(__file__).parent/'derivation.json').read_bytes())
        process_snapshot = self.processes(case, native)
        official = self.official_client(app + '/files/debian') if self.args.verify_official else {
            'status':'NOT_REQUESTED', 'scope':'No official client files opened'}
        # Re-read all collected fixture bytes and metadata after the long native hash work.
        for target, before in list(self.records.items()):
            require(self.info(target, private=not target.startswith('/data/app/'))
                == {key:value for key,value in before.items() if key != 'sha256'}
                and self.native_hash(target) == before['sha256'], 'Collected file changed: ' + target)
        apk_after = self.apk_identity()
        security_after = self.security()
        require(apk_after == apk_before and security_before == security_after, 'Package or integrity state changed during collection')
        result = {'status':'PASS', 'schema':'foldgpt.gnu-project-independent-collection.v1',
            'collectedAtUtc':datetime.now(timezone.utc).isoformat(), 'scope':'Fixed offline native GNU project, not Desktop/model routing',
            'case':case, 'logs':logroot, 'uid':self.uid, 'tests':3, 'denials':8, 'projectFiles':len(artifacts),
            'archiveSha256':sha(artifacts['dist/app.pyz']), 'apk':apk_after, 'nativeLibraries':library_identity,
            'reproducedStripping':strip_records,
            'launcherBuildManifestSha256':sha(build_manifest_bytes), 'frozenSourceFilesVerified':len(manifest['files']),
            'derivationMatchesFrozenLauncher':derivation['launcherSha256'] == manifest['files']['sources/gnu-project.c'],
            'serviceSourceScope':'Current source snapshot only; installed APK digest identifies compiled service, not a reproducible source-to-DEX proof',
            'security':security_after, 'processSnapshot':process_snapshot, 'officialClient':official,
            'fileObservations':self.records,
            'limits':['Denials and historical ECHILD are native fixture observations, not replayed by collector.',
                'No model request, UI project, production policy, TTY, network-enabled build or arbitrary-workload qualification.',
                'Boot indicators are current observations, not a contractual warranty statement.']}
        (self.out/'verification.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        return result

    def official_client(self, rootfs):
        source = rootfs + '/var/lib/dpkg/info/chatgpt.md5sums'
        original = self.command('cat', source).stdout
        self.save('official-client/installed-md5sums', original)
        trusted_inventory = None
        critical_from_package = {}
        release = None
        if self.args.official_deb:
            package = self.args.official_deb
            digest = hashlib.sha256()
            with package.open('rb') as stream:
                while chunk := stream.read(4*1024*1024):
                    digest.update(chunk)
            with package.open('rb') as stream:
                require(stream.read(8) == b'!<arch>\n', 'Invalid supplied Debian archive')
                while header := stream.read(60):
                    require(len(header) == 60 and header[58:] == b'`\n', 'Invalid ar header')
                    name = header[:16].decode().strip().rstrip('/')
                    size = int(header[48:58])
                    if name == 'control.tar.xz':
                        require(size <= 8*1024*1024, 'Oversized Debian control archive')
                        with tarfile.open(fileobj=io.BytesIO(stream.read(size)), mode='r:xz') as control:
                            members = {m.name.removeprefix('./'):m for m in control.getmembers()}
                            package_control = control.extractfile(members['control']).read()
                        self.save('official-client/supplied-package-control', package_control)
                        if size % 2:
                            stream.read(1)
                        continue
                    if name == 'data.tar.xz':
                        trusted_entries = {}
                        with tarfile.open(fileobj=stream, mode='r|xz') as payload:
                            for member in payload:
                                member_name = member.name.removeprefix('./')
                                if not member.isfile():
                                    continue
                                relative(member_name)
                                require(member_name not in trusted_entries, 'Duplicate regular release path')
                                member_md5, member_sha = hashlib.md5(), hashlib.sha256()
                                with payload.extractfile(member) as data:
                                    while chunk := data.read(4*1024*1024):
                                        member_md5.update(chunk)
                                        member_sha.update(chunk)
                                trusted_entries[member_name] = member_md5.hexdigest()
                                if member_name in ('usr/lib/chatgpt/ChatGPT','usr/lib/chatgpt/resources/app.asar',
                                        'usr/lib/chatgpt/resources/codex'):
                                    critical_from_package[member_name] = member_sha.hexdigest()
                        trusted_inventory = ''.join(value + '  ' + key + '\n' for key,value in sorted(trusted_entries.items())).encode()
                        self.save('official-client/supplied-package-derived-md5sums', trusted_inventory)
                        break
                    stream.seek(size + size % 2, 1)
            require(trusted_inventory is not None and sorted(trusted_inventory.splitlines()) == sorted(original.splitlines()),
                'Installed package inventory differs from supplied historical release')
            versions = re.findall(rb'^Version: (.+)$', package_control, re.M)
            require(len(versions) == 1, 'Missing supplied package version')
            release = {'path':str(package), 'sha256':digest.hexdigest(), 'version':versions[0].decode(),
                'scope':'Independent local historical Debian artifact; publisher authentication is not established by this collector.'}
        lines = original.decode().splitlines()
        require(1 <= len(lines) <= 20000, 'Unbounded client package inventory')
        manifest = []
        for line in lines:
            match = re.fullmatch(r'([0-9a-f]{32})  (.+)', line)
            require(match is not None, 'Invalid installed md5sums')
            name = match[2]
            relative(name)
            require(name.startswith(('usr/lib/chatgpt/', 'usr/share/', 'etc/apparmor.d/')),
                'Package inventory refers outside client payload')
            manifest.append(match[1] + '  ' + rootfs + '/' + name)
        # Native Android checker hashes files. It runs no client or PRoot binary.
        checked = self.command('sh', '-c', 'cd ' + shlex.quote(rootfs)
            + ' && md5sum -c var/lib/dpkg/info/chatgpt.md5sums', timeout=60, check=False)
        self.save('official-client/native-md5-check.txt', checked.stdout)
        self.save('official-client/native-md5-check.stderr', checked.stderr)
        require(checked.returncode == 0 and not checked.stderr
            and len(checked.stdout.decode().splitlines()) == len(lines)
            and all(line.endswith(': OK') for line in checked.stdout.decode().splitlines()), 'Official package files differ from installed inventory')
        require(self.command('cat', source).stdout == original, 'Installed client inventory changed during verification')
        critical = {name:self.native_hash(rootfs+'/'+name) for name in
            ('usr/lib/chatgpt/ChatGPT','usr/lib/chatgpt/resources/app.asar','usr/lib/chatgpt/resources/codex')}
        if self.args.official_deb:
            require(critical == critical_from_package, 'Critical installed client SHA256 differs from historical package')
        return {'status':'PASS', 'files':len(lines), 'manifestSha256':sha(original), 'criticalSha256':critical,
            'suppliedHistoricalPackage':release,
            'scope':'Native bytes match installed dpkg MD5 inventory and supplied historical inventory when present; not behavioral integrity.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', default='adb')
    for name in ('serial','log','fixture'):
        parser.add_argument('--'+name, required=True)
    for name in ('build','native-build'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-official', action='store_true')
    parser.add_argument('--official-deb', type=Path)
    parser.add_argument('--llvm-strip', type=Path)
    args = parser.parse_args()
    collector = Collector(args)
    try:
        result = collector.collect()
        print(json.dumps({key:result[key] for key in ('status','tests','denials','projectFiles','archiveSha256','apk')}))
        print('evidence=' + str(collector.out))
    except Exception as error:
        (collector.out/'failure.json').write_text(json.dumps({'status':'FAIL', 'error':str(error)}, indent=2)+'\n', encoding='utf-8')
        raise
    finally:
        (collector.out/'read-commands.json').write_text(json.dumps(collector.commands, indent=2)+'\n', encoding='utf-8')


if __name__ == '__main__':
    main()
