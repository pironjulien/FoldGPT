"""Offline integrity tests against retained real host and Android composites."""
import argparse
import importlib.util
import json
from pathlib import Path, PurePosixPath
import tarfile
import unittest

spec = importlib.util.spec_from_file_location('composite_collector', Path(__file__).with_name('collect-native-executor.py'))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
OPTIONS = None


class CompositeEvidenceTests(unittest.TestCase):
    def load(self, directory, android=False):
        self.android = android
        if android:
            self.matrix = collector.strict_json((directory / 'composite-tests.json').read_bytes())
            self.output = (directory / 'fixture-output.txt').read_text()
            with tarfile.open(directory / 'sources-cases.tar') as archive:
                self.source = archive.extractfile('sources/' + collector.SUITE).read()
                self.child_source = archive.extractfile('sources/tools/executor/test_native_processes_live.py').read()
                for case in self.matrix['observations']:
                    prefix = 'cases/' + PurePosixPath(case['caseDirectory']).name
                    self.assertEqual(archive.extractfile(prefix + '/work/value').read(),
                        collector.lifecycle.decode_chunk(case['finalValueBase64']))
                    self.assertEqual(archive.extractfile(prefix + '/work/private/secret').read(), b'private-intact')
        else:
            self.matrix = collector.strict_json((directory / 'evidence/composite.json').read_bytes())
            self.output = (directory / 'composite-tests.txt').read_text()
            self.source = (directory / 'sources/test_native_executor_transport.py').read_bytes()
            self.child_source = (directory / 'sources/test_native_processes_live.py').read_bytes()

    def setUp(self):
        self.load(OPTIONS.current)

    def inspect(self):
        return collector.inspect_matrix(self.matrix, self.output, self.source, self.child_source,
            str(PurePosixPath(self.matrix['observations'][0]['caseDirectory']).parent),
            str(PurePosixPath(self.matrix['artifacts']['runner']['path']).parent) if self.android else None)

    def test_01_actual_host_nine_pass(self):
        self.assertEqual(self.inspect()['passed'], 9)

    def test_02_actual_android_missing_children_six_pass_retained(self):
        self.load(OPTIONS.children_failure, True)
        result = self.inspect()
        self.assertEqual(result['passed'], 6)
        self.assertEqual(len(result['failedTests']), 3)

    def test_03_actual_android_shield_failure_eight_pass_retained(self):
        self.load(OPTIONS.shield_failure, True)
        result = self.inspect()
        self.assertEqual(result['passed'], 8)
        self.assertEqual(len(result['failedTests']), 1)
        self.assertTrue(result['failedTests'][0].startswith('test_07_'))

    def test_04_fake_pass_on_real_failure_rejected(self):
        self.load(OPTIONS.shield_failure, True)
        self.matrix['passed'] = True
        with self.assertRaises(ValueError): self.inspect()

    def test_05_foreign_case_path_rejected(self):
        self.matrix['observations'][1]['caseDirectory'] = '/outside/fcomp-foreign'
        with self.assertRaises(ValueError): self.inspect()

    def test_06_missing_response_rejected(self):
        events = self.matrix['observations'][0]['events']
        events.remove(next(event for event in events if event.get('direction') == 'response' and 'id' in event['message']))
        with self.assertRaises((ValueError, KeyError)): self.inspect()

    def test_07_private_mutation_rejected(self):
        self.matrix['observations'][0]['privateSha256'] = collector.sha(b'changed')
        with self.assertRaises(ValueError): self.inspect()

    def test_08_missing_child_inventory_rejected(self):
        events = self.matrix['observations'][4]['events']
        events.remove(next(event for event in events if 'childSnapshot' in event))
        with self.assertRaises(ValueError): self.inspect()

    def test_09_shield_warning_in_fake_pass_rejected(self):
        self.output += '\nRpcError exception in shielded future\n'
        with self.assertRaises(ValueError): self.inspect()

    def test_10_native_broker_cannot_be_inside_proot(self):
        self.load(OPTIONS.shield_failure, True)
        event = next(event for event in self.matrix['observations'][0]['events'] if 'nativeBrokerContext' in event)
        event['nativeBrokerContext']['status']['TracerPid'] = '1234'
        with self.assertRaises(ValueError): self.inspect()

    def test_11_gnu_bridge_cannot_substitute_authenticated_peer(self):
        self.load(OPTIONS.shield_failure, True)
        event = next(event for event in self.matrix['observations'][0]['events'] if 'guestBridgeContext' in event)
        event['guestBridgeContext']['pid'] += 1
        with self.assertRaises(ValueError): self.inspect()

    def test_12_native_gate_child_list_cannot_be_empty(self):
        event = next(event for event in self.matrix['observations'][4]['events'] if 'childSnapshot' in event)
        event['childSnapshot']['children'] = []
        with self.assertRaises(ValueError): self.inspect()


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('current', 'children-failure', 'shield-failure', 'evidence'):
        parser.add_argument('--' + name, type=Path, required=True)
    OPTIONS = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CompositeEvidenceTests))
    report = {'scope': 'Offline independent integrity checks against real preserved composite observations and case bytes',
        'passed': result.wasSuccessful(), 'tests': result.testsRun,
        'collectorSha256': collector.sha(Path(collector.__file__).read_bytes()),
        'sharedCollectorSha256': collector.sha(collector.SHARED.read_bytes()),
        'testSha256': collector.sha(Path(__file__).read_bytes()),
        'evidenceRoots': {name: str(getattr(OPTIONS, name)) for name in ('current', 'children_failure', 'shield_failure')}}
    OPTIONS.evidence.write_text(json.dumps(report, indent=2) + '\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
