"""Fixed Android execution of the native managed-acquisition conformance suite.

The debug service supplies APK-owned programs and a new private directory.
No account, profile, model command, remote policy or activation is involved.
"""
import argparse
import json
import os
from pathlib import Path
import runpy
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.native_files_rpc_fixture import file_hash, observation, require


def main():
    def terminate(_number, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt('Android supervisor requested cleanup')

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runner', type=Path, required=True)
    parser.add_argument('--fixture', type=Path, required=True)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--uid', type=int, required=True)
    parser.add_argument('--address-space-bytes', type=int, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve(strict=True)
    require(sys.platform == 'android' and args.uid == os.getuid() and args.uid > 0,
            'The fixture requires native Android Python in the actual app UID')
    info = evidence.stat()
    require(info.st_uid == args.uid and info.st_mode & 0o077 == 0, 'Fixture directory is not app-private')
    before = observation(android_uid=args.uid)
    (evidence / 'android-context-before.json').write_text(json.dumps(before, indent=2) + '\n')
    parent = evidence / 'cases'
    parent.mkdir(mode=0o700)
    suite = Path(__file__).with_name('native-managed-test.py')
    original_argv = sys.argv
    try:
        sys.argv = [str(suite), '--runner', str(args.runner.resolve(strict=True)),
                    '--fixture', str(args.fixture.resolve(strict=True)), '--parent', str(parent),
                    '--evidence', str(evidence / 'kernel-tests.json'),
                    '--address-space-bytes', str(args.address_space_bytes)]
        try:
            runpy.run_path(str(suite), run_name='__main__')
        except SystemExit as result:
            require(result.code == 0, 'The actual native acquisition conformance suite failed')
    finally:
        sys.argv = original_argv
    matrix = json.loads((evidence / 'kernel-tests.json').read_bytes())
    require(matrix.get('successful') is True and matrix.get('uid') == args.uid
            and matrix.get('observations'), 'Native suite evidence is incomplete')
    require(not list(parent.iterdir()), 'Native suite left private case workspaces behind')
    after = observation(android_uid=args.uid)
    result = {'schema': 'foldgpt.native-managed-android.v1', 'status': 'PASS',
              'uid': args.uid, 'observations': len(matrix['observations']),
              'runnerSha256': file_hash(args.runner), 'fixtureSha256': file_hash(args.fixture),
              'suiteSha256': file_hash(suite), 'kernelTestsSha256': file_hash(evidence / 'kernel-tests.json'),
              'observationBefore': before, 'observationAfter': after,
              'addressSpaceBytes': args.address_space_bytes,
              'limit': 'Static native acquisition profile; no general shell, TTY, network or Desktop routing'}
    (evidence / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'observations': result['observations']}), flush=True)


if __name__ == '__main__':
    main()
