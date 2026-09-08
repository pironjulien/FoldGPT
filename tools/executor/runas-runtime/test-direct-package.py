"""PC package/admission regressions over actual built bytes; no Android execution."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


stage = module("review_native_stage", Path(__file__).with_name("stage-production-native.py"))
verify = module("review_native_apk", Path(__file__).with_name("verify-production-apk.py"))
ARGS = None
OBSERVATIONS = []


class DirectBuildAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="build-case-", dir=ARGS.output)
        self.directory = Path(self.temporary.name) / "build"
        shutil.copytree(ARGS.direct_build, self.directory)

    def tearDown(self):
        self.temporary.cleanup()

    def record(self, filename, transform):
        path = self.directory / filename
        data = json.loads(path.read_bytes())
        transform(data)
        path.write_text(json.dumps(data, indent=2) + "\n")

    def refuse(self):
        with self.assertRaises((ValueError, OSError, AssertionError)) as failure:
            stage.production_direct(self.directory)
        OBSERVATIONS.append({"test": self.id(), "refused": True, "error": str(failure.exception)})

    def test_real_build_is_admitted(self):
        data, provenance = stage.production_direct(self.directory)
        self.assertEqual(data, (ARGS.direct_build / "libfoldgpt_direct_runner.so").read_bytes())
        self.assertEqual(provenance["executableSha256"], hashlib.sha256(data).hexdigest())
        OBSERVATIONS.append({"test": self.id(), "admitted": True, "provenance": provenance})

    def test_changed_runner_bytes_are_refused(self):
        target = self.directory / "libfoldgpt_direct_runner.so"
        target.write_bytes(target.read_bytes() + b"changed")
        self.refuse()

    def test_changed_actual_second_compile_is_refused(self):
        target = self.directory / "direct-runner.repeat.so"
        target.write_bytes(target.read_bytes() + b"changed")
        self.refuse()

    def test_changed_frozen_source_is_refused(self):
        target = self.directory / "source/direct-runner.c"
        target.write_bytes(target.read_bytes() + b"\n/* changed */\n")
        self.refuse()

    def test_missing_source_is_refused(self):
        (self.directory / "source/direct-api.md").unlink()
        self.refuse()

    def test_wrong_ndk_or_api_is_refused(self):
        self.record("build.json", lambda value: value.update(apiLevel=34))
        self.refuse()

    def test_false_recompile_record_is_refused(self):
        self.record("build.json", lambda value: value["binaries"][0].update(realRecompilationIdentical=False))
        self.refuse()

    def test_inspection_metadata_cannot_substitute_for_actual_elf(self):
        self.record("direct-runner.elf.json", lambda value: value.update(sha256="0" * 64))
        self.refuse()

    def test_manifest_duplicate_cannot_hide_a_source(self):
        self.record("sources.json", lambda value: value.__setitem__(1, value[0]))
        digest = hashlib.sha256((self.directory / "sources.json").read_bytes()).hexdigest()
        self.record("build.json", lambda value: value.update(sourceManifestSha256=digest))
        self.refuse()

    def test_binary_alias_outside_snapshot_is_refused(self):
        target = self.directory / "libfoldgpt_direct_runner.so"
        target.unlink()
        try:
            target.symlink_to(ARGS.direct_build / target.name)
        except OSError as error:
            self.skipTest("Host cannot create a real symlink: " + str(error))
        self.refuse()

    def test_source_alias_outside_snapshot_is_refused(self):
        target = self.directory / "source/direct-runner.c"
        target.unlink()
        try:
            target.symlink_to(ARGS.direct_build / "source" / target.name)
        except OSError as error:
            self.skipTest("Host cannot create a real symlink: " + str(error))
        self.refuse()

    @unittest.skipUnless(sys.platform == "win32", "Windows directory junction regression")
    def test_source_directory_junction_is_refused(self):
        source = self.directory / "source"
        held = self.directory / "source-held"
        source.resolve(strict=True).relative_to(self.directory.resolve(strict=True))
        held.resolve().relative_to(self.directory.resolve(strict=True))
        source.rename(held)
        def quote(path):
            return "'" + str(path).replace("'", "''") + "'"
        command = "New-Item -ItemType Junction -Path " + quote(source) + " -Target " + quote(ARGS.direct_build / "source") + " | Out-Null"
        subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command], check=True, capture_output=True)
        try:
            self.assertTrue(source.is_junction())
            self.refuse()
        finally:
            # Remove only the verified junction itself before fixture cleanup;
            # never recurse into its external snapshot target.
            if source.is_junction():
                source.rmdir()


class ModelPackageSelectionTests(unittest.TestCase):
    def setUp(self):
        assets = ARGS.package / "assets"
        self.config = json.loads((assets / "foldgpt-executor-deployment.json").read_bytes())
        self.qualification = json.loads((assets / "foldgpt-executor-qualification.json").read_bytes())
        self.sources = {row["path"] for row in json.loads((assets / "foldgpt-executor-manifest.json").read_bytes())}
        self.runner = (ARGS.package / "jniLibs/arm64-v8a/libfoldgpt_direct_runner.so").read_bytes()

    def check(self):
        return verify.verify_model_selection(self.config, self.qualification,
            lambda name: self.runner if name == "libfoldgpt_direct_runner.so" else (_ for _ in ()).throw(KeyError(name)), self.sources)

    def test_real_explicit_package_selects_both_distinct_profiles(self):
        self.assertEqual(self.check(), ["managed", "ordinaryUid"])

    def test_absent_option_keeps_managed_even_when_code_and_elf_exist(self):
        del self.config["backendOptions"]["ordinaryUid"]
        del self.qualification["ordinaryUidBuild"]
        self.assertEqual(self.check(), ["managed"])

    def test_absent_option_with_stray_attestation_is_refused(self):
        del self.config["backendOptions"]["ordinaryUid"]
        with self.assertRaises(ValueError): self.check()

    def test_selected_option_requires_build_attestation(self):
        del self.qualification["ordinaryUidBuild"]
        with self.assertRaises(ValueError): self.check()

    def test_attestation_must_identify_the_actual_runner(self):
        self.qualification["ordinaryUidBuild"]["executableSha256"] = "0" * 64
        with self.assertRaises(ValueError): self.check()

    def test_attestation_length_is_checked(self):
        self.qualification["ordinaryUidBuild"]["bytes"] += 1
        with self.assertRaises(ValueError): self.check()

    def test_selected_code_closure_is_complete(self):
        self.sources.remove("tools/executor/bionic-supervisor/direct_wire.py")
        with self.assertRaises(ValueError): self.check()

    def test_model_workspace_authority_cannot_be_added_to_deployment_option(self):
        self.config["backendOptions"]["ordinaryUid"]["workspace"] = "/untrusted"
        with self.assertRaises(ValueError): self.check()

    def test_arbitrary_process_path_is_refused(self):
        self.config["backendOptions"]["ordinaryUid"]["processRunner"] = "/data/local/tmp/custom.so"
        with self.assertRaises(ValueError): self.check()

    def test_nonstandard_production_limits_are_refused(self):
        self.config["backendOptions"]["ordinaryUid"]["limits"] = {"uid_tasks": 1000}
        with self.assertRaises(ValueError): self.check()

    def test_duplicate_json_authority_field_is_refused(self):
        with self.assertRaises(ValueError): verify.strict_json('{"ordinaryUid":null,"ordinaryUid":{}}')

    def test_parent_path_in_build_attestation_is_refused(self):
        self.qualification["ordinaryUidBuild"]["path"] = "../foreign-build"
        with self.assertRaises(ValueError): self.check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--direct-build", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ARGS = parser.parse_args()
    for name in ("direct_build", "package", "output"):
        value = getattr(ARGS, name).resolve()
        value.relative_to(ROOT)
        setattr(ARGS, name, value)
    ARGS.output.mkdir(parents=True, exist_ok=False)
    result = unittest.main(argv=[sys.argv[0]], verbosity=2, exit=False).result
    (ARGS.output / "results.json").write_text(json.dumps({"schema": "foldgpt.direct.package.tests.v1",
        "success": result.wasSuccessful(), "testsRun": result.testsRun,
        "passed": result.testsRun - len(result.failures) - len(result.errors) - len(result.skipped),
        "failures": [{"test": test.id(), "detail": detail} for test, detail in result.failures],
        "errors": [{"test": test.id(), "detail": detail} for test, detail in result.errors],
        "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped],
        "androidExecuted": False, "directBuild": str(ARGS.direct_build), "package": str(ARGS.package),
        "observations": OBSERVATIONS}, indent=2) + "\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
