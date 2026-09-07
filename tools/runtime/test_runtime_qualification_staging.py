"""PC-only runtime fixture and identity admission, with no real ADB invocation."""
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

from runtime_qualification_identity import BASE, PACKAGE, SENTINEL, runtime_identity, resolve_runtime_identity

HERE = Path(__file__).resolve().parent


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RuntimeStagingTests(unittest.TestCase):
    def test_explicit_v2_identity_retains_v1_and_refuses_crossed_parts(self):
        first, second = runtime_identity(1), runtime_identity(2)
        self.assertEqual(second.report_file('report.json'), 'files/runtime-v2/report.json')
        self.assertEqual(second.report_version, 2)
        self.assertIn(first.package, second.retained_packages)
        self.assertEqual(resolve_runtime_identity(second.package, second.base, 2), second)
        for package, base, version in ((first.package, second.base, 2), (second.package, first.base, 2),
                                       (second.package, second.base, 1), (second.package, second.base, True)):
            with self.assertRaises(ValueError): resolve_runtime_identity(package, base, version)

    def test_v2_operators_select_only_its_exact_fixture(self):
        stage, snapshot = script('stage-native-qualification.py'), script('snapshot-native-qualification.py')
        second = runtime_identity(2)
        files, entries = stage.fixture(second.base)
        self.assertEqual(files, {'workspace/private/secret': SENTINEL})
        self.assertEqual(entries['workspace/directory'], set())
        self.assertEqual(snapshot.fixture_names(second.workspace), ('private/secret',))
        for alias in (second.base + '/', second.base + '/../', second.base + '-new'):
            with self.assertRaises(ValueError): stage.fixture(alias)
            with self.assertRaises(ValueError): snapshot.fixture_names(alias + '/workspace')

    def test_other_identities_and_aliases_fail_before_adb_or_output_creation(self):
        module = script('stage-kernel-python.py')
        for base, version in ((BASE + '/', 1), (BASE + '/../foldgpt-bionic-supervisor-qualification-v4', 1),
                              ('/data/local/tmp/foldgpt-bionic-supervisor-qualification-v4', 1), (BASE, 12)):
            with self.subTest(base=base, version=version), tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'absent'
                argv = ['stage', '--adb', 'NEVER_ADB', '--serial', 'PC', '--stage', temporary,
                        '--output', str(output), '--package', PACKAGE, '--base', base,
                        '--report-version', str(version)]
                with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run') as invoked:
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                        module.main()
                    self.assertEqual(error.exception.code, 2)
                    invoked.assert_not_called()
                self.assertFalse(output.exists())
        with self.assertRaises(ValueError):
            resolve_runtime_identity(PACKAGE, BASE, True)

    def test_exact_package_info_cannot_be_replaced_with_kernel_info(self):
        module = script('stage-kernel-python.py')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'result'
            argv = ['stage', '--adb', 'NEVER_ADB', '--serial', 'PC', '--stage', temporary,
                    '--output', str(output), '--package', PACKAGE, '--base', BASE, '--report-version', '1']
            wrong = b'{"packageName":"app.foldgpt.kernelqualification.v12","diagnosticVersion":12}'
            with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 0, wrong, b'')) as invoked:
                with self.assertRaisesRegex(ValueError, 'independent fixture'):
                    module.main()
                self.assertEqual(invoked.call_count, 1)
                self.assertIn('files/runtime-v1/package-info.json', invoked.call_args.args[0][-1])

    def test_actual_tar_has_empty_project_directory_and_only_private_sentinel(self):
        module = script('stage-native-qualification.py')
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'result'
            argv = ['stage', '--adb', 'NEVER_ADB', '--serial', 'PC', '--base', BASE, '--output', str(output)]
            # Refuse before any Android write, then inspect the actual assembled input.
            with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run', return_value=
                    subprocess.CompletedProcess([], 0, b'1000\n', b'')) as invoked:
                with self.assertRaisesRegex(RuntimeError, 'nonroot ADB shell'):
                    module.main()
                self.assertEqual(invoked.call_count, 1)
            with tarfile.open(output / 'fixture.tar') as archive:
                members = archive.getmembers()
                self.assertEqual({item.name for item in members}, {'broker', 'workspace',
                    'workspace/private', 'workspace/directory', 'workspace/.git', 'workspace/private/secret'})
                for item in members:
                    self.assertEqual((item.uid, item.gid, item.mode), (2000, 2000, 0o700 if item.isdir() else 0o600))
                self.assertEqual(archive.extractfile('workspace/private/secret').read(), SENTINEL)

    def test_snapshot_and_stage_reject_runtime_aliases_before_io(self):
        for name, flag in (('snapshot-native-qualification.py', '--workspace'), ('stage-native-qualification.py', '--base')):
            module = script(name)
            for base in (BASE + '/..', BASE + '-v2', '/data/local/tmp'):
                with tempfile.TemporaryDirectory() as temporary:
                    output = Path(temporary) / 'absent'
                    value = base + '/workspace' if flag == '--workspace' else base
                    argv = [name, '--adb', 'NEVER_ADB', '--serial', 'PC', '--output', str(output), flag, value]
                    with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run') as invoked:
                        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                            module.main()
                        self.assertEqual(error.exception.code, 2)
                        invoked.assert_not_called()
                    self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
