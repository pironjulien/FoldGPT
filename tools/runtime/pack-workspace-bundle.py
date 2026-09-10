"""Package the assembled, truthfully branded ARM64 tools with integrity records."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

ROOT = Path(__file__).resolve().parents[2]
VERSION = '2026.09.09.2'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    output = args.bundle.resolve()
    output.relative_to(ROOT / 'work')
    stage = output / 'codex-primary-runtime'
    node = stage / 'dependencies/node'
    python = stage / 'dependencies/python'
    library = python / 'local/lib/python3.13/dist-packages'
    skia = node / 'node_modules/@oai/artifact-tool/node_modules/skia-canvas/lib/skia.node'
    target = library / 'artifact_tool_v2/bin/node_modules/skia-canvas/lib/skia.node'
    shutil.copyfile(skia, target)
    # The upstream Windows Python package includes its portable JS RPC server.
    # Launch exactly that implementation with the Linux ARM64 Node engine.
    (library / 'artifact_tool_v2/bin/artifact_tool_rpc_daemon').write_text(
        '#!/bin/sh\nset -eu\nhere=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec "$here/../../../../../../../node/bin/node" "$here/artifact_tool_rpc_daemon.js" "$@"\n',
        encoding='utf-8', newline='\n')
    (stage / 'checks').mkdir(exist_ok=True)
    for name in ('workspace-node-check.cjs', 'workspace-python-check.py', 'workspace-render-check.py'):
        shutil.copyfile(ROOT / 'tools/runtime' / name, stage / 'checks' / name)
    fallback = stage / 'dependencies/bin/fallback'
    fallback.mkdir(parents=True, exist_ok=True)
    override = stage / 'dependencies/bin/override'
    override.mkdir(exist_ok=True)
    (fallback / 'pnpm').write_text(
        '#!/bin/sh\nset -eu\nhere=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
        'exec "$here/../../node/bin/node" "$here/../../node/node_modules/pnpm/bin/pnpm.cjs" "$@"\n',
        encoding='utf-8', newline='\n')
    for name in ('git', 'pdftoppm', 'pdftotext', 'pdfinfo', 'libreoffice', 'soffice', 'heif-convert', 'JxrDecApp'):
        if name in ('libreoffice', 'soffice'):
            shutil.copyfile(ROOT / 'tools/runtime/foldgpt-soffice.sh', fallback / name)
        else:
            (fallback / name).write_text('#!/bin/sh\nexec /usr/bin/' + name + ' "$@"\n', encoding='utf-8', newline='\n')
    # Official Linux document helpers deliberately resolve the override bin
    # directory. Supply the real adapters there as well as in the CLI fallback.
    for wrapper in fallback.iterdir():
        if wrapper.is_file():
            shutil.copyfile(wrapper, override / wrapper.name)
    metadata = {'provider': 'FoldGPT', 'bundleFormatVersion': 2, 'bundleVersion': 'FoldGPT-ARM64-' + VERSION,
                'artifactToolVersion': '2.8.59', 'nodeVersion': 'v24.19.0', 'pythonVersion': '3.13.5',
                'pnpmVersion': '11.19.0', 'targetPlatform': 'linux', 'targetArch': 'arm64',
                'bundledPlugins': ['plugins/openai-primary-runtime'], 'bundledSkills': [], 'skillsToRemove': [],
                'nativeDependencies': ['git', 'poppler', 'libheif', 'jxrlib', 'libreoffice'],
                'libreOfficeVersion': '25.2.3.2',
                'hostRequirements': 'FoldGPT Debian 13 ARM64 with authenticated Debian native packages',
                'provenance': 'Portable OpenAI 26.904.11930 components; Linux ARM64 npm modules and Python wheels; guest language engines.'}
    (stage / 'runtime.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
    build = json.loads((output / 'build-receipt.json').read_text())
    (stage / 'foldgpt-provenance.json').write_text(json.dumps(build, indent=2) + '\n', encoding='utf-8')
    files = []
    critical = []
    for file in sorted(stage.rglob('*')):
        if not file.is_file() or file.name == 'foldgpt-integrity.json':
            continue
        relative = file.relative_to(stage).as_posix()
        if '__pycache__' in file.parts or file.suffix in ('.pyc', '.exe', '.dll'):
            continue
        data = file.read_bytes()
        if data.startswith((b'MZ', b'\xcf\xfa\xed\xfe', b'\xfe\xed\xfa\xcf')):
            raise ValueError('Foreign native executable in ARM64 bundle: ' + relative)
        if data.startswith(b'\x7fELF') and int.from_bytes(data[18:20], 'little') != 183:
            raise ValueError('Non-ARM64 ELF in bundle: ' + relative)
        item = {'path': relative, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
        files.append(item)
        if (data.startswith(b'\x7fELF') or relative.startswith(('checks/', 'dependencies/bin/')) or
                file.name in ('runtime.json', 'artifact_tool_rpc_daemon', 'artifact_tool_rpc_daemon.js', 'artifact_tool.mjs')):
            critical.append(item)
    (stage / 'foldgpt-integrity.json').write_text(json.dumps({'schema': 'foldgpt.workspace-integrity.v1',
        'requiredFiles': critical}, indent=2) + '\n', encoding='utf-8')
    inventory = {'metadata': metadata, 'files': files}
    (output / 'inventory.json').write_text(json.dumps(inventory, indent=2), encoding='utf-8')
    if args.prepare_only:
        print(json.dumps({'prepared': str(stage), 'files': len(files), 'requiredFiles': len(critical)}))
        return
    archive = output / ('foldgpt-workspace-' + VERSION + '.tar.gz')
    def archive_filter(info):
        relative = Path(info.name)
        if '__pycache__' in relative.parts or relative.suffix in ('.pyc', '.exe', '.dll'):
            return None
        if not (info.isfile() or info.isdir()):
            raise ValueError('The bundle contains an unexpected link: ' + info.name)
        info.uid = info.gid = 0
        info.uname = info.gname = ''
        info.mtime = 0
        # Executable scripts/binaries need an execute bit after a Windows build.
        info.mode = 0o755 if info.isdir() or '/bin/' in info.name else 0o644
        return info
    with tarfile.open(archive, 'w:gz', compresslevel=3) as stream:
        stream.add(stage, arcname='codex-primary-runtime', filter=archive_filter)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    provider = {'schema': 'foldgpt.workspace-provider.v1', 'source': 'foldgpt-local', 'bundleVersion': metadata['bundleVersion'],
                'archivePath': '/usr/local/share/foldgpt/workspace-runtime/' + archive.name,
                'archiveSha256': digest, 'targetPlatform': 'linux', 'targetArch': 'arm64'}
    (output / 'provider.json').write_text(json.dumps(provider, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'sha256': digest,
                      'files': len(files), 'requiredFiles': len(critical)}))


if __name__ == '__main__':
    main()
