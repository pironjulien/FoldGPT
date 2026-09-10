"""Guard one-time migration admission without touching a device."""
import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("recover", Path(__file__).with_name("recover-legacy-native-session.py"))
recover = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recover)


class ObservationTest(unittest.TestCase):
    def setUp(self):
        self.uid = 10412
        self.marker = {"version": 1, "uid": self.uid, "brokerPid": 29060}
        self.state = {"schema": "foldgpt.native.owner.v1", "state": "stopping", "launchOrigin": "android-app",
                      "lastNativeSessionStatus": {"launchOrigin": "android-app", "directNative": True,
                          "bootstrapPid": 29060, "cleanupComplete": False, "ownerRetained": True}}
        self.main = [["14571", str(self.uid), "app.foldgpt"]]

    def check(self, state=None, marker=None, owned=None, allow=True):
        recover.validate_legacy_observation(state or self.state, marker or self.marker,
            self.main if owned is None else owned, self.uid, allow)

    def test_stopping_requires_explicit_contract(self):
        with self.assertRaises(ValueError):
            self.check(allow=False)
        self.check()

    def test_live_runtime_or_child_refuses_even_with_matching_marker(self):
        for name in ("app.foldgpt:runtime", "libfoldgpt_python_cli.so", "node_repl"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(owned=self.main + [["29060", str(self.uid), name]])

    def test_mismatched_owner_and_cleanup_claims_refuse(self):
        for key, value in (("bootstrapPid", 29061), ("ownerRetained", False),
                           ("cleanupComplete", True), ("directNative", False),
                           ("launchOrigin", "run-as")):
            changed = copy.deepcopy(self.state)
            changed["lastNativeSessionStatus"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(state=changed)

    def test_other_states_never_broadened(self):
        for name in ("ready", "starting", "closed", None):
            changed = {**self.state, "state": name}
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.check(state=changed)

    def test_other_version_and_uid_refuse(self):
        for key, value in (("version", 3), ("uid", self.uid + 1)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.check(marker={**self.marker, key: value})

    def test_valid_and_invalid_v2_marker(self):
        valid_epoch = {"schema": "foldgpt.android-boot-epoch.v1", "source": "android.provider.Settings.Global.BOOT_COUNT", "bootCount": 9}
        v2_marker = {"version": 2, "uid": self.uid, "brokerPid": 29060, "bootEpoch": valid_epoch}
        self.check(marker=v2_marker)
        for bad_epoch in (None, {}, {"bootCount": "9"}, {"schema": "other", "bootCount": 9}):
            with self.subTest(bad_epoch=bad_epoch), self.assertRaises(ValueError):
                self.check(marker={**v2_marker, "bootEpoch": bad_epoch})

    def test_original_unavailable_contract_preserved(self):
        self.check(state={"state": "unavailable"}, allow=False)

    def test_census_requires_complete_numeric_view_and_init_control(self):
        self.assertEqual(recover.app_processes("PID UID NAME\n1 0 init\n14571 10412 app.foldgpt\n", self.uid), self.main)
        for text in ("PID UID NAME\n14571 10412 app.foldgpt\n", "PID USER NAME\n1 root init\n",
                     "PID UID NAME\n1 0 init\n123 ?? node\n"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                recover.app_processes(text, self.uid)


if __name__ == "__main__":
    unittest.main()
