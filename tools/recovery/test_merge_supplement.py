"""Real Git/filesystem regressions for additive recovery on PC/Linux."""
import importlib.util
import os
from pathlib import Path
import subprocess
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
        (self.project / '.gitignore').write_text('data/\n')
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


if __name__ == '__main__':
    unittest.main()
