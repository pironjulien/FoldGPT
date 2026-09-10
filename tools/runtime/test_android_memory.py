"""Regressions for incomplete ADB/proc readings in the memory report."""
import importlib.util
from pathlib import Path
import unittest


spec = importlib.util.spec_from_file_location('memory_inspector', Path(__file__).with_name('inspect-android-memory.py'))
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)


def result(text, code=0):
    return {'code': code, 'text': text, 'stderr': ''}


def record(start=7300):
    stat = result('23 (worker (test)) S ' + '0 ' * 18 + str(start) + ' 4096 2\r\n')
    return {'pid': 23, 'statBefore': stat, 'statAfter': stat, 'statFinal': stat,
            'status': result('Name:\tworker\r\nUid:\t10412\t10412\t10412\t10412\r\n'),
            'smaps_rollup': result('Rss:                900 kB\r\nPss:                640 kB\r\n')}


class MemoryCoverageTests(unittest.TestCase):
    def test_windows_adb_crlf_is_counted(self):
        self.assertEqual(memory.summarize_pss([record()], 10412, True)['summedPssKiB'], 640)

    def test_denied_or_unparseable_pss_never_becomes_zero(self):
        for reading in (result('Pss: 640 kB\n', 1), result(''), result('Permission denied\r\n', 1)):
            with self.subTest(reading=reading):
                entry = record()
                entry['smaps_rollup'] = reading
                summary = memory.summarize_pss([entry], 10412, True)
                self.assertIsNone(summary['summedPssKiB'])
                self.assertIsNone(summary['observedPssKiB'])
                self.assertEqual(summary['pssUnavailablePids'], [23])

    def test_partial_sum_is_never_labeled_complete(self):
        missing = record()
        missing['pid'] = 24
        missing['statBefore'] = result('', 1)
        summary = memory.summarize_pss([record(), missing], 10412, True)
        self.assertIsNone(summary['summedPssKiB'])
        self.assertEqual(summary['observedPssKiB'], 640)
        self.assertEqual(summary['pssObservedCount'], 1)

    def test_pid_reuse_and_changed_owner_are_rejected(self):
        reused = record()
        reused['statAfter'] = record(8300)['statAfter']
        changed_owner = record()
        changed_owner['status'] = result('Uid:\t2000\t2000\t2000\t2000\n')
        for entry in (reused, changed_owner):
            with self.subTest(entry=entry):
                self.assertIsNone(memory.summarize_pss([entry], 10412, True)['summedPssKiB'])

    def test_membership_change_retains_only_partial_observation(self):
        summary = memory.summarize_pss([record()], 10412, False)
        self.assertIsNone(summary['summedPssKiB'])
        self.assertEqual(summary['observedPssKiB'], 640)
        self.assertFalse(summary['pssCoverageComplete'])

    def test_pid_reuse_after_its_pss_window_is_rejected(self):
        entry = record()
        entry['statFinal'] = record(8300)['statFinal']
        summary = memory.summarize_pss([entry], 10412, True)
        self.assertIsNone(summary['summedPssKiB'])
        self.assertEqual(summary['pssUnavailablePids'], [23])

    def test_failed_process_enumeration_is_not_an_empty_uid(self):
        for reading in (result('', 1), result('permission denied\n'),
                        result('UID PID PPID NAME\nnot-a-row\n')):
            with self.subTest(reading=reading), self.assertRaises(ValueError):
                memory.uid_processes(reading, 10412)
        self.assertEqual(memory.uid_processes(result('UID PID PPID NAME\r\n0 1 0 init\r\n'), 10412), [])


if __name__ == '__main__':
    unittest.main()
