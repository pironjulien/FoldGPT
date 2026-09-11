"""Real filesystem/ZIP admission regressions; never runs Gradle or Android."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile

SPEC = importlib.util.spec_from_file_location("candidate_build", Path(__file__).with_name("build-production-candidate.py"))
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class CandidateAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root_patch = patch.object(candidate, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def put(self, name, data=b"input"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def descriptor(self):
        inputs = {}
        for name in candidate.PAYLOADS + candidate.TOOLCHAINS:
            self.put(name + "/input")
            inputs[name] = {"path": name, "files": candidate.inventory(self.root / name)}
        value = {"schema": candidate.SCHEMA, "scope": "test", "sdk": "sdkPlatform", "gradle": "gradleHome/input",
                 "buildToolsVersion": "36.0.0", "sdkPlatformDirectory": "android-37.0", "inputs": inputs}
        path = self.put("inputs.json", candidate.canonical(value))
        return path, candidate.digest_file(path), value

    def test_reject_changed_descriptor_before_reading_any_input(self):
        path, _, _ = self.descriptor()
        with self.assertRaisesRegex(ValueError, "descriptor digest"):
            candidate.admit_inputs(path, "0" * 64)

    def test_reject_mutated_file_with_valid_descriptor(self):
        path, sha, _ = self.descriptor()
        self.put("executor/input", b"tampered")
        with self.assertRaisesRegex(ValueError, "inventory/hash differs: executor"):
            candidate.admit_inputs(path, sha)

    def test_reject_uninventoried_file(self):
        path, sha, _ = self.descriptor()
        self.put("executor/extra", b"new")
        with self.assertRaisesRegex(ValueError, "inventory/hash differs: executor"):
            candidate.admit_inputs(path, sha)

    def test_reject_missing_file(self):
        path, sha, _ = self.descriptor()
        (self.root / "executor/input").unlink()
        with self.assertRaisesRegex(ValueError, "empty"):
            candidate.admit_inputs(path, sha)

    def test_duplicate_json_fields_refused(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            candidate.strict_json(b'{"schema":1,"schema":2}')

    def test_existing_attempt_preserved_including_empty_directory(self):
        output = self.root / "work/attempt"
        output.mkdir(parents=True)
        with self.assertRaises(FileExistsError):
            candidate.output_path(output)
        self.assertEqual(list(output.iterdir()), [])

    def test_outputs_refuse_project_root_other_directory_and_escape(self):
        for value in (self.root, self.root / "android/output", self.root / "work/../../escape"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                candidate.output_path(value)

    def test_exclusive_manifest_write_preserves_previous_bytes(self):
        path = self.put("work/input.json", b"preserved")
        with self.assertRaises(FileExistsError):
            candidate.write_new(path, {"replacement": True})
        self.assertEqual(path.read_bytes(), b"preserved")

    def test_current_executor_source_required_even_with_matching_manifest(self):
        source = self.put("tools/executor/example.py", b"current\n")
        self.put("executor/assets/foldgpt-executor/tools/executor/example.py", b"obsolete\n")
        self.put("executor/assets/foldgpt-executor-manifest.json", candidate.canonical([
            {"path": "tools/executor/example.py", "sha256": hashlib.sha256(b"obsolete\n").hexdigest()}]))
        with self.assertRaisesRegex(ValueError, "restage"):
            candidate.validate_source_closure(self.root / "executor")
        source.write_bytes(b"obsolete\r\n")
        self.assertEqual(candidate.validate_source_closure(self.root / "executor"), 1)

    def test_packaged_payload_bytes_checked_independently(self):
        path = self.put("runtime/arm64-v8a/libproot.so", b"approved")
        descriptor = {"inputs": {name: {"files": {}} for name in candidate.PAYLOADS}}
        descriptor["inputs"]["runtimeJni"]["files"] = candidate.inventory(path.parent.parent)
        apk = self.root / "candidate.apk"
        with ZipFile(apk, "w") as archive:
            archive.writestr("lib/arm64-v8a/libproot.so", b"changed")
        with self.assertRaisesRegex(ValueError, "Packaged input differs"):
            candidate.verify_packaged_inputs(apk, descriptor)

    def test_stale_x11_provenance_refused(self):
        self.put("x11/build-manifest.json", candidate.canonical({"sha256": "0" * 64}))
        trees = {"runtimeJni": {name: {} for name in candidate.RUNTIME},
                 "transportJni": {name: {} for name in candidate.TRANSPORT},
                 "x11Jni": {"arm64-v8a/libXlorie.so": {"sha256": "1" * 64}, "build-manifest.json": {}}}
        with self.assertRaisesRegex(ValueError, "does not identify"):
            candidate.validate_payloads({"x11Jni": self.root / "x11"}, trees)

    def test_preflight_does_not_create_output_or_run_gradle(self):
        self.put("gradle/bin/gradle", b"gradle")
        descriptor = {"gradle": "gradle/bin/gradle", "buildToolsVersion": "36.0.0"}
        paths = {name: self.root / name for name in candidate.PAYLOADS}
        args = argparse.Namespace(candidate="r47", output=self.root / "work/new", inputs=self.root / "manifest",
                                  inputs_sha256="0" * 64, preflight_only=True)
        with patch.object(candidate, "admit_inputs", return_value=(descriptor, paths, {})), patch.object(candidate.subprocess, "run") as run:
            result = candidate.build_candidate(args)
        self.assertEqual(result["preflight"], "PASS")
        self.assertFalse(args.output.exists())
        run.assert_not_called()
        for prop in ("RuntimeJni", "X11Jni", "FrozenTransportJni", "DebugJni", "DebugAssets", "ExecutorAssets", "ExecutorJni"):
            self.assertTrue(any(arg.startswith("-Pfoldgpt" + prop + "=") for arg in result["argv"]))


if __name__ == "__main__":
    unittest.main()
