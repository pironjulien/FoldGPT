"""PC-only independent-identity/input checks. Does not invoke Gradle or ADB."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from qualification_profiles import BY_PACKAGE, HERE, PROFILES, for_version

REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tools/runtime"))
from qualification_identity import resolve_identity


def script(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), HERE / name)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackagingTests(unittest.TestCase):
    def test_fixed_versions_and_runtime_identities_agree(self):
        for version, profile in PROFILES.items():
            identity = resolve_identity(profile.package, profile.base, version)
            self.assertEqual(identity.workspace, profile.base + "/workspace")
            self.assertEqual(BY_PACKAGE[profile.package], profile)
        for value in (True, "12", 10, 13, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                for_version(value)

    def test_v11_outputs_preserved_and_v12_disjoint(self):
        old, new = for_version(11), for_version(12)
        self.assertEqual(old.stage, HERE / "build/qualification-stage-v11")
        self.assertEqual(old.apk, HERE / "qualification/build/outputs/apk/debug/qualification-debug.apk")
        self.assertEqual(new.stage, HERE / "build/qualification-v12/qualification-stage-v12")
        self.assertEqual(new.apk, HERE / "build/qualification-v12/modules/qualification/outputs/apk/debug/qualification-debug.apk")
        self.assertFalse(new.stage.is_relative_to(old.stage))
        self.assertFalse(new.apk.is_relative_to(old.apk.parent))

    def test_v12_pin_authenticates_actual_corrected_frozen_inputs(self):
        profile = for_version(12)
        pin = json.loads(profile.inputs.read_text())
        self.assertEqual((pin["package"], pin["base"]), (profile.package, profile.base))
        self.assertIs(pin["androidExecution"], False)
        self.assertEqual(pin["frozenName"], "foldgpt-bionic-supervisor-PHREPY0u")
        frozen = REPO / "downloads/bionic-supervisor" / pin["frozenName"]
        for name, digest in pin["frozenFiles"].items():
            self.assertEqual(Path(name).name, name)
            self.assertEqual(hashlib.sha256((frozen / name).read_bytes()).hexdigest(), digest)
        cli = REPO / "downloads/native-kernel-trial/python-cli-v12/libfoldgpt_python_cli.so"
        self.assertEqual(hashlib.sha256(cli.read_bytes()).hexdigest(), pin["pythonCliSha256"])
        self.assertIn((profile.base + "/python").encode(), cli.read_bytes())

    def test_apk_selected_factory_has_exact_base_and_shared_implementation(self):
        profile = for_version(12)
        path = REPO / "tools/executor/bionic-supervisor" / (profile.factory_module + ".py")
        tree = ast.parse(path.read_text())
        base = next(node for node in tree.body if isinstance(node, ast.Assign))
        self.assertEqual(ast.literal_eval(base.value.args[0]), profile.base)
        function = next(node for node in tree.body if isinstance(node, ast.FunctionDef))
        call = function.body[0].value
        self.assertEqual(call.func.id, "_factory")
        self.assertEqual([arg.id for arg in call.args], ["options", "BASE"])

    def test_wrong_frozen_build_refused_before_stage_creation(self):
        module = script("stage-qualification.py")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "uncreated"
            argv = ["stage-qualification.py", "--frozen", temporary, "--python-cli", temporary,
                    "--package", for_version(12).package, "--output", str(output)]
            with patch.object(sys, "argv", argv), self.assertRaisesRegex(ValueError, "reviewed identity"):
                module.main()
            self.assertFalse(output.exists())

    def test_unknown_verifier_version_refused_before_output_creation(self):
        module = script("verify-qualification.py")
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "uncreated"
            with self.assertRaises(SystemExit) as failure:
                module.main(["--version", "13", "--output", str(output)])
            self.assertEqual(failure.exception.code, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
