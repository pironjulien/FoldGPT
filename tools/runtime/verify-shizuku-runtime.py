"""Independently collect the fixed shell runtime's bytes, owners and ELF aliases."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--payload', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError('Preserve prior verification reports')
    manifest = json.loads(args.payload.read_text())
    result = subprocess.run([args.adb, '-s', args.serial, 'exec-out', 'tar', '-cf', '-',
                             '-C', '/data/local/tmp/foldgpt-shizuku-lab', 'native', 'python'],
                            capture_output=True, timeout=60)
    if result.returncode or result.stderr:
        raise ValueError('Runtime collection failed: ' + result.stderr.decode(errors='replace'))
    records = []
    with tarfile.open(fileobj=io.BytesIO(result.stdout)) as archive:
        entries = archive.getmembers()
        observed = {x.name.rstrip('/'): x for x in entries}
        if len(observed) != len(entries):
            raise ValueError('Duplicate path in device archive')
        expected = {x['path'] for x in manifest['records']}
        if any(not x.isdir() and name not in expected for name, x in observed.items()):
            raise ValueError('Unexpected runtime entry')
        for name, entry in observed.items():
            if entry.uid != 2000:
                raise ValueError('Runtime is not owned by shell: ' + name)
            # Linux symlink mode bits are not access controls. The containing
            # directory and exact link target are the relevant checks.
            if not entry.issym() and entry.mode & 0o022:
                raise ValueError('Runtime entry writable by other identities: ' + name)
        for item in manifest['records']:
            entry = observed[item['path']]
            if item['type'] == 'symlink':
                if not entry.issym() or entry.linkname != item['target']:
                    raise ValueError('Runtime alias differs: ' + item['path'])
            else:
                if not entry.isfile():
                    raise ValueError('Runtime file type differs: ' + item['path'])
                data = archive.extractfile(entry).read()
                if hashlib.sha256(data).hexdigest() != item['sha256']:
                    raise ValueError('Runtime file bytes differ: ' + item['path'])
                if entry.mode != int(item['mode'], 8):
                    raise ValueError('Runtime file mode differs: ' + item['path'])
            records.append({'path': item['path'], 'uid': entry.uid,
                            'mode': oct(entry.mode), 'type': item['type']})
    report = {'schema': 'foldgpt.shizuku.runtime-verification.v1', 'state': 'verified',
              'filesAndAliases': len(records), 'records': records,
              'runtimePayloadSha256': manifest['payloadSha256'],
              'scope': 'Device bytes and symlinks; no execution or sandbox assertion'}
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps({k: v for k, v in report.items() if k != 'records'}))


if __name__ == '__main__':
    main()
