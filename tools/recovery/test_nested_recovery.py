"""Real filesystem/Git checks for snapshots confined within the project."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from recovery_paths import destination_boundary, plain_path, snapshot_roots


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TOOLS = (('hydrate-project', load('hydrate-project').hydrate),
         ('merge-supplement', load('merge-supplement').merge))


class NestedRecoveryTests(unittest.TestCase):
    def setUp(self):
        test_root = Path(__file__).resolve().parents[2] / 'work/recovery-tests'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.base = Path(self.temp.name).resolve()
        self.base.relative_to(test_root.resolve())
        self.addCleanup(self.temp.cleanup)

    def fixture(self, name):
        project = self.base / name
        project.mkdir()
        subprocess.run(['git', 'init', '-q', str(project)], check=True)
        (project / '.gitignore').write_text('data/\nwork/\n*.log\n')
        (project / 'source.py').write_text('tracked bytes\n')
        subprocess.run(['git', '-C', str(project), 'add', '.'], check=True)
        subprocess.run(['git', '-C', str(project), '-c', 'user.name=Recovery test',
                        '-c', 'user.email=local@example.invalid', 'commit', '-qm', 'fixture'], check=True)
        source = project / 'work/FoldGPT-recovery/restored/snapshot'
        (source / 'data/empty').mkdir(parents=True)
        (source / 'data/a').write_text('restored bytes\n')
        (source / 'source.py').write_text('old bytes\n')
        (source / 'work/evidence/trace.json').parent.mkdir(parents=True)
        (source / 'work/evidence/trace.json').write_text('evidence\n')
        return project, source

    def test_nested_snapshot_and_report_keep_sources_and_snapshot_intact(self):
        for name, _ in TOOLS:
            with self.subTest(tool=name):
                project, source = self.fixture(name)
                report = project / 'work/FoldGPT-recovery/report.json'
                result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name(name + '.py')),
                    '--project', str(project), '--snapshot', str(source), '--report', str(report)], capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(json.loads(report.read_text())['sourceFilesOverwritten'])
                self.assertEqual((project / 'data/a').read_text(), 'restored bytes\n')
                self.assertTrue((project / 'data/empty').is_dir())
                self.assertEqual((project / 'work/evidence/trace.json').read_text(), 'evidence\n')
                self.assertEqual((project / 'source.py').read_text(), 'tracked bytes\n')
                self.assertEqual((source / 'source.py').read_text(), 'old bytes\n')
                self.assertFalse((source / 'work/FoldGPT-recovery').exists())

    def test_output_into_snapshot_refused_before_any_copy(self):
        for name, operation in TOOLS:
            with self.subTest(tool=name):
                project, source = self.fixture(name)
                injected = source / source.relative_to(project) / 'injected'
                injected.parent.mkdir(parents=True)
                injected.write_text('must not write into live snapshot')
                with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
                    operation(source, project)
                self.assertFalse((source / 'injected').exists())
                self.assertFalse((project / 'data').exists())

    def test_other_overlaps_and_snapshot_root_links_are_refused(self):
        for name, operation in TOOLS:
            project, source = self.fixture(name)
            elsewhere = project / 'work/not-recovery'
            elsewhere.mkdir()
            alias = project / 'work/FoldGPT-recovery/alias'
            os.symlink(source, alias, target_is_directory=True)
            for invalid in (project, self.base, project / 'work/FoldGPT-recovery', elsewhere, alias):
                with self.subTest(tool=name, invalid=invalid):
                    with self.assertRaises((ValueError, RuntimeError)):
                        operation(invalid, project)
                    self.assertFalse((project / 'data').exists())

    def test_destination_link_parent_refuses_before_any_copy(self):
        for name, operation in TOOLS:
            with self.subTest(tool=name):
                project, source = self.fixture(name)
                outside = self.base / (name + '-outside')
                outside.mkdir()
                os.symlink(outside, project / 'data', target_is_directory=True)
                with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
                    operation(source, project)
                self.assertEqual(list(outside.iterdir()), [])
                self.assertFalse((project / 'work/evidence').exists())

    def test_source_directory_links_are_preserved_without_following(self):
        for name, operation in TOOLS:
            with self.subTest(tool=name):
                project, source = self.fixture(name)
                outside = self.base / (name + '-outside')
                outside.mkdir()
                (outside / 'external').write_text('outside')
                os.symlink(outside, source / 'data/link', target_is_directory=True)
                operation(source, project)
                self.assertTrue((project / 'data/link').is_symlink())
                self.assertEqual(os.readlink(project / 'data/link'), os.readlink(source / 'data/link'))
                self.assertEqual((outside / 'external').read_text(), 'outside')

    def test_absent_tracked_file_protects_its_descendants(self):
        for name, operation in TOOLS:
            with self.subTest(tool=name):
                project, source = self.fixture(name)
                (project / 'source.py').unlink()
                (source / 'source.py').unlink()
                (source / 'source.py').mkdir()
                (source / 'source.py/new.log').write_text('must not recreate tracked path as directory')
                operation(source, project)
                self.assertFalse((project / 'source.py').exists())

    def test_existing_asset_conflict_is_preflighted(self):
        for name, operation in TOOLS:
            with self.subTest(tool=name):
                project, source = self.fixture(name)
                (project / 'work/evidence').mkdir()
                (project / 'work/evidence/trace.json').write_text('preserve existing')
                with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
                    operation(source, project)
                self.assertFalse((project / 'data').exists())
                self.assertEqual((project / 'work/evidence/trace.json').read_text(), 'preserve existing')

    def test_hydration_report_cannot_overwrite_sources_or_snapshot(self):
        project, source = self.fixture('hydrate')
        for report in (project / 'source.py', project / 'new-source.py', source / 'new-report.json'):
            with self.subTest(report=report):
                result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name('hydrate-project.py')),
                    '--project', str(project), '--snapshot', str(source), '--report', str(report)], capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((project / 'data').exists())
                self.assertEqual((project / 'source.py').read_text(), 'tracked bytes\n')

    @unittest.skipUnless(os.name == 'nt', 'Windows junctions')
    def test_windows_junctions_refused_in_source_and_destination(self):
        for name, operation in TOOLS:
            for location in ('input', 'output', 'root'):
                with self.subTest(tool=name, location=location):
                    project, source = self.fixture(name + '-' + location)
                    outside = self.base / (name + '-' + location + '-outside')
                    outside.mkdir()
                    junction = {'input': source / 'data/junction', 'output': project / 'data',
                                'root': project / 'work/FoldGPT-recovery/junction'}[location]
                    subprocess.run(['cmd', '/c', 'mklink', '/J', str(junction), str(outside)], check=True, capture_output=True)
                    with self.assertRaises((ValueError, RuntimeError, FileExistsError)):
                        operation(junction if location == 'root' else source, project)
                    self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == 'nt', 'Windows path namespaces')
    def test_windows_prefix_aliases_cannot_bypass_root_boundaries(self):
        project, source = self.fixture('prefix-roots')
        extended = lambda path: Path('\\\\?\\' + str(path))
        forbidden = (project, project.parent, project / 'work', project / 'work/FoldGPT-recovery')
        for candidate in forbidden:
            for input_source, input_project in ((extended(candidate), project), (candidate, extended(project))):
                with self.subTest(source=input_source, project=input_project):
                    with self.assertRaises(ValueError):
                        snapshot_roots(input_source, input_project)
        for input_source, input_project in ((extended(source), project), (source, extended(project))):
            self.assertEqual(snapshot_roots(input_source, input_project), (source, project))
            with self.assertRaises(ValueError):
                destination_boundary(extended(source), input_source, input_project, directory=True)

    @unittest.skipUnless(os.name == 'nt', 'Windows path namespaces')
    def test_windows_mixed_prefixes_preserve_report_boundaries(self):
        extended = lambda path: Path('\\\\?\\' + str(path))
        for name, _ in TOOLS:
            for prefix_source in (False, True):
                with self.subTest(tool=name, prefix_source=prefix_source):
                    project, source = self.fixture(name + '-prefix-' + str(prefix_source))
                    source_arg = extended(source) if prefix_source else source
                    project_arg = project if prefix_source else extended(project)
                    for destination in (source / 'new-report.json', project / 'new-source.py'):
                        report_arg = destination if prefix_source else extended(destination)
                        result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name(name + '.py')),
                            '--snapshot', str(source_arg), '--project', str(project_arg), '--report', str(report_arg)], capture_output=True)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertFalse(destination.exists())
                        self.assertFalse((project / 'data').exists())
                    report = project / 'work/FoldGPT-recovery/report.json'
                    report_arg = extended(report) if prefix_source else report
                    result = subprocess.run([sys.executable, '-B', str(Path(__file__).with_name(name + '.py')),
                        '--snapshot', str(source_arg), '--project', str(project_arg), '--report', str(report_arg)], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertTrue(report.is_file())
                    self.assertEqual((project / 'data/a').read_text(), 'restored bytes\n')

    @unittest.skipUnless(os.name == 'nt', 'Windows path namespaces')
    def test_windows_unc_aliases_normalize_and_device_names_are_refused(self):
        self.assertEqual(plain_path('\\\\?\\UNC\\server\\share\\folder'), Path('\\\\server\\share\\folder'))
        for name in ('\\\\.\\C:\\Dev', '\\\\?\\GLOBALROOT\\Device\\HarddiskVolume1', '\\??\\C:\\Dev'):
            with self.subTest(path=name):
                with self.assertRaises(ValueError):
                    plain_path(name)


if __name__ == '__main__':
    unittest.main()
