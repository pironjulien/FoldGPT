"""Identity/refusal and missing-observation regressions for device baselines."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("device_baseline", Path(__file__).with_name("collect-device-baseline.py"))
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def reader(overrides=None):
    values = {
        ("getprop", "ro.product.model"): "fixture-model",
        ("getprop", "ro.serialno"): "fixture-serial",
        ("cat", "/proc/sys/kernel/random/boot_id"): "fixture-boot",
        ("run-as", "app.foldgpt", "id", "-u"): "10412",
        ("ps", "-A", "-o", "UID,PID,PPID,NAME"): "UID PID PPID NAME\n0 1 0 init\n10412 50 1 app.foldgpt\n",
        ("dumpsys", "activity", "settings"): "  max_phantom_processes=32\n",
        ("dumpsys", "package", "app.foldgpt"): "versionCode=37 minSdk=30\nversionName=0.2.0-dev\n",
    }
    values.update(overrides or {})
    calls = []

    def read(*args):
        calls.append(args)
        value = values.get(args, "")
        return value if isinstance(value, dict) else {"code": 0, "text": value}
    return read, calls


class BaselineTests(unittest.TestCase):
    def test_wrong_device_refuses_before_app_inspection(self):
        read, calls = reader()
        with self.assertRaisesRegex(ValueError, "identity differs"):
            baseline.collect(read, "another-model", "fixture-serial")
        self.assertEqual(len(calls), 2)

    def test_unavailable_model_refuses_before_app_inspection(self):
        read, calls = reader({("getprop", "ro.product.model"): {"code": 1, "text": ""}})
        with self.assertRaisesRegex(ValueError, "Model unavailable"):
            baseline.collect(read, "fixture-model", "fixture-serial")
        self.assertEqual(len(calls), 1)

    def test_missing_properties_are_unknown_and_uid_is_not_phantom_count(self):
        read, _ = reader()
        result = baseline.collect(read, "fixture-model", "fixture-serial")
        self.assertIsNone(result["properties"]["ro.boot.warranty_bit"])
        self.assertEqual(result["observedUidProcessCount"], 1)
        self.assertEqual(result["effectiveGlobalPhantomLimit"], 32)
        self.assertIsNone(result["globalPhantomProcessCount"])
        self.assertEqual([p["name"] for p in result["uidProcesses"]], ["app.foldgpt"])

    def test_failed_ps_is_never_zero_processes(self):
        read, _ = reader({("ps", "-A", "-o", "UID,PID,PPID,NAME"): {"code": 1, "text": "denied"}})
        with self.assertRaisesRegex(ValueError, "enumeration failed"):
            baseline.collect(read, "fixture-model", "fixture-serial")

    def test_reboot_invalidates_snapshot(self):
        read, _ = reader()
        boots = iter(["first", "second"])

        def rebooting(*args):
            if args == ("cat", "/proc/sys/kernel/random/boot_id"):
                return {"code": 0, "text": next(boots)}
            return read(*args)
        with self.assertRaisesRegex(ValueError, "rebooted"):
            baseline.collect(rebooting, "fixture-model", "fixture-serial")

    def test_missing_or_ambiguous_limit_is_unknown(self):
        for text in ("", "other=32\n", "max_phantom_processes=32\nmax_phantom_processes=64\n"):
            self.assertIsNone(baseline.effective_phantom_limit({"code": 0, "text": text}))
        self.assertIsNone(baseline.effective_phantom_limit({"code": 1, "text": "max_phantom_processes=32"}))


if __name__ == "__main__":
    unittest.main()
