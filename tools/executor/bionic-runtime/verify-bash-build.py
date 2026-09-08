"""Attest two real Bionic Bash builds, their full features, prefixes and imports."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

HERE = Path(__file__).resolve().parent
LEGACY_PREFIX = b'/data/local/tmp/foldgpt-shizuku-lab'


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def symbols(text):
    result = []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) >= 8 and re.fullmatch(r'[0-9]+:', fields[0]):
            result.append({'name': fields[7].split('@', 1)[0], 'binding': fields[4], 'index': fields[6]})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--ndk', required=True, type=Path)
    args = parser.parse_args()
    require(not sys.flags.optimize, 'ELF checks require normal Python assertions')
    output, ndk = args.output.resolve(strict=True), args.ndk.resolve(strict=True)
    manifest = json.loads((output / 'source/source-manifest.json').read_bytes())
    require(manifest['androidPrefix'] == args.prefix, 'Prepared and compiled prefixes must agree')
    source = output / 'source/bash-5.3'
    recorded = {row['path'] for row in manifest['preparedFiles']}
    actual = {path.relative_to(source).as_posix() for path in source.rglob('*') if path.is_file()}
    require(recorded == actual and len(recorded) == len(manifest['preparedFiles']), 'Prepared source inventory changed')
    for row in manifest['preparedFiles']:
        path = source / row['path']
        require(path.stat().st_size == row['bytes'] and digest(path) == row['sha256'], 'Build modified prepared source: ' + row['path'])
        if args.prefix.encode() != LEGACY_PREFIX:
            require(LEGACY_PREFIX not in path.read_bytes(), 'Old laboratory prefix remains in source: ' + row['path'])
    binaries = [output / path for path in ('first/bash', 'second/bash', 'libfoldgpt_bash.so')]
    hashes = [digest(path) for path in binaries]
    require(len(set(hashes)) == 1, 'Two independently compiled Bash binaries differ')
    data = binaries[-1].read_bytes()
    prefix = args.prefix.encode()
    require(prefix == LEGACY_PREFIX or LEGACY_PREFIX not in data, 'Old laboratory prefix remains in ELF')
    suffixes = ('bin', 'bin:.', 'etc/profile', 'etc/bash.bashrc', 'etc/inputrc', 'etc/hosts',
                'tmp', 'var/tmp', 'share/locale', 'share/bashdb/bashdb-main.inc')
    for suffix in suffixes:
        require(prefix + b'/' + suffix.encode() + b'\0' in data, 'Compiled runtime path missing: ' + suffix)
    features = ('JOB_CONTROL', 'BRACE_EXPANSION', 'READLINE', 'HISTORY', 'PROCESS_SUBSTITUTION',
                'ARRAY_VARS', 'EXTENDED_GLOB', 'COND_COMMAND', 'PROGRAMMABLE_COMPLETION')
    for build in ('first', 'second'):
        config = (output / build / 'config.h').read_text()
        for feature in features:
            require(re.search(r'^#define\s+' + feature + r'\s+1\s*$', config, re.M), 'Bash feature absent: ' + feature)
        require(re.search(r'^#define\s+NO_MULTIBYTE_SUPPORT\b', config, re.M) is None, 'Multibyte support was disabled')
    spec = importlib.util.spec_from_file_location('foldgpt_bash_elf', HERE / 'shizuku-check-elf.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    elf = checker.check(binaries[-1])
    toolchain = ndk / 'toolchains/llvm/prebuilt/linux-x86_64'
    readelf = toolchain / 'bin/llvm-readelf'
    header = subprocess.check_output([str(readelf), '-h', '-l', '-d', '-n', str(binaries[-1])])
    (output / 'elf.txt').write_bytes(header)
    imported_raw = subprocess.check_output([str(readelf), '--dyn-symbols', '--wide', str(binaries[-1])])
    (output / 'imported-symbols.txt').write_bytes(imported_raw)
    imports = [row for row in symbols(imported_raw.decode()) if row['index'] == 'UND']
    exports, libraries = set(), []
    for name in elf['needed']:
        path = toolchain / 'sysroot/usr/lib/aarch64-linux-android/35' / name
        exported_raw = subprocess.check_output([str(readelf), '--dyn-symbols', '--wide', str(path)])
        (output / (name + '.exports.txt')).write_bytes(exported_raw)
        exports.update(row['name'] for row in symbols(exported_raw.decode()) if row['index'] != 'UND')
        libraries.append({'name': name, 'sha256': digest(path)})
    require(imports, 'Bash dynamic import table is unexpectedly empty')
    unresolved = [row for row in imports if row['binding'] != 'WEAK' and row['name'] not in exports]
    require(not unresolved, 'Bash imports unavailable Android API35 symbols: ' + json.dumps(unresolved))
    recipe_paths = [HERE / name for name in ('build-bash.sh', 'prepare-bash.py', 'verify-bash-build.py',
                                             'shizuku-check-elf.py', 'bash-inputs.json')]
    recipe_paths += sorted((HERE / 'termux-bash').glob('*.patch'))
    report = {'schema': 'foldgpt.native-bash-build.v1', 'androidExecuted': False,
              'scope': 'Two actual cross-compilations and static qualification only; no APK or device change.',
              'androidPrefix': args.prefix, 'ndk': '29.0.14206865', 'apiLevel': 35,
              'sourceDateEpoch': manifest['sourceDateEpoch'], 'sourceManifestSha256': digest(output / 'source/source-manifest.json'),
              'preparedSourceFilesVerified': len(recorded), 'sourceFilesUnchanged': True,
              'recipe': [{'path': path.relative_to(HERE).as_posix(), 'sha256': digest(path)} for path in recipe_paths],
              'compilerSha256': digest((toolchain / 'bin/clang').resolve(strict=True)),
              'readelfSha256': digest(readelf), 'ndkLinkLibraries': libraries,
              'reproducible': True, 'buildHashes': hashes[:2], 'elf': elf,
              'features': [*features, 'MULTIBYTE'], 'runtimePaths': [args.prefix + '/' + suffix for suffix in suffixes],
              'oldLaboratoryPrefixPresent': LEGACY_PREFIX in data,
              'importsVerified': imports,
              'unresolvedWeakImports': [row['name'] for row in imports if row['binding'] == 'WEAK' and row['name'] not in exports]}
    (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
    (output / 'SHA256SUMS').write_text(hashes[-1] + '  libfoldgpt_bash.so\n')
    print(json.dumps({'output': str(binaries[-1]), 'sha256': hashes[-1], 'reproducible': True,
                      'sourceFiles': len(recorded), 'imports': len(imports), 'androidPrefix': args.prefix,
                      'androidExecuted': False}))


if __name__ == '__main__':
    main()
