"""Assemble a provenance-recorded FoldGPT Linux ARM64 workspace distribution.

Portable OpenAI components come from the user's installed runtime. Native npm
modules and Python wheels are acquired for Linux ARM64, never renamed Windows
binaries. The two language engines are copied from the installed Debian guest.
This does not publish any third-party package or use account credentials.
"""
import argparse
import base64
import gzip
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[2]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--serial', required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    out.relative_to(ROOT / 'work')
    out.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve(strict=True)
    original = json.loads((source / 'runtime.json').read_text())
    if original['bundleVersion'] != '26.904.11930' or original['artifactToolVersion'] != '2.8.59':
        raise ValueError('The reviewed portable source version differs')
    stage = out / 'codex-primary-runtime'
    stage.mkdir(exist_ok=True)
    deps = stage / 'dependencies'
    downloads = out / 'downloads'
    downloads.mkdir(exist_ok=True)
    receipt = {'schema': 'foldgpt.workspace-build.v1', 'portableSource': str(source),
               'portableSourceMetadata': original, 'acquisitions': []}

    def acquire(url, filename, expected=None, algorithm='sha256'):
        path = downloads / filename
        if not path.exists():
            print('Download ' + filename, flush=True)
            with urllib.request.urlopen(url, timeout=90) as remote, path.open('xb') as stream:
                shutil.copyfileobj(remote, stream)
        data = path.read_bytes()
        digest = hashlib.new(algorithm, data).digest()
        if expected is not None and digest != expected:
            raise ValueError('Download checksum differs: ' + filename)
        receipt['acquisitions'].append({'url': url, 'file': filename, 'sha256': sha(data),
                                        'verifiedAlgorithm': algorithm if expected else None})
        return data

    def npm(name, version, destination):
        url = 'https://registry.npmjs.org/' + name.replace('/', '%2f') + '/' + version
        metadata = json.loads(acquire(url, name.replace('/', '_') + '-' + version + '.json'))
        algorithm, digest = metadata['dist']['integrity'].split('-', 1)
        data = acquire(metadata['dist']['tarball'], name.replace('/', '_') + '-' + version + '.tgz',
                       base64.b64decode(digest), algorithm)
        destination.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
            for item in archive:
                parts = Path(item.name).parts
                if not parts or parts[0] != 'package' or '..' in parts:
                    raise ValueError('Unexpected npm archive member')
                path = destination.joinpath(*parts[1:])
                if item.isdir():
                    path.mkdir(parents=True, exist_ok=True)
                elif item.isfile():
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(archive.extractfile(item).read())
                else:
                    raise ValueError('Unsupported npm archive entry')

    modules = deps / 'node/node_modules'
    if not modules.exists():
        print('Copy portable Node packages', flush=True)
        shutil.copytree(source / 'dependencies/node/node_modules', modules,
                        ignore=shutil.ignore_patterns('*win32*', '*darwin*', '*.exe', '*.dll', '*.node'))
    npm('@napi-rs/canvas-linux-arm64-gnu', '0.1.100', modules / '@napi-rs/canvas-linux-arm64-gnu')
    sharp_dependencies = json.loads((modules / 'sharp/package.json').read_text())['optionalDependencies']
    for name in ('@img/sharp-linux-arm64', '@img/sharp-libvips-linux-arm64'):
        npm(name, sharp_dependencies[name], modules / name)
    skia = modules / '@oai/artifact-tool/node_modules/skia-canvas'
    config = json.loads((skia / 'package.json').read_text())
    filename = 'linux-arm64-glibc.gz'
    data = acquire('https://github.com/samizdatco/skia-canvas/releases/download/v' + config['version'] + '/' + filename,
                   'skia-canvas-' + config['version'] + '-' + filename,
                   bytes.fromhex(config['prebuild'][filename].split(':', 1)[1]))
    (skia / 'lib/skia.node').write_bytes(gzip.decompress(data))

    library = deps / 'python/local/lib/python3.13/dist-packages'
    library.mkdir(parents=True, exist_ok=True)
    python_source = source / 'dependencies/python/Lib/site-packages'
    requirements = []
    for path in sorted(python_source.glob('*.dist-info/METADATA')):
        fields = dict(line.split(': ', 1) for line in path.read_text(encoding='utf-8').splitlines()
                      if line.startswith(('Name: ', 'Version: ')))
        if fields['Name'].lower().replace('-', '_') == 'artifact_tool_v2':
            continue
        requirements.append(fields['Name'] + '==' + fields['Version'])
    requirements_path = out / 'python-requirements.txt'
    requirements_path.write_text('\n'.join(requirements) + '\n')
    print('Install Linux ARM64 Python wheels', flush=True)
    subprocess.run(['uv', 'pip', 'install', '--target', str(library), '--python-version', '3.13',
                    '--python-platform', 'aarch64-manylinux_2_28', '--only-binary', ':all:',
                    '--link-mode', 'copy', '--cache-dir', str(out / 'uv-cache'),
                    '--requirements', str(requirements_path)], check=True)
    for name in ('artifact_tool_v2', 'artifact_tool_v2-2.8.59.dist-info'):
        if not (library / name).exists():
            shutil.copytree(python_source / name, library / name,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    if not (stage / 'plugins').exists():
        shutil.copytree(source / 'plugins', stage / 'plugins')

    print('Acquire installed Linux ARM64 language engines', flush=True)
    adb = ['adb', '-s', args.serial, 'exec-out', 'run-as', 'app.foldgpt']
    for remote, local in [
        ('usr/lib/chatgpt/resources/cua_node/bin/node', deps / 'node/bin/node'),
        ('usr/bin/python3.13', deps / 'python/bin/python3'),
    ]:
        local.parent.mkdir(parents=True, exist_ok=True)
        data = subprocess.check_output(adb + ['cat', 'files/debian/' + remote], timeout=45)
        if data[:4] != b'\x7fELF' or int.from_bytes(data[18:20], 'little') != 183:
            raise ValueError('Not a Linux ARM64 ELF: ' + remote)
        local.write_bytes(data)
        receipt.setdefault('guestEngines', []).append({'path': remote, 'sha256': sha(data)})
    stdlib = deps / 'python/lib/python3.13'
    if not (stdlib / 'encodings/__init__.py').exists():
        data = subprocess.check_output(adb + ['tar', '-cf', '-', '-C', 'files/debian/usr/lib', 'python3.13'], timeout=45)
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            for item in archive:
                parts = Path(item.name).parts
                if '..' in parts or not parts or parts[0] != 'python3.13':
                    raise ValueError('Unsafe stdlib archive entry')
                if not item.isfile() or '__pycache__' in parts or item.name.endswith('.pyc'):
                    continue
                target = deps / 'python/lib' / item.name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.extractfile(item).read())
    # Pack only authentic files. Writable caches and compiled host bytecode are
    # excluded at packing time; all modes and archive paths are set explicitly.
    receipt['status'] = 'assembled-not-yet-device-validated'
    (out / 'build-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps({'stage': str(stage), 'status': receipt['status']}))


if __name__ == '__main__':
    main()
