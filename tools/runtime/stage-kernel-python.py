"""Stage and independently verify the fixed diagnostic Python runtime.

Reads PackageManager information collected by the installed diagnostic app.
Creates only the previously absent v2/python directory. No native worker runs.
The shell-owned runtime is a verified diagnostic input, not an immutable
production boundary against other processes sharing the shell UID.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import tarfile

BASE = '/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2'
PACKAGE = 'app.foldgpt.kernelqualification'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--stage', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--package', choices=(PACKAGE, 'app.foldgpt.shizukuprobe'), default=PACKAGE)
    parser.add_argument('--lab-report-version', choices=(2, 3, 4), type=int, default=2,
                        help='Fixed laboratory report generation; does not change the native fixture')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {'schema': 'foldgpt.fixed-kernel-python-staging.v1', 'verified': False, 'base': BASE}
    adb = [args.adb, '-s', args.serial]

    def run(name, command, input_bytes=None):
        result = subprocess.run(adb + ['shell', '-T', shlex.join(command)], input=input_bytes,
                                capture_output=True, timeout=60)
        (args.output / (name + '.stdout')).write_bytes(result.stdout)
        (args.output / (name + '.stderr')).write_bytes(result.stderr)
        if result.returncode or result.stderr:
            raise RuntimeError('Device staging/verification failed at ' + name)
        return result.stdout

    try:
        info_file = (f'files/kernel-v{args.lab_report_version}/package-info.json'
                     if args.package == 'app.foldgpt.shizukuprobe' else 'files/package-info.json')
        info = json.loads(run('package-info', ['run-as', args.package, 'cat', info_file]))
        native_directory = info['nativeLibraryDir']
        if (not native_directory.startswith('/data/app/') or not native_directory.endswith('/lib/arm64')
                or str(PurePosixPath(native_directory)) != native_directory or '..' in PurePosixPath(native_directory).parts
                or not info['sourceDir'].startswith(str(PurePosixPath(native_directory).parents[1]) + '/')):
            raise ValueError('Unexpected actual PackageManager paths')
        report['packageInfo'] = info
        stage = args.stage.resolve(strict=True)
        manifest = json.loads((stage / 'assets/foldgpt-python-runtime.json').read_text())
        config = json.loads((stage / 'assets/foldgpt-executor-deployment.json').read_text())
        if config['pythonRuntime']['path'] != BASE + '/python' or config['packageName'] != args.package:
            raise ValueError('Staged Python data belong to a different diagnostic')
        files, aliases, directories = {}, {}, {'.'}

        def path_name(name):
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or str(path) != name or '\\' in name or name == '.':
                raise ValueError('Invalid Python manifest path')
            if name in files or name in aliases:
                raise ValueError('Duplicate runtime name')
            directories.update(str(parent) for parent in path.parents)
            return name

        for entry in manifest['dataFiles']:
            name = path_name(entry['path'])
            data = (stage / 'staged-python-data' / name).read_bytes()
            if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
                raise ValueError('Unverified Python data')
            files[name] = data
        for entry in manifest['runtimeAliases']:
            name = path_name(entry['path'])
            library = entry['nativeLibrary']
            if PurePosixPath(library).name != library or config['nativeLibraries'].get(library) != entry['sha256']:
                raise ValueError('ELF alias does not identify its admitted package library')
            aliases[name] = native_directory + '/' + library
        if set(files) & directories or set(aliases) & directories:
            raise ValueError('Runtime entry conflicts with a directory')
        native_names = sorted(config['nativeLibraries'])
        raw = run('installed-native-digests', ['sha256sum', *(native_directory + '/' + name for name in native_names)])
        observed = {}
        for line in raw.decode().splitlines():
            digest, path = line.split('  ', 1)
            observed[path] = digest
        if observed != {native_directory + '/' + name: config['nativeLibraries'][name] for name in native_names}:
            raise ValueError('Installed native bytes differ from the reviewed manifest')
        payload = args.output / 'python.tar.gz'
        # Android toybox ignored PAX linkpath and truncated absolute APK aliases
        # at 100 bytes. GNU LongLink records preserve these actual package paths.
        with tarfile.open(payload, 'w:gz', format=tarfile.GNU_FORMAT) as archive:
            for name in sorted(directories, key=lambda name: (name.count('/'), name)):
                if name == '.':
                    continue
                entry = tarfile.TarInfo(name)
                entry.type = tarfile.DIRTYPE
                entry.uid = entry.gid = 2000
                entry.mode = 0o700
                archive.addfile(entry)
            for name, data in files.items():
                entry = tarfile.TarInfo(name)
                entry.uid = entry.gid = 2000
                entry.mode = 0o600
                entry.size = len(data)
                archive.addfile(entry, io.BytesIO(data))
            for name, target in aliases.items():
                entry = tarfile.TarInfo(name)
                entry.uid = entry.gid = 2000
                entry.mode = 0o777
                entry.type = tarfile.SYMTYPE
                entry.linkname = target
                archive.addfile(entry)
        run('create-python', ['sh', '-c', 'umask 077\nmkdir -- ' + shlex.quote(BASE + '/python')])
        # ADB shell stdin truncated the compressed stream on the first device
        # preparation. The sync protocol preserves bytes; hash the remote file
        # before asking tar to read it. Never feed a binary runtime through sh.
        payload_hash = hashlib.file_digest(payload.open('rb'), 'sha256').hexdigest()
        remote_archive = BASE + '/python-payload-' + payload_hash + '.tar.gz'
        pushed = subprocess.run(adb + ['push', str(payload), remote_archive], capture_output=True, timeout=60)
        (args.output / 'push.stdout').write_bytes(pushed.stdout)
        (args.output / 'push.stderr').write_bytes(pushed.stderr)
        if pushed.returncode:
            raise RuntimeError('Runtime sync transfer failed')
        actual_hash = run('pushed-archive-hash', ['sha256sum', remote_archive]).decode().split()[0]
        if actual_hash != payload_hash:
            raise ValueError('Pushed runtime archive differs before extraction')
        run('extract-python', ['tar', '-xzf', remote_archive, '-C', BASE + '/python'])
        collected_archive = BASE + '/python-collected-' + payload_hash + '.tar.gz'
        run('archive-installed-python', ['tar', '-czf', collected_archive, '-C', BASE + '/python', '.'])
        pulled = subprocess.run(adb + ['pull', collected_archive, str(args.output / 'python-collected.tar.gz')],
                                capture_output=True, timeout=60)
        (args.output / 'pull.stdout').write_bytes(pulled.stdout)
        (args.output / 'pull.stderr').write_bytes(pulled.stderr)
        if pulled.returncode:
            raise RuntimeError('Independent runtime archive transfer failed')
        seen = set()
        with tarfile.open(args.output / 'python-collected.tar.gz') as archive:
            for entry in archive:
                name = entry.name.removeprefix('./').rstrip('/') or '.'
                if name in seen or entry.uid != 2000 or entry.gid != 2000:
                    raise ValueError('Duplicate or incorrectly owned installed runtime entry')
                seen.add(name)
                if entry.isdir():
                    if name not in directories or entry.mode != 0o700:
                        raise ValueError('Unexpected runtime directory')
                elif name in files:
                    if not entry.isfile() or entry.mode != 0o600 or archive.extractfile(entry).read() != files[name]:
                        raise ValueError('Installed Python data bytes/type/mode differ: ' + name)
                elif name in aliases:
                    if not entry.issym() or entry.linkname != aliases[name]:
                        raise ValueError('Installed Python alias differs')
                else:
                    raise ValueError('Unexpected installed runtime entry')
        if seen != directories | set(files) | set(aliases):
            raise ValueError('Installed runtime inventory is incomplete')
        report.update(verified=True, nativeLibraries=len(native_names), dataFiles=len(files),
                      aliases=len(aliases), directories=len(directories),
                      payloadSha256=hashlib.file_digest(payload.open('rb'), 'sha256').hexdigest(),
                      scope='Actual diagnostic runtime bytes and aliases; no native command launched')
    finally:
        (args.output / 'verification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
