"""PC-only, exclusive staging for the new private-UID broker qualification."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
SERVICE = HERE.parent
REPO = SERVICE.parents[2]
BASE = '/data/user/0/app.foldgpt/files/runas-native-v2'
PACKAGE = 'app.foldgpt.runasbrokerqualification.v2'
STAGE = SERVICE / 'build/runasbrokerqualification-v2/stage-r2'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def pinned(path, expected):
    data = path.read_bytes()
    if sha(data) != expected:
        raise ValueError('Frozen input differs: ' + str(path))
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python-cli', type=Path, required=True)
    parser.add_argument('--python-cli-sha256', required=True)
    args = parser.parse_args()
    cli = pinned(args.python_cli, args.python_cli_sha256)
    if (BASE + '/python/lib:$ORIGIN').encode() not in cli:
        raise ValueError('CLI does not carry the actual private runtime prefix RUNPATH')
    runtime_root = REPO / 'downloads/shizuku-lab/runtime-stage-20260907'
    runtime = json.loads(pinned(runtime_root / 'manifest.json', 'bc9ddcfc598c875337af9d114fe0314be4dd09920dff27131f8c61278c95a5cc'))
    frozen = REPO / 'downloads/bionic-supervisor/foldgpt-bionic-supervisor-qKM94iHA'
    binary_inventory = pinned(frozen / 'BINARIES.sha256', 'a10ca7cc9ccb8c110cd7ca901d84b9066a7bf5ae73842935da88e1895437b40d')
    binaries = dict(reversed(row.split('  ', 1)) for row in binary_inventory.decode().splitlines())
    snapshot = REPO / 'downloads/native-app-server-host-v3-20260908'
    source_manifest = json.loads(pinned(snapshot / 'manifest.json', 'efe646543de659e75be3d39742d9fab63ef051770704971102bbef70bba0506a'))
    # Validate before creating outputs: a failed pin never changes a prior stage.
    native = {}
    for entry in runtime['nativeFiles']:
        name = entry['name']
        if name != 'libfoldgpt_python_cli.so':
            native[name] = pinned(runtime_root / 'jniLibs/arm64-v8a' / name, entry['sha256'])
    native['libfoldgpt_python_cli.so'] = cli
    for name in ('libfoldgpt_bionic_supervisor.so', 'libfoldgpt_native_files.so',
                 'libfoldgpt_native_file_handle.so', 'libfoldgpt_qualification_worker.so'):
        native[name] = pinned(frozen / name, binaries[name])
    worker_build = REPO / 'downloads/runas-worker-v2-20260908'
    native['libfoldgpt_qualification_worker.so'] = pinned(worker_build / 'libfoldgpt_qualification_worker.so', '0769ff3a7877cfcf13dc8cd49d5d3b865eef524718358e0e5b93951903166b3a')
    target_identity = json.loads((worker_build / 'build.json').read_text())['target']
    sources = {}
    for entry in source_manifest['files']:
        data = pinned(snapshot / entry['path'], entry['sha256'])
        if entry['path'].startswith('package/') and entry['path'].endswith('.py'):
            relative = entry['path'][len('package/'):]
            compile(data, relative, 'exec')
            sources[relative] = data
    bootstrap = (HERE / 'foldgpt_runas_broker.py').read_bytes()
    compile(bootstrap, 'foldgpt_runas_broker.py', 'exec')
    sources['foldgpt_runas_broker.py'] = bootstrap
    STAGE.mkdir(parents=True, exist_ok=False)
    assets = STAGE / 'assets'
    jni = STAGE / 'jniLibs/arm64-v8a'
    assets.mkdir(); jni.mkdir(parents=True)
    for name, data in native.items():
        (jni / name).write_bytes(data)
    # Transport contributes these files itself; the admission still pins them.
    transport = REPO / 'tools/executor/shizuku-lab/build/frozen-transport-jni/arm64-v8a'
    for name, expected in {
            'libfoldgpt_shizuku_transport.so': 'd4bb423a0dbe354485337d947bec486d6012d7b37a2ae0d73d0def8f26fe4ca6',
            'libfoldgpt_bionic_cwd.so': 'f65702d47130bf8f3098e7b9a5da5d982bbbc0d20cf50eeb61cc5fd489237157'}.items():
        native[name] = pinned(transport / name, expected)
    for relative, data in sources.items():
        target = assets / 'foldgpt-runas-broker' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    data_root = STAGE / 'staged-python-data'
    shutil.copytree(runtime_root / 'assets/bionic-python', data_root)
    for entry in runtime['dataFiles']:
        value = pinned(data_root / entry['path'], entry['sha256'])
        if len(value) != entry['bytes']:
            raise ValueError('Runtime data size differs')
    runtime_manifest = {key: runtime[key] for key in ('python', 'dataFiles', 'runtimeAliases')}
    (STAGE / 'runtime-manifest.json').write_text(json.dumps(runtime_manifest, indent=2) + '\n')
    lines = ['/* Generated exclusively from authenticated frozen input manifests. */',
             'static const struct runtime_file runtime_files[] = {']
    for entry in runtime['dataFiles']:
        lines.append('    {%s, %d, %s},' % (json.dumps(entry['path']), entry['bytes'], json.dumps(entry['sha256'])))
    lines += ['};', 'static const struct runtime_alias runtime_aliases[] = {']
    for entry in runtime['runtimeAliases']:
        if sha(native[entry['nativeLibrary']]) != entry['sha256']:
            raise ValueError('Runtime alias targets a different ELF')
        lines.append('    {%s, %s},' % (json.dumps(entry['path']), json.dumps(entry['nativeLibrary'])))
    lines += ['};', 'static const struct runtime_file native_files[] = {']
    for name, data in sorted(native.items()):
        lines.append('    {%s, %d, %s},' % (json.dumps(name), len(data), json.dumps(sha(data))))
    lines += ['};', '']
    (STAGE / 'runtime-inventory.h').write_text('\n'.join(lines), encoding='ascii')
    config = {'schema': 'foldgpt.runas-broker-config.v2', 'package': PACKAGE, 'target': 'app.foldgpt', 'base': BASE,
              'nativeLibraries': {name: sha(data) for name, data in sorted(native.items())},
              'qualificationUid': target_identity['uid'], 'targetApkSha256': target_identity['apkSha256'], 'runtimeFiles': len(runtime['dataFiles']), 'runtimeAliases': len(runtime['runtimeAliases'])}
    (assets / 'foldgpt-runas-broker-config.json').write_text(json.dumps(config, indent=2) + '\n')
    inventory = {'schema': 'foldgpt.runas-broker-build.v2', 'package': PACKAGE, 'base': BASE, 'androidExecuted': False,
                 'pythonCliSha256': sha(cli), 'runnerSha256': sha(native['libfoldgpt_bionic_supervisor.so']),
                 'files': [{'path': path.relative_to(STAGE).as_posix(), 'bytes': path.stat().st_size,
                            'sha256': sha(path.read_bytes())} for path in sorted(STAGE.rglob('*')) if path.is_file()]}
    (STAGE / 'build-inventory.json').write_text(json.dumps(inventory, indent=2) + '\n')
    print(json.dumps({'stage': str(STAGE), 'files': len(inventory['files']), 'native': len(native),
                      'data': len(runtime['dataFiles']), 'aliases': len(runtime['runtimeAliases'])}, indent=2))


if __name__ == '__main__':
    main()
