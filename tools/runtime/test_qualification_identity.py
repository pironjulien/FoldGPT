"""PC-only collision and evidence-admission tests; never invokes real ADB."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from qualification_identity import (LAB_PACKAGE, LEGACY_PACKAGE, V11_PACKAGE,
                                    V2_BASE, V3_BASE, resolve_identity)

HERE = Path(__file__).resolve().parent


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class IdentityTests(unittest.TestCase):
    def test_v11_paths_are_independent(self):
        identity = resolve_identity(V11_PACKAGE, V3_BASE, 11)
        self.assertEqual(identity.workspace, V3_BASE + '/workspace')
        self.assertEqual(identity.report_file('report.json'), 'files/kernel-v11/report.json')
        self.assertEqual(identity.report_file('package-info.json'), 'files/kernel-v11/package-info.json')

    def test_crossed_profiles_and_path_aliases_are_refused(self):
        for package, base, version in ((V11_PACKAGE, V2_BASE, 11), (V11_PACKAGE, V3_BASE, 6),
                (LAB_PACKAGE, V3_BASE, 6), (LAB_PACKAGE, V2_BASE, 11),
                (LEGACY_PACKAGE, V3_BASE, None), (V11_PACKAGE, V3_BASE + '/', 11),
                (V11_PACKAGE, V3_BASE + '/../qualification-v2', 11),
                (V11_PACKAGE, V3_BASE, True), ('unrelated.application', V3_BASE, 11)):
            with self.subTest(package=package, base=base, version=version), self.assertRaises(ValueError):
                resolve_identity(package, base, version)

    def test_historical_report_locations_remain_explicit(self):
        self.assertEqual(resolve_identity(LEGACY_PACKAGE, V2_BASE, None).report_directory, 'files')
        for version in range(2, 7):
            self.assertEqual(resolve_identity(LAB_PACKAGE, V2_BASE, version).report_directory,
                             'files/kernel-v' + str(version))

    def test_clean_records_from_other_fixture_cannot_authorize_inspection(self):
        identity = resolve_identity(V11_PACKAGE, V3_BASE, 11)
        app = {'diagnosticVersion': 11, 'packageName': V11_PACKAGE, 'nativeBase': V3_BASE,
               'requestedAction': V11_PACKAGE + '.KERNEL_RUN_FIXED_V11'}
        native = {'workspace': identity.workspace}
        self.assertTrue(identity.matches_evidence(app, native))
        for change in ({'diagnosticVersion': 10}, {'diagnosticVersion': True},
                       {'packageName': LAB_PACKAGE}, {'nativeBase': V2_BASE},
                       {'requestedAction': V11_PACKAGE + '.KERNEL_PREFLIGHT'}):
            with self.subTest(change=change):
                self.assertFalse(identity.matches_evidence(app | change, native))
        self.assertFalse(identity.matches_evidence(app, {'workspace': V2_BASE + '/workspace'}))

    def test_invalid_cli_identity_fails_before_subprocess_or_output_creation(self):
        for filename in ('stage-kernel-python.py', 'collect-native-qualification.py'):
            module = script(filename)
            with tempfile.TemporaryDirectory() as temporary:
                output = Path(temporary) / 'uncreated'
                argv = [filename, '--adb', 'NEVER_INVOKE_ADB', '--serial', 'PC-ONLY',
                        '--output', str(output), '--package', V11_PACKAGE,
                        '--base', V2_BASE, '--report-version', '11']
                argv += (['--stage', temporary] if filename.startswith('stage-')
                         else ['--apk', temporary, '--before', temporary])
                with patch.object(sys, 'argv', argv), patch.object(subprocess, 'run') as invoked:
                    with self.assertRaises(SystemExit) as failure:
                        module.main()
                    self.assertEqual(failure.exception.code, 2)
                    invoked.assert_not_called()
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
