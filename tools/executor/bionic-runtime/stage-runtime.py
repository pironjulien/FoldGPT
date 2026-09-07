"""Prepare an APK-owned ELF inventory and data assets, without building an APK.

Aliases are a declarative manifest, not symlinks written onto a device. A future
installer must resolve each target under its current nativeLibraryDir and verify
hashes, then protect the runtime outside the command workspace. No admission or
security claim follows from this packaging check alone.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath

HERE = Path(__file__).resolve().parent


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--python-archive', required=True, type=Path)
    parser.add_argument('--python-cli', required=True, type=Path)
    parser.add_argument('--bash', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    pinned = module('bionic_python_package', HERE / 'python-package.py')
    inspected = module('existing_android_elf_inspector', HERE.parent / 'stage-android-python.py')
    files = pinned.package(args.python_archive)
    args.output.mkdir(parents=True, exist_ok=False)
    jni = args.output / 'jniLibs/arm64-v8a'
    assets = args.output / 'assets/bionic-python'
    jni.mkdir(parents=True)
    records, aliases, blobs, data_records = [], [], {}, []

    def add_elf(name, data, origin):
        info = inspected.elf_info(data)
        sha = hashlib.sha256(data).hexdigest()
        if sha in blobs:
            return blobs[sha]
        if not (name.startswith('lib') and name.endswith('.so')):
            raise ValueError('JNI executable filename must use lib*.so')
        target = jni / name
        if target.exists():
            raise ValueError('JNI runtime name collision')
        target.write_bytes(data)
        blobs[sha] = name
        records.append({'name': name, 'origin': origin, 'sha256': sha, 'bytes': len(data), 'elf': info})
        return name

    # Preserve canonical DT_NEEDED names before deduplicating package aliases.
    canonical = ['libpython3.14.so', 'libcrypto_python.so', 'libssl_python.so', 'libsqlite3_python.so', 'libpython3.so']
    for name in canonical:
        add_elf(name, files['lib/' + name], 'official Python lib/' + name)
    data_count = data_bytes = 0
    for path, data in sorted(files.items()):
        if not path.startswith('lib/'):
            continue
        if data.startswith(b'\x7fELF'):
            sha = hashlib.sha256(data).hexdigest()
            name = add_elf('libfoldgpt_py_' + sha[:24] + '.so', data, 'official Python ' + path)
            aliases.append({'path': path, 'nativeLibrary': name, 'sha256': sha})
        else:
            target = assets / PurePosixPath(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            data_records.append({'path': path, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)})
            data_count += 1
            data_bytes += len(data)
    for path, name in [(args.python_cli, 'libfoldgpt_python_cli.so'), (args.bash, 'libfoldgpt_bash.so')]:
        data = path.read_bytes()
        info = inspected.elf_info(data)
        if info['interpreter'] != '/system/bin/linker64':
            raise ValueError('CLI is not a native Bionic dynamic executable')
        add_elf(name, data, str(path))
    # Every archived ELF name has a hash-exact APK representation.
    for alias in aliases:
        if hashlib.sha256((jni / alias['nativeLibrary']).read_bytes()).hexdigest() != alias['sha256']:
            raise ValueError('Runtime alias differs from the authenticated bytes')
    manifest = {
        'schema': 1, 'status': 'HOST_STAGED_NOT_ANDROID_EXECUTED', 'python': pinned.PIN,
        'nativeFiles': records, 'runtimeAliases': aliases, 'dataFiles': data_records,
        'summary': {'nativeFiles': len(records), 'nativeBytes': sum(x['bytes'] for x in records),
                    'runtimeAliases': len(aliases), 'dataFiles': data_count, 'dataBytes': data_bytes},
        'launchContract': {
            'shell': 'nativeLibraryDir/libfoldgpt_bash.so',
            'python': 'nativeLibraryDir/libfoldgpt_python_cli.so',
            'defaultPythonHome': 'Explicit build-time deployment-prefix.txt; must match admitted extracted assets/bionic-python directory',
            'PYTHONHOME': 'Optional ordinary CPython override, subject to the original managed policy',
            'linker': 'Python CLI DT_RUNPATH starts with its explicit deployment-prefix/lib, followed by $ORIGIN; direct DT_NEEDED for all four primary Python libraries. Verify the ELF matches the deployed prefix; an ORIGIN-only CLI fails under the admitted Samsung loader path.',
            'PATH': 'admitted command aliases resolving to APK-owned executables',
            'policy': 'Parent must apply original complete file/network policy before executing target',
        },
        'scope': 'Cross-compiled Bash/Python and full official library packaging; no sandbox or device validation',
    }
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps(manifest['summary']))


if __name__ == '__main__':
    main()
