"""Reject stale or failed lifecycle receipts before a new Android generation."""
import copy
import importlib.util
from pathlib import Path
import unittest


_spec = importlib.util.spec_from_file_location("production_device",
    Path(__file__).with_name("qualify-production-device.py"))
_driver = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_driver)


class ProductionCleanupReceipts(unittest.TestCase):
    def setUp(self):
        receipt = {"bootstrapPid": 8166, "waitStatus": 0, "bootstrapReaped": True,
            "cleanupComplete": True, "ownerRetained": False, "setupError": None,
            "cleanupError": None, "transportFailed": False, "quarantined": False,
            "refusedBeforeFork": False}
        self.status = {"state": "closed", "lastNativeSessionStatus": receipt,
                       "lastRemoteStatus": copy.deepcopy(receipt)}

    def test_requires_the_current_generation_in_both_receipts(self):
        self.assertTrue(_driver.successful_cleanup(self.status, 8166))
        self.assertFalse(_driver.successful_cleanup(self.status, 8815))
        for key in ("lastNativeSessionStatus", "lastRemoteStatus"):
            value = copy.deepcopy(self.status)
            value[key]["bootstrapPid"] = 8815
            self.assertFalse(_driver.successful_cleanup(value, 8166))

    def test_failure_or_incomplete_receipt_never_admits_restart(self):
        changes = {"waitStatus": 1, "bootstrapReaped": False, "cleanupComplete": False,
            "ownerRetained": True, "setupError": {}, "cleanupError": {},
            "transportFailed": True, "quarantined": True, "refusedBeforeFork": True}
        for key in ("lastNativeSessionStatus", "lastRemoteStatus"):
            for field, failed in changes.items():
                with self.subTest(receipt=key, field=field):
                    value = copy.deepcopy(self.status)
                    value[key][field] = failed
                    self.assertFalse(_driver.successful_cleanup(value, 8166))
            value = copy.deepcopy(self.status)
            del value[key]
            self.assertFalse(_driver.successful_cleanup(value, 8166))

    def test_closed_state_and_known_positive_pid_are_required(self):
        for state in ("ready", "unavailable", "stopping", None):
            value = {**self.status, "state": state}
            self.assertFalse(_driver.successful_cleanup(value, 8166))
        for pid in (None, 0, -1, True, "8166"):
            self.assertFalse(_driver.successful_cleanup(self.status, pid))
        self.assertFalse(_driver.successful_cleanup(None, 8166))


if __name__ == "__main__":
    unittest.main()
