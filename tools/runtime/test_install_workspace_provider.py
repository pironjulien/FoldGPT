"""Real filesystem/crash regressions using generated ASARs, never client payloads."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name('install-workspace-provider.py')
SESSION = SCRIPT.parents[2] / 'runtime/guest/foldgpt-session.sh'
if os.name == 'posix':
    SPEC = importlib.util.spec_from_file_location('workspace_adapter', SCRIPT)
    ADAPTER = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(ADAPTER)


def fixture():
    module = b'let xB,PB,QB,hB,fB; // independently generated test module\n'
    other = b'Unchanged fixture member\n' * 100001
    header = {'files': {
        'module.js': {'size': len(module), 'offset': '0', 'integrity': {
            'algorithm': 'SHA256', 'hash': hashlib.sha256(module).hexdigest(),
            'blockSize': 32, 'blocks': [hashlib.sha256(module[i:i + 32]).hexdigest()
                                       for i in range(0, len(module), 32)]}},
        'other.dat': {'size': len(other), 'offset': str(len(module))},
        'external.node': {'size': 17, 'unpacked': True},
    }}
    raw = json.dumps(header, separators=(',', ':')).encode()
    padded = raw + b'\0' * (-len(raw) % 4)
    pickle = struct.pack('<II', len(padded) + 4, len(raw)) + padded
    source = struct.pack('<II', 4, len(pickle)) + pickle + module + other
    known = {hashlib.sha256(source).hexdigest(): {
        'module': 'module.js', 'sha256': hashlib.sha256(module).hexdigest(),
        'names': ['xB', 'PB', 'QB', 'hB', 'fB']}}
    return source, known


def tree(directory):
    return {str(item.relative_to(directory)): (
        item.lstat().st_mode, item.lstat().st_ino, item.lstat().st_size,
        item.lstat().st_mtime_ns, item.read_bytes() if item.is_file() else None)
        for item in directory.rglob('*')}


@unittest.skipUnless(os.name == 'posix', 'Production helper requires POSIX file descriptors, locks and fsync')
class WorkspaceAdapterTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='foldgpt-adapter-test-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.asar = self.root / 'app.asar'
        self.state = self.root / 'state'
        self.source, known = fixture()
        self.asar.write_bytes(self.source)
        self.asar.chmod(0o640)
        self.known_patch = mock.patch.dict(ADAPTER.KNOWN, known, clear=True)
        self.known_patch.start()
        self.addCleanup(self.known_patch.stop)
        self.official = next(iter(known))
        self.backup = self.state / (self.official + '.official.asar')
        self.receipt = self.state / 'client-adapter.json'

    def test_unknown_client_refused_without_creating_state_or_touching_context(self):
        self.asar.write_bytes(b'Unknown client revision')
        (self.root / 'AGENTS.md').write_text('Preserve user context')
        before = tree(self.root)
        for check_only in (True, False):
            with self.assertRaisesRegex(ValueError, 'not reviewed'):
                ADAPTER.install(self.asar, self.state, check_only)
            self.assertEqual(before, tree(self.root))

    def test_forged_receipt_cannot_authorize_unknown_bytes(self):
        self.asar.write_bytes(b'Unknown client with a matching forged receipt')
        self.state.mkdir()
        self.receipt.write_text(json.dumps({'adaptedSha256': ADAPTER.digest(self.asar.read_bytes())}))
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, 'not reviewed'):
            ADAPTER.install(self.asar, self.state)
        self.assertEqual(before, tree(self.root))

    def test_known_original_preflight_is_read_only_and_streaming_preserves_members(self):
        before = tree(self.root)
        result = ADAPTER.install(self.asar, self.state, True)
        self.assertEqual('original', result['clientState'])
        self.assertEqual(before, tree(self.root))
        adapted, _ = ADAPTER.adapt(self.source)
        _, header_size, _, json_size = struct.unpack_from('<IIII', adapted)
        header = json.loads(adapted[16:16 + json_size])
        base = 8 + header_size
        other = header['files']['other.dat']
        self.assertEqual(b'Unchanged fixture member\n' * 100001,
                         adapted[base + int(other['offset']):base + int(other['offset']) + other['size']])
        self.assertEqual({'size': 17, 'unpacked': True}, header['files']['external.node'])
        member = header['files']['module.js']
        content = adapted[base:base + member['size']]
        self.assertIn(b'FoldGPT workspace provider v1', content)
        self.assertEqual(ADAPTER.digest(content), member['integrity']['hash'])
        self.assertEqual([ADAPTER.digest(content[i:i + 32]) for i in range(0, len(content), 32)],
                         member['integrity']['blocks'])

    def test_stream_plan_never_reads_a_whole_payload(self):
        class BoundedReads(io.BytesIO):
            def read(self, size=-1):
                if not 0 <= size <= ADAPTER.CHUNK:
                    raise AssertionError('Unbounded archive read')
                return super().read(size)
        stream = BoundedReads(self.source)
        plan, _ = ADAPTER.adaptation_plan(stream, ADAPTER.stream_digest(stream))
        result = b''.join(ADAPTER.plan_chunks(stream, plan))
        self.assertEqual(ADAPTER.adapt(self.source)[0], result)

    def test_installation_is_idempotent_and_retains_the_verified_official_backup(self):
        installed = ADAPTER.install(self.asar, self.state)
        self.assertEqual('adapted', installed['status'])
        self.assertEqual(self.source, self.backup.read_bytes())
        self.assertEqual(ADAPTER.adapt(self.source)[0], self.asar.read_bytes())
        self.assertEqual(0o640, self.asar.stat().st_mode & 0o777)
        self.assertEqual(0o600, self.backup.stat().st_mode & 0o777)
        before = tree(self.root)
        self.assertEqual('adapted', ADAPTER.install(self.asar, self.state, True)['clientState'])
        self.assertEqual('current', ADAPTER.install(self.asar, self.state)['status'])
        self.assertEqual(before, tree(self.root))

    def test_receipt_drift_duplicate_fields_and_corrupt_backups_are_refused_unchanged(self):
        ADAPTER.install(self.asar, self.state)
        valid = self.receipt.read_bytes()
        record = json.loads(valid)
        for key in ('officialSha256', 'adaptedSha256', 'modifiedModule', 'backup', 'provider'):
            changed = {**record, key: 'forged'}
            self.receipt.write_text(json.dumps(changed))
            before = tree(self.root)
            with self.assertRaisesRegex(ValueError, 'receipt differs'):
                ADAPTER.install(self.asar, self.state)
            self.assertEqual(before, tree(self.root))
        self.receipt.write_bytes(b'{"provider":"wrong",' + valid[1:])
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, 'Duplicate'):
            ADAPTER.install(self.asar, self.state)
        self.assertEqual(before, tree(self.root))
        self.receipt.write_bytes(valid)
        self.backup.write_bytes(b'Corrupt official backup')
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, 'backup differs'):
            ADAPTER.install(self.asar, self.state)
        self.assertEqual(before, tree(self.root))

    def test_adapted_client_without_original_backup_is_refused(self):
        ADAPTER.install(self.asar, self.state)
        self.backup.unlink()
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, 'not reviewed'):
            ADAPTER.install(self.asar, self.state)
        self.assertEqual(before, tree(self.root))

    def test_missing_receipt_recovers_from_verified_backup_without_replacing_asar(self):
        ADAPTER.install(self.asar, self.state)
        expected = self.receipt.read_bytes()
        self.receipt.unlink()
        before = tree(self.root)
        self.assertEqual('adapted', ADAPTER.install(self.asar, self.state, True)['clientState'])
        self.assertEqual(before, tree(self.root))
        ADAPTER.install(self.asar, self.state)
        self.assertEqual(before['app.asar'], tree(self.root)['app.asar'])
        self.assertEqual(expected, self.receipt.read_bytes())

    def test_failed_write_preserves_active_original_and_can_resume(self):
        original_write = ADAPTER.atomic_write
        def fail_asar(path, chunks, *args):
            if path == self.asar:
                raise OSError('Injected ASAR publication failure')
            return original_write(path, chunks, *args)
        with mock.patch.object(ADAPTER, 'atomic_write', side_effect=fail_asar):
            with self.assertRaisesRegex(OSError, 'publication failure'):
                ADAPTER.install(self.asar, self.state)
        self.assertEqual(self.source, self.asar.read_bytes())
        self.assertEqual(self.source, self.backup.read_bytes())
        self.assertFalse(self.receipt.exists())
        self.assertEqual('adapted', ADAPTER.install(self.asar, self.state)['status'])

    def test_real_process_deaths_before_and_after_atomic_publication_recover(self):
        for point in ('after-backup', 'before-rename:app.asar', 'after-rename:app.asar',
                      'after-asar', 'before-rename:client-adapter.json',
                      'after-rename:client-adapter.json', 'after-receipt'):
            with self.subTest(point=point), tempfile.TemporaryDirectory(prefix='foldgpt-adapter-kill-') as directory:
                root = Path(directory)
                asar, state = root / 'app.asar', root / 'state'
                asar.write_bytes(self.source)
                child = subprocess.run([sys.executable, '-B', str(Path(__file__).resolve()), '--crash', directory, point],
                                       capture_output=True, timeout=30)
                self.assertEqual(-signal.SIGKILL, child.returncode, child.stderr.decode())
                ADAPTER.install(asar, state, True)
                ADAPTER.install(asar, state)
                self.assertEqual(ADAPTER.adapt(self.source)[0], asar.read_bytes())
                self.assertEqual(self.source, (state / self.backup.name).read_bytes())
                record = json.loads((state / 'client-adapter.json').read_bytes())
                self.assertEqual(ADAPTER.digest(asar.read_bytes()), record['adaptedSha256'])
                self.assertEqual('current', ADAPTER.install(asar, state)['status'])

    def test_concurrent_installer_cannot_take_the_same_lease(self):
        ADAPTER.install(self.asar, self.state)
        with (self.state / 'install.lock').open('r+b') as lease:
            ADAPTER.fcntl.flock(lease.fileno(), ADAPTER.fcntl.LOCK_EX | ADAPTER.fcntl.LOCK_NB)
            before = tree(self.root)
            with self.assertRaises(BlockingIOError):
                ADAPTER.install(self.asar, self.state)
            self.assertEqual(before, tree(self.root))

    def test_symlink_and_hardlink_backups_are_refused(self):
        self.state.mkdir()
        for link in (lambda: self.backup.symlink_to(self.asar), lambda: os.link(self.asar, self.backup)):
            link()
            before = tree(self.root)
            with self.assertRaises((OSError, ValueError)):
                ADAPTER.install(self.asar, self.state)
            self.assertEqual(before, tree(self.root))
            self.backup.unlink()

    def test_backup_cannot_be_mistaken_for_the_active_archive(self):
        self.state.mkdir()
        self.backup.write_bytes(self.source)
        before = tree(self.root)
        with self.assertRaisesRegex(ValueError, 'separate from its backup'):
            ADAPTER.install(self.backup, self.state)
        self.assertEqual(before, tree(self.root))

    def test_session_refusal_precedes_dbus_context_and_all_filesystem_mutations(self):
        source = SESSION.read_text()
        commands = self.root / 'commands'
        commands.mkdir()
        log = self.root / 'calls'
        python = commands / 'python3'
        python.write_text('#!/bin/bash\nprintf "%s\\n" "$*" >> "$TEST_LOG"\nexit 42\n')
        python.chmod(0o755)
        session = self.root / 'session.sh'
        session.write_text(source)
        home = self.root / 'home'
        home.mkdir()
        result = subprocess.run(['/bin/bash', str(session)],
                                env={**os.environ, 'PATH': str(commands) + ':' + os.environ['PATH'],
                                     'HOME': str(home), 'TEST_LOG': str(log)}, capture_output=True, timeout=10)
        self.assertEqual(42, result.returncode, result.stderr.decode())
        calls = log.read_text().splitlines()
        self.assertEqual(1, len(calls))
        self.assertIn('install-workspace-provider.py --check', calls[0])
        self.assertEqual([], list(home.iterdir()))


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--crash':
        root, point = Path(sys.argv[2]), sys.argv[3]
        _, known = fixture()
        ADAPTER.KNOWN = known
        def kill_checkpoint(name):
            if name == point:
                os.kill(os.getpid(), signal.SIGKILL)
        ADAPTER.checkpoint = kill_checkpoint
        ADAPTER.install(root / 'app.asar', root / 'state')
        raise SystemExit('Requested crash point was not reached')
    unittest.main()
