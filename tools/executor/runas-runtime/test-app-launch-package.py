"""Cross-origin and altered-byte checks using real compiled launcher outputs."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
ARGS = None


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


admit = load("app_build_admission", Path(__file__).with_name("app-launch-admission.py"))
verify = load("app_package_verification", Path(__file__).with_name("verify-production-apk.py"))


class AppLaunchPackageTests(unittest.TestCase):
    def setUp(self):
        assets = ARGS.package / "assets"
        self.config = json.loads((assets / "foldgpt-executor-deployment.json").read_bytes())
        self.proof = json.loads((assets / "foldgpt-executor-qualification.json").read_bytes())
        self.sources = {row["path"] for row in json.loads((assets / "foldgpt-executor-manifest.json").read_bytes())}
        self.assets = {"foldgpt-app-launch-build.json": (assets / "foldgpt-app-launch-build.json").read_bytes()}
        self.binaries = {name: (ARGS.package / "jniLibs/arm64-v8a" / name).read_bytes()
                         for name in (admit.BOOTSTRAP, admit.TRANSPORT)}

    def check(self):
        return verify.verify_launch_origin(self.config, self.proof, self.assets.__getitem__, self.binaries.__getitem__, self.sources)

    def change_attestation(self, transform):
        value = json.loads(self.assets["foldgpt-app-launch-build.json"])
        transform(value)
        data = json.dumps(value).encode()
        self.assets["foldgpt-app-launch-build.json"] = data
        self.proof["appLaunchBuildSha256"] = hashlib.sha256(data).hexdigest()

    def test_real_application_package(self):
        self.assertEqual(self.check(), "android-app")

    def test_legacy_apk_remains_accepted(self):
        with zipfile.ZipFile(ARGS.legacy_apk) as archive:
            def asset(name): return archive.read("assets/" + name)
            config = json.loads(asset("foldgpt-executor-deployment.json"))
            proof = json.loads(asset("foldgpt-executor-qualification.json"))
            sources = {row["path"] for row in json.loads(asset("foldgpt-executor-manifest.json"))}
            self.assertEqual(verify.verify_launch_origin(config, proof, asset,
                lambda name: archive.read("lib/arm64-v8a/" + name), sources), "run-as")

    def test_false_origin_is_refused(self):
        self.config["launchOrigin"] = "run-as"
        with self.assertRaises(ValueError): self.check()

    def test_v1_cannot_select_app_libraries(self):
        self.config["schema"] = "foldgpt.native.deployment.v1"
        del self.config["launchOrigin"]
        with self.assertRaises(ValueError): self.check()

    def test_app_package_cannot_include_runas_bootstrap(self):
        self.config["nativeLibraries"]["libfoldgpt_native_bootstrap.so"] = "0" * 64
        with self.assertRaises(ValueError): self.check()

    def test_changed_transport_with_consistent_deployment_hash_is_refused(self):
        self.binaries[admit.TRANSPORT] += b"modified"
        self.config["nativeLibraries"][admit.TRANSPORT] = hashlib.sha256(self.binaries[admit.TRANSPORT]).hexdigest()
        with self.assertRaises(ValueError): self.check()

    def test_changed_bootstrap_with_consistent_deployment_hash_is_refused(self):
        self.binaries[admit.BOOTSTRAP] += b"modified"
        self.config["nativeLibraries"][admit.BOOTSTRAP] = hashlib.sha256(self.binaries[admit.BOOTSTRAP]).hexdigest()
        with self.assertRaises(ValueError): self.check()

    def test_legacy_admission_attestation_is_refused(self):
        self.change_attestation(lambda value: value["bootstrapBuild"].update(schema="foldgpt.native-admission-build.v1", inheritedSeccomp=0))
        with self.assertRaises(ValueError): self.check()

    def test_missing_source_closure_is_refused(self):
        self.sources.remove("foldgpt_app_bootstrap.py")
        with self.assertRaises(ValueError): self.check()

    def test_missing_attestation_binding_is_refused(self):
        del self.proof["appLaunchBuildSha256"]
        with self.assertRaises(ValueError): self.check()

    def test_execution_claim_is_not_synthesized(self):
        self.change_attestation(lambda value: value.update(androidProductionExecuted=True))
        with self.assertRaises(ValueError): self.check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--legacy-apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ARGS = parser.parse_args()
    for name in ("package", "legacy_apk", "output"):
        path = getattr(ARGS, name).resolve()
        path.relative_to(ROOT)
        setattr(ARGS, name, path)
    if ARGS.output.exists():
        raise FileExistsError("Preserve previous package verification")
    result = unittest.main(argv=[sys.argv[0]], exit=False, verbosity=2).result
    ARGS.output.parent.mkdir(parents=True, exist_ok=True)
    ARGS.output.write_text(json.dumps({"success": result.wasSuccessful(), "testsRun": result.testsRun,
        "failures": [(case.id(), detail) for case, detail in result.failures],
        "errors": [(case.id(), detail) for case, detail in result.errors], "androidExecuted": False}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
