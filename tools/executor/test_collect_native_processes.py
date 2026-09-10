"""Offline integrity checks against retained real lifecycle observations.

No fixture is run, no device is contacted and no historical evidence is changed.
Negative cases alter copies to ensure incomplete or contradictory proof fails.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("native_process_collector", Path(__file__).with_name("collect-native-processes.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)
OPTIONS = None


class LifecycleEvidenceTests(unittest.TestCase):
    @staticmethod
    def load(directory, native=False):
        if native:
            return (collector.strict_json((directory / "lifecycle-tests.json").read_bytes()),
                (directory / "fixture-output.txt").read_text(),
                (directory / "sources/tools/executor/test_native_processes_live.py").read_bytes())
        return (collector.strict_json((directory / "evidence/lifecycle.json").read_bytes()),
            (directory / "lifecycle-tests.txt").read_text(), (directory / "sources/test_native_processes_live.py").read_bytes())

    def setUp(self):
        self.matrix, self.output, self.source = self.load(OPTIONS.current)

    def inspect(self):
        return collector.inspect_matrix(self.matrix, self.output, self.source, "unused-offline-target")

    def entry(self, number, field):
        return next(entry for entry in self.matrix["observations"]
                    if entry["test"].startswith(f"__main__.NativeProcessTests.test_{number:02}_") and field in entry)

    def test_01_actual_v2_twenty_three_tests(self):
        value = self.inspect()
        self.assertEqual(value["testsRun"], 23)
        self.assertEqual(value["passed"], 23)
        self.assertEqual(value["observations"], 109)
        self.assertEqual(value["nativeProcessProfile"], "managed-process-v2")
        self.assertFalse(value["childWatcherWarningObserved"])

    def test_02_retained_actual_android_v1_pass_still_valid(self):
        self.matrix, self.output, self.source = self.load(OPTIONS.legacy_pass, native=True)
        value = self.inspect()
        self.assertEqual(value["testsRun"], 20)
        self.assertEqual(value["passed"], 20)
        self.assertEqual(value["nativeProcessProfile"], "managed-process-v1")

    def test_03_retained_actual_android_failure_remains_failure(self):
        self.matrix, self.output, self.source = self.load(OPTIONS.legacy_failure, native=True)
        value = self.inspect()
        self.assertEqual(value["testsRun"], 19)
        self.assertEqual(value["passed"], 1)
        self.assertEqual(len(value["failedTests"]), 18)
        self.assertTrue(value["missingMemfdCreateErrorObserved"])

    def test_04_missing_acknowledgement_rejected(self):
        self.entry(21, "supervisorIdentity")["supervisorIdentity"]["acknowledgedBeforeWorker"] = False
        with self.assertRaises(ValueError): self.inspect()

    def test_05_invented_supervisor_returncode_rejected(self):
        self.entry(21, "supervisorReturncode")["supervisorReturncode"] = 255
        with self.assertRaises(ValueError): self.inspect()

    def test_06_old_native_profile_cannot_masquerade_as_v2(self):
        self.entry(21, "nativeStarted")["nativeStarted"]["profile"] = "managed-process-v1"
        with self.assertRaises(ValueError): self.inspect()

    def test_07_bare_pid_signal_route_rejected(self):
        self.entry(21, "supervisorSignals")["supervisorSignals"][0]["route"] = "os.kill"
        with self.assertRaises(ValueError): self.inspect()

    def test_08_post_reap_identity_proof_required(self):
        self.entry(22, "postReapSignalReturnedESRCH")["postReapSignalReturnedESRCH"] = False
        with self.assertRaises(ValueError): self.inspect()

    def test_09_transferred_descriptor_cleanup_required(self):
        self.entry(23, "actualDescriptorCountsUnchanged")["actualDescriptorCountsUnchanged"] = False
        with self.assertRaises(ValueError): self.inspect()

    def test_10_real_output_warning_cannot_be_ignored(self):
        self.output += "\nchild process pid 123 exit status already read: will report returncode 255\n"
        with self.assertRaises(ValueError): self.inspect()

    def test_11_missing_raw_native_cleanup_rejected(self):
        self.entry(22, "nativeEvents")["nativeEvents"][-1]["cleanupComplete"] = False
        with self.assertRaises(ValueError): self.inspect()

    def test_12_actual_android_v2_partial_failure_remains_failure(self):
        self.matrix, self.output, self.source = self.load(OPTIONS.v2_failure, native=True)
        value = self.inspect()
        self.assertEqual(value['testsRun'], 23)
        self.assertEqual(value['passed'], 22)
        self.assertEqual(value['observations'], 108)
        self.assertEqual(len(value['failedTests']), 1)
        self.assertTrue(value['failedTests'][0].startswith('test_22_'))
        self.assertEqual(value['nativeProcessProfile'], 'managed-process-v2')

    def test_13_packaged_inventory_cannot_omit_snapshots(self):
        self.entry(22, 'childSnapshots').pop('childSnapshots')
        with self.assertRaises(ValueError): self.inspect()

    def test_14_post_ack_worker_cannot_be_invented_empty(self):
        self.entry(22, 'childSnapshots')['childSnapshots'][2]['children'] = []
        with self.assertRaises(ValueError): self.inspect()

    def test_15_visible_pid_cannot_be_silently_ignored(self):
        self.entry(22, 'childSnapshots')['childSnapshots'][0]['readableProcesses'].pop()
        with self.assertRaises(ValueError): self.inspect()

    def test_16_same_uid_unreadable_cannot_be_classified_foreign(self):
        snapshot = self.entry(22, 'childSnapshots')['childSnapshots'][0]
        record = snapshot['readableProcesses'].pop()
        snapshot['inaccessibleForeignProcesses'].append({'pid': record['pid'], 'ownerUid': self.matrix['uid']})
        snapshot['inaccessibleForeignProcesses'].sort(key=lambda item: item['pid'])
        with self.assertRaises(ValueError): self.inspect()

    def test_17_parent_reuse_between_gate_observations_rejected(self):
        self.entry(22, 'childSnapshots')['childSnapshots'][2]['parent']['startTimeTicks'] += 1
        with self.assertRaises(ValueError): self.inspect()


def main():
    global OPTIONS
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("current", "legacy-pass", "legacy-failure", "v2-failure", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    OPTIONS = parser.parse_args()
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(LifecycleEvidenceTests))
    report = {"scope": "Offline collector integrity against actual retained host/Android lifecycle evidence",
        "passed": result.wasSuccessful(), "tests": result.testsRun,
        "collectorSha256": hashlib.sha256(Path(collector.__file__).read_bytes()).hexdigest(),
        "testSha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "evidenceRoots": {key: str(getattr(OPTIONS, key)) for key in ("current", "legacy_pass", "legacy_failure", "v2_failure")}}
    OPTIONS.evidence.write_text(json.dumps(report, indent=2) + "\n")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
