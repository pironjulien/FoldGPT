"""PC admission regression tests using a real r25 deployment and kernel receipts.

These tests exercise rejection boundaries; they do not run an Android process.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import stat
from types import SimpleNamespace
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
TRANSPORT = ROOT / "tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor"
sys.dont_write_bytecode = True
sys.path.insert(0, str(TRANSPORT))
import foldgpt_native_bootstrap as native
import foldgpt_app_bootstrap as app

ARGS = None


class OriginAdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with zipfile.ZipFile(ARGS.apk) as package:
            cls.original = json.loads(package.read(native.ASSET))
        cls.receipt = json.loads(ARGS.receipt.read_bytes())
        # Java retained the full status text; the Python receipt retained a
        # subset without CapInh/CapAmb/filter count. Use the complete real input.
        cls.observed = dict(line.split(":", 1) for line in cls.receipt["java"]["status"].splitlines()
                            if ":" in line)

    def setUp(self):
        self.config = copy.deepcopy(self.original)
        self.app = copy.deepcopy(self.original)
        self.app.update(schema="foldgpt.native.deployment.v2", launchOrigin="android-app")
        self.runas = {**self.observed, "NoNewPrivs": "0", "Seccomp": "0", "Seccomp_filters": "0"}
        self.runas_context = "u:r:runas_app:s0:c143,c257,c512,c768"
        self.app_context = "u:r:untrusted_app:s0:c156,c257,c512,c768"

    def test_original_deployment_is_accepted_unchanged(self):
        self.assertIs(native.deployment_contract(self.config), self.config)
        self.assertEqual(self.config, self.original)

    def test_explicit_app_deployment_is_accepted_unchanged(self):
        snapshot = copy.deepcopy(self.app)
        self.assertIs(native.deployment_contract(self.app, launch_origin="android-app"), self.app)
        self.assertEqual(self.app, snapshot)

    def test_each_origin_refuses_the_other_schema(self):
        with self.assertRaises(ValueError):
            native.deployment_contract(self.app)
        with self.assertRaises(ValueError):
            native.deployment_contract(self.config, launch_origin="android-app")

    def test_unknown_origin_has_no_default(self):
        for origin in (None, "", "shell", "android", "runas", "fallback"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                native.deployment_contract(self.config, launch_origin=origin)

    def test_v1_rejects_launch_origin_even_if_runas(self):
        self.config["launchOrigin"] = "run-as"
        with self.assertRaises(ValueError):
            native.deployment_contract(self.config)

    def test_v2_requires_exact_origin(self):
        for value in (None, "run-as", "shell", 2):
            self.app["launchOrigin"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                native.deployment_contract(self.app, launch_origin="android-app")
        del self.app["launchOrigin"]
        with self.assertRaises(ValueError):
            native.deployment_contract(self.app, launch_origin="android-app")

    def test_v2_keeps_private_runtime_boundary(self):
        for path in ("/", "/data/local/tmp/python", "/data/user/0/another.app/files/python"):
            self.app["pythonRuntime"]["path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                native.deployment_contract(self.app, launch_origin="android-app")

    def test_v2_cannot_supply_workspace_or_environment(self):
        for key in ("workspace", "parentEnvironment", "launchOrigin"):
            changed = copy.deepcopy(self.app)
            changed["backendOptions"][key] = "injected"
            with self.subTest(key=key), self.assertRaises(ValueError):
                native.deployment_contract(changed, launch_origin="android-app")

    def test_v2_cannot_replace_factory(self):
        self.app["backendFactory"] = "external:factory"
        with self.assertRaises(ValueError):
            native.deployment_contract(self.app, launch_origin="android-app")

    def test_v2_cannot_replace_ordinary_runner(self):
        for key in ("processRunner", "ptyProcessRunner"):
            changed = copy.deepcopy(self.app)
            changed["backendOptions"]["ordinaryUid"][key] = "/system/bin/sh"
            with self.subTest(key=key), self.assertRaises(ValueError):
                native.deployment_contract(changed, launch_origin="android-app")

    def test_runas_state_remains_accepted(self):
        native.process_context(self.runas, self.runas_context)

    def test_runas_rejects_real_filtered_application_state(self):
        with self.assertRaises(ValueError):
            native.process_context(self.observed, self.runas_context)

    def test_runas_rejects_any_admission_state_change(self):
        for name, value in (("NoNewPrivs", "1"), ("Seccomp", "1"), ("Seccomp_filters", "1")):
            changed = {**self.runas, name: value}
            with self.subTest(name=name), self.assertRaises(ValueError):
                native.process_context(changed, self.runas_context)

    def test_runas_rejects_capabilities(self):
        for name in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                native.process_context({**self.runas, name: "1"}, self.runas_context)

    def test_unknown_process_origin_is_rejected(self):
        with self.assertRaises(ValueError):
            native.process_context(self.runas, self.runas_context, launch_origin="automatic")

    def test_application_accepts_recorded_kernel_state_and_observed_domain(self):
        native.process_context(self.observed, self.app_context, launch_origin="android-app")

    def test_application_rejects_runas_unfiltered_state(self):
        with self.assertRaises(ValueError):
            native.process_context(self.runas, self.app_context, launch_origin="android-app")

    def test_application_refuses_changed_filter_state(self):
        for name, value in (("Seccomp", "0"), ("Seccomp", "1"), ("Seccomp_filters", "0"),
                            ("Seccomp_filters", "-1"), ("NoNewPrivs", "1"), ("TracerPid", "1234")):
            with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                native.process_context({**self.observed, name: value}, self.app_context,
                                       launch_origin="android-app")

    def test_application_rejects_capabilities(self):
        for name in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                native.process_context({**self.observed, name: "1"}, self.app_context,
                                       launch_origin="android-app")

    def test_application_rejects_other_domain_and_malformed_context(self):
        for context in (self.runas_context, "u:r:shell:s0", "u:r:untrusted_app_32:s0:c156,c257",
                        "u:r:untrusted_app:s0", self.app_context + "\nother", ""):
            with self.subTest(context=context), self.assertRaises(ValueError):
                native.process_context(self.observed, context, launch_origin="android-app")

    def test_entry_modules_reject_wrong_argument_counts(self):
        for module in (native, app):
            for arguments in ([], ["a"] * 4, ["a"] * 6):
                with self.subTest(module=module.__name__, count=len(arguments)), self.assertRaises(ValueError):
                    module.main(arguments)

    def private_stat(self, **changes):
        return SimpleNamespace(**{"st_dev": 19, "st_ino": 42, "st_uid": 10412,
                                  "st_gid": 10412, "st_mode": stat.S_IFDIR | 0o700, **changes})

    def test_data_views_accept_only_same_private_directory(self):
        for canonical in (native.DATA, Path("/data/data/app.foldgpt")):
            with self.subTest(canonical=canonical):
                self.assertEqual(app.admit_data_path(canonical, self.private_stat(), self.private_stat(), 10412), canonical)

    def test_data_views_reject_other_package_or_directory(self):
        for path in ("/data/data/another.app", "/data/local/tmp/app.foldgpt", "/data/user/10/app.foldgpt"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                app.admit_data_path(Path(path), self.private_stat(), self.private_stat(), 10412)

    def test_data_views_reject_changed_identity_owner_group_or_mode(self):
        for change in ({"st_dev": 20}, {"st_ino": 43}, {"st_uid": 10413}, {"st_gid": 10413},
                       {"st_mode": stat.S_IFDIR | 0o710}, {"st_mode": stat.S_IFLNK | 0o700}):
            for side in ("declared", "canonical"):
                declared = self.private_stat(**change) if side == "declared" else self.private_stat()
                actual = self.private_stat(**change) if side == "canonical" else self.private_stat()
                with self.subTest(change=change, side=side), self.assertRaises(ValueError):
                    app.admit_data_path(Path("/data/data/app.foldgpt"), declared, actual, 10412)

    def test_private_runtime_suffix_keeps_exact_spelling(self):
        data = Path("/data/data/app.foldgpt")
        expected = data / "files/native-runtime-v1/python"
        self.assertEqual(app.admit_private_suffix(native.RUNTIME, data, expected, expected,
                                                 self.private_stat(), 10412, 0o077), expected)

    def test_private_suffix_rejects_inside_and_outside_aliases(self):
        data = Path("/data/data/app.foldgpt")
        expected = data / "files/native-runtime-v1/python"
        for replacement in (data / "files/other-python", native.RUNTIME, Path("/data/local/tmp/python")):
            for side in ("declared", "canonical"):
                resolved = replacement if side == "declared" else expected
                canonical = replacement if side == "canonical" else expected
                with self.subTest(replacement=replacement, side=side), self.assertRaises(ValueError):
                    app.admit_private_suffix(native.RUNTIME, data, resolved, canonical,
                                             self.private_stat(), 10412, 0o077)

    def test_runas_paths_keep_exact_original_prefix(self):
        self.assertEqual(native.runtime_paths(10412), native.BootstrapPaths(
            native.DATA, native.RUNTIME, native.PROJECTS, native.BROKER))

    def test_non_android_identity_is_rejected(self):
        self.assertNotEqual(sys.platform, "android", "This is a PC-only admission test")
        with self.assertRaises(ValueError):
            native.identity(10415, 1903, "a" * 32, str(native.BROKER / ("a" * 32) / "launch.json"))
        with self.assertRaises(ValueError):
            app.identity(10415, 1903, "a" * 32, str(native.BROKER / ("a" * 32) / "launch.json"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ARGS = parser.parse_args()
    ARGS.output.resolve().relative_to(ROOT)
    if ARGS.output.exists():
        raise FileExistsError("Retain previous test evidence")
    result = unittest.main(argv=[sys.argv[0]], verbosity=2, exit=False).result
    with ARGS.output.open("x", encoding="utf-8") as destination:
        json.dump({"success": result.wasSuccessful(), "testsRun": result.testsRun,
                   "androidExecuted": False,
                   "failures": [{"test": test.id(), "detail": detail} for test, detail in result.failures],
                   "errors": [{"test": test.id(), "detail": detail} for test, detail in result.errors]}, destination, indent=2)
        destination.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
