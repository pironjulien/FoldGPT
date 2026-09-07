"""PC-only identity, source-attestation and collector refusal tests."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from runtime_qualification_profile import BASE, BUILD, PACKAGE, REPO, STAGE, get_profile, load_contract, requests


def module(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result); return result


stage_module = module(Path(__file__).with_name("stage-runtime-qualification.py"), "runtime_stage_test")
collector = module(REPO / "tools/runtime/collect-runtime-qualification.py", "runtime_collector_test")


class PackagingTests(unittest.TestCase):
    def test_two_fixed_profiles_preserve_v1_and_retain_it_from_v2(self):
        first, second = get_profile(1), get_profile(2)
        self.assertEqual((first.package, first.base, first.stage), (PACKAGE, BASE, STAGE))
        self.assertEqual(second.package, 'app.foldgpt.runtimequalification.v2')
        self.assertEqual(second.base, '/data/local/tmp/foldgpt-bionic-runtime-qualification-v2')
        self.assertEqual(second.backend_factory, 'tools.executor.bionic-supervisor.runtime_qualification_factory_v2:factory')
        self.assertIn(first.package, second.retained_packages)
        for attribute in ('build', 'stage', 'apk', 'inputs'):
            self.assertNotEqual(getattr(first, attribute), getattr(second, attribute))
        for invalid in (True, False, 0, 3, '2'):
            with self.assertRaises(ValueError): get_profile(invalid)

    def test_selected_stage_rejects_cross_version_pin_before_output(self):
        first, second = get_profile(1), get_profile(2)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cli = root / 'python'; cli.write_bytes(b'unused')
            for selected, other in ((first, second), (second, first)):
                with self.assertRaisesRegex(ValueError, 'identify'):
                    stage_module.stage(root, cli, profile=selected, output=root / 'absent', pin={
                        'schema': 'foldgpt.runtime-qualification.inputs.v1', 'package': other.package,
                        'base': other.base, 'frozenName': root.name})
                self.assertFalse((root / 'absent').exists())

    def test_java_request_resources_equal_selected_python_contracts(self):
        contract = load_contract()
        for version, resource in ((1, 'runtime-requests.json'), (2, 'runtime-requests-v2.json')):
            profile = get_profile(version)
            actual = json.loads((Path(__file__).parent / 'runtimequalification/src/test/resources' / resource).read_bytes())
            self.assertEqual(actual, requests(contract, profile))
            self.assertEqual(actual['start']['params']['cwd'], 'file://' + profile.base + '/workspace')

    def test_posix_request_paths_survive_windows_packaging(self):
        contract = load_contract(); plan = requests(contract)
        start = plan["start"]["params"]
        self.assertEqual(start["cwd"], "file://" + BASE + "/workspace")
        self.assertEqual(start["env"]["FOLDGPT_PYTHON_REAL"], "@nativeLibraryDir/libfoldgpt_python_cli.so")
        self.assertEqual(plan["write"]["params"]["chunk"], "bmF0aXZlIGlucHV0Cg==")
        self.assertNotIn("\\", plan["file"]["params"]["path"])
        self.assertEqual(STAGE.parent, BUILD)
        self.assertEqual(PACKAGE, "app.foldgpt.runtimequalification.v1")

    def test_only_reviewed_stage_identity_is_admitted(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); cli = root / "python"; cli.write_bytes(b"unused")
            with self.assertRaisesRegex(ValueError, "identify"):
                stage_module.stage(root, cli, pin={"schema": "foldgpt.runtime-qualification.inputs.v1",
                    "package": "app.foldgpt.kernelqualification.v12", "base": BASE, "frozenName": root.name}, output=root / "out")
            self.assertFalse((root / "out").exists())

    def test_inventory_requires_exact_bytes_and_safe_names(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "source.py").write_bytes(b"value = 1\n")
            digest = hashlib.sha256((root / "source.py").read_bytes()).hexdigest()
            (root / "SOURCES.sha256").write_text(digest + "  source.py\n")
            self.assertEqual(stage_module.read_inventory(root, "SOURCES.sha256"), {"source.py": digest})
            (root / "source.py").write_bytes(b"value = 2\n")
            with self.assertRaises(ValueError): stage_module.read_inventory(root, "SOURCES.sha256")
            (root / "SOURCES.sha256").write_text(digest + "  ../source.py\n")
            with self.assertRaises(ValueError): stage_module.read_inventory(root, "SOURCES.sha256")

    def test_kernel_and_coerced_identity_never_authorize_material_collection(self):
        app = {"schema": "foldgpt.android-kernel-rpc.v1", "packageName": PACKAGE,
            "nativeBase": BASE, "diagnosticVersion": 1, "requestedAction": PACKAGE + ".RUNTIME_RUN_FIXED_V1"}
        native = {"schema": "foldgpt.bionic-runtime-qualification.private.v1", "workspace": BASE + "/workspace"}
        self.assertFalse(collector.identities(app, native)); self.assertFalse(collector.transport_clean(app, native))
        app["schema"] = "foldgpt.android-runtime-rpc.v1"
        self.assertTrue(collector.identities(app, native))
        app["diagnosticVersion"] = True
        self.assertFalse(collector.identities(app, native))

    def test_missing_actual_transport_wait_never_authorizes_material_collection(self):
        app = {"schema": "foldgpt.android-runtime-rpc.v1", "packageName": PACKAGE, "nativeBase": BASE,
            "diagnosticVersion": 1, "requestedAction": PACKAGE + ".RUNTIME_RUN_FIXED_V1", "transportCleanupComplete": True,
            "transport": {"schema": "foldgpt.shizuku.transport.v1", "bootstrapReaped": False, "cleanupComplete": True,
                "ownerRetained": True, "quarantined": False, "transportFailed": False, "refusedBeforeFork": False, "waitStatus": 0}}
        native = {"schema": "foldgpt.bionic-runtime-qualification.private.v1", "workspace": BASE + "/workspace",
            "nativeResult": {"cleanupComplete": True}, "quarantined": False, "supervisorWaited": True,
            "processClosed": True, "supervisorReturncode": 0, "bootstrapPid": 100, "supervisorPid": 101}
        self.assertFalse(collector.transport_clean(app, native))
        app["transport"].update(bootstrapReaped=True, ownerRetained=False, waitStatus=False)
        self.assertFalse(collector.transport_clean(app, native))


if __name__ == "__main__":
    unittest.main(verbosity=2)
