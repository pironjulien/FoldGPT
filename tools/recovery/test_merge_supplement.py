"""Real Git/filesystem regressions for additive recovery on PC/Linux."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('merge_supplement', Path(__file__).with_name('merge-supplement.py'))
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MergeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.project, self.source = self.base / 'project', self.base / 'source'
        self.project.mkdir(); self.source.mkdir()
        self.git('init', '-q')
        (self.project / '.gitignore').write_text('data/\nwork/\n')
        (self.project / 'source.py').write_text('current\n')
        self.git('add', '.')
        self.git('-c', 'user.name=Recovery test', '-c', 'user.email=local@example.invalid',
                 'commit', '-qm', 'fixture')
        (self.source / 'data/empty').mkdir(parents=True)
        (self.source / 'data/a').write_bytes(b'actual bytes\0\xff')
        (self.source / 'source.py').write_text('obsolete\n')
        (self.source / 'untracked.txt').write_text('not an ignored build artifact')

    def git(self, *args):
        return subprocess.check_output(['git', '-C', str(self.project), *args], stderr=subprocess.STDOUT)

    def test_restore_and_repeat_without_source_changes(self):
        os.symlink('a', self.source / 'data/link')
        first = module.merge(self.source, self.project)
        self.assertEqual(first['addedFilesAndLinks'], 2)
        self.assertEqual((self.project / 'data/a').read_bytes(), b'actual bytes\0\xff')
        self.assertEqual(os.readlink(self.project / 'data/link'), 'a')
        self.assertTrue((self.project / 'data/empty').is_dir())
        self.assertEqual((self.project / 'source.py').read_text(), 'current\n')
        self.assertFalse((self.project / 'untracked.txt').exists())
        self.assertEqual(self.git('status', '--porcelain'), b'')
        again = module.merge(self.source, self.project)
        self.assertEqual(again['addedFilesAndLinks'], 0)
        self.assertEqual(again['identicalExistingFilesAndLinks'], 2)

    def test_conflict_prevents_all_additions(self):
        (self.project / 'data').mkdir()
        (self.project / 'data/z').write_text('preserve')
        (self.source / 'data/z').write_text('conflict')
        with self.assertRaises(FileExistsError):
            module.merge(self.source, self.project)
        self.assertFalse((self.project / 'data/a').exists())
        self.assertFalse((self.project / 'data/empty').exists())
        self.assertEqual((self.project / 'data/z').read_text(), 'preserve')

    def test_symlink_parent_refuses_before_copy(self):
        outside = self.base / 'outside'
        outside.mkdir()
        os.symlink(outside, self.project / 'data')
        with self.assertRaises((ValueError, FileExistsError, RuntimeError)):
            module.merge(self.source, self.project)
        self.assertEqual(list(outside.iterdir()), [])

    def test_absent_tracked_file_still_protects_all_descendants(self):
        (self.project / '.gitignore').write_text('data/\n*.log\n')
        (self.project / 'source.py').unlink()
        (self.source / 'source.py').unlink()
        (self.source / 'source.py').mkdir()
        (self.source / 'source.py/added.log').write_text('must not replace the tracked file by a directory')
        module.merge(self.source, self.project)
        self.assertFalse((self.project / 'source.py').exists())

    def test_report_cannot_replace_tracked_source_or_old_report(self):
        for report in [self.project / 'source.py', self.base / 'previous.json']:
            if report.name == 'previous.json':
                report.write_text('prior evidence')
            before = report.read_bytes()
            result = subprocess.run([sys.executable, '-B', str(Path(module.__file__)),
                '--snapshot', str(self.source), '--project', str(self.project), '--report', str(report)],
                capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(report.read_bytes(), before)
            self.assertFalse((self.project / 'data').exists())

    def test_report_inside_ignored_work_directory_preserves_recovered_bytes(self):
        report = self.project / 'work/FoldGPT-recovery/verification.json'
        result = subprocess.run([sys.executable, '-B', str(Path(module.__file__)),
            '--snapshot', str(self.source), '--project', str(self.project), '--report', str(report)],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(report.read_text())['addedPaths'], ['data/a'])
        self.assertEqual((self.project / 'data/a').read_bytes(), b'actual bytes\0\xff')
        self.assertEqual((self.project / 'source.py').read_text(), 'current\n')
        self.assertEqual(self.git('status', '--porcelain'), b'')

    def test_new_report_cannot_collide_with_supplement_or_untracked_sources(self):
        collision = self.source / 'work/FoldGPT-recovery/verification.json'
        collision.parent.mkdir(parents=True)
        collision.write_text('existing supplemental evidence')
        for report in (self.project / collision.relative_to(self.source),
                       self.project / 'new-source.py', self.source / 'new-report.json'):
            with self.subTest(report=report):
                result = subprocess.run([sys.executable, '-B', str(Path(module.__file__)),
                    '--snapshot', str(self.source), '--project', str(self.project), '--report', str(report)],
                    capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(report.exists())
                self.assertFalse((self.project / 'data').exists())
        self.assertEqual(collision.read_text(), 'existing supplemental evidence')


if __name__ == '__main__':
    unittest.main()
