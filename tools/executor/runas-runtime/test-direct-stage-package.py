"""Exercise real native package assembly and refuse altered stage provenance on PC."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[3]
PACKAGER = Path(__file__).with_name("stage-production-package.py")
spec = importlib.util.spec_from_file_location("package_selection_review", PACKAGER.with_name("verify-production-apk.py"))
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)
ARGS = None
OBSERVATIONS = []


class StagePackageAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="assembly-case-", dir=ARGS.output)
        self.directory = Path(self.temporary.name)
        self.stage = self.directory / "stage"
        shutil.copytree(ARGS.native_stage, self.stage)
        self.output = self.directory / "package"

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *, ordinary=True):
        command = [sys.executable, "-B", str(PACKAGER), "--native-stage", str(self.stage),
            "--admission-build", str(ARGS.admission_build), "--output", str(self.output), "--host-v2"]
        if ordinary:
            command.append("--ordinary-uid")
        result = subprocess.run(command, capture_output=True, text=True, timeout=60)
        OBSERVATIONS.append({"test": self.id(), "returncode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr, "outputCreated": self.output.exists()})
        return result

    def change_manifest(self, transform):
        path = self.stage / "manifest.json"
        record = json.loads(path.read_bytes())
        transform(record)
        path.write_text(json.dumps(record, indent=2) + "\n")

    def assert_refused_before_output(self):
        result = self.invoke()
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertIn("Ordinary UID stage differs", result.stderr)
        self.assertFalse(self.output.exists(), "Rejected provenance must not leave a package candidate")

    def check_selection(self, ordinary):
        result = self.invoke(ordinary=ordinary)
        self.assertEqual(result.returncode, 0, result.stderr)
        assets = self.output / "assets"
        config = json.loads((assets / "foldgpt-executor-deployment.json").read_bytes())
        qualification = json.loads((assets / "foldgpt-executor-qualification.json").read_bytes())
        manifest = json.loads((assets / "foldgpt-executor-manifest.json").read_bytes())
        sources = {row["path"] for row in manifest}
        profiles = verifier.verify_model_selection(config, qualification,
            lambda name: (self.output / "jniLibs/arm64-v8a" / name).read_bytes(), sources)
        self.assertEqual(profiles, ["managed", "ordinaryUid"] if ordinary else ["managed"])
        # Shared modules must stay in the package regardless of mode selection.
        self.assertTrue({"tools/executor/native_model_profiles.py", "tools/executor/ordinary_uid_files.py",
            "tools/executor/bionic-supervisor/direct_processes.py",
            "tools/executor/bionic-supervisor/direct_wire.py"} <= sources)
        for row in manifest:
            data = (assets / "foldgpt-executor" / row["path"]).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(), row["sha256"])

    def test_real_ordinary_package_is_assembled(self):
        self.check_selection(True)

    def test_unselected_package_keeps_managed_profile_and_source_closure(self):
        self.check_selection(False)

    def test_altered_provenance_is_refused_before_output(self):
        self.change_manifest(lambda record: record["ordinaryUidBuild"].update(executableSha256="0" * 64))
        self.assert_refused_before_output()

    def test_changed_runner_with_consistent_stage_inventory_is_refused_before_output(self):
        relative = "jniLibs/arm64-v8a/libfoldgpt_direct_runner.so"
        target = self.stage / relative
        data = target.read_bytes() + b"altered staged runner"
        target.write_bytes(data)
        def alter(record):
            rows = [row for row in record["files"] if row["path"] == relative]
            self.assertEqual(len(rows), 1)
            rows[0].update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
        self.change_manifest(alter)
        self.assert_refused_before_output()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-stage", type=Path, required=True)
    parser.add_argument("--admission-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ARGS = parser.parse_args()
    for name in ("native_stage", "admission_build", "output"):
        path = getattr(ARGS, name).resolve()
        path.relative_to(ROOT)
        setattr(ARGS, name, path)
    ARGS.output.mkdir(parents=True, exist_ok=False)
    result = unittest.main(argv=[sys.argv[0]], verbosity=2, exit=False).result
    (ARGS.output / "results.json").write_text(json.dumps({"schema": "foldgpt.direct.package.assembly-tests.v1",
        "success": result.wasSuccessful(), "testsRun": result.testsRun,
        "failures": [{"test": test.id(), "detail": detail} for test, detail in result.failures],
        "errors": [{"test": test.id(), "detail": detail} for test, detail in result.errors],
        "androidExecuted": False, "nativeStage": str(ARGS.native_stage),
        "admissionBuild": str(ARGS.admission_build), "observations": OBSERVATIONS}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
