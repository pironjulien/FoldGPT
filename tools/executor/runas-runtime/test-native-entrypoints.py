"""Exercise command/alias admission using a real APK; never claim Android execution."""
import argparse
import copy
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[3]
TRANSPORT = ROOT / "tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor"
sys.path.insert(0, str(TRANSPORT))
import foldgpt_native_bootstrap as bootstrap

spec = importlib.util.spec_from_file_location("native_apk_verifier", Path(__file__).with_name("verify-production-apk.py"))
verify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify)
ARGS = None


class NativeEntrypointsTests(unittest.TestCase):
    def setUp(self):
        with zipfile.ZipFile(ARGS.apk) as archive:
            self.config = json.loads(archive.read("assets/foldgpt-executor-deployment.json"))
            self.qualification = json.loads(archive.read("assets/foldgpt-executor-qualification.json"))
            self.runtime = json.loads(archive.read("assets/foldgpt-python-runtime.json"))
            self.binaries = {name: archive.read("lib/arm64-v8a/" + name)
                             for name in self.config["nativeLibraries"]}

    def check(self):
        return verify.verify_entrypoints(self.config, self.qualification, self.runtime, self.binaries.__getitem__)

    def test_actual_package_selection_and_aliases(self):
        self.assertEqual(self.check(), sorted(self.config["backendOptions"]["executables"]))

    def test_all_selected_commands_resolve_same_absolute_elf(self):
        native = PurePosixPath("/data/app/qualification/app.foldgpt/lib/arm64")
        declared = {name: value.replace("@nativeLibraryDir", str(native))
                    for name, value in self.config["backendOptions"]["executables"].items()}
        admitted = bootstrap.production_entrypoints(declared, native, self.config["nativeLibraries"])
        for name, path in declared.items():
            self.assertEqual(admitted[name], path)
            self.assertEqual(admitted[path], path)

    def test_arbitrary_entrypoint_is_rejected(self):
        self.config["backendOptions"]["executables"]["external"] = "/system/bin/sh"
        with self.assertRaises(ValueError): self.check()

    def test_python_cannot_be_relabelled_as_rg(self):
        self.config["backendOptions"]["executables"]["rg"] = "@nativeLibraryDir/libfoldgpt_python_cli.so"
        with self.assertRaises(ValueError): self.check()

    def test_duplicate_runtime_alias_is_rejected(self):
        self.runtime["runtimeAliases"].append(copy.deepcopy(self.runtime["runtimeAliases"][0]))
        with self.assertRaises(ValueError): self.check()

    def test_missing_command_alias_is_rejected(self):
        self.runtime["runtimeAliases"] = [item for item in self.runtime["runtimeAliases"] if item["path"] != "bin/bash"]
        with self.assertRaises(ValueError): self.check()

    def test_changed_alias_hash_is_rejected(self):
        self.runtime["runtimeAliases"][0]["sha256"] = "0" * 64
        with self.assertRaises(ValueError): self.check()

    def test_bootstrap_rejects_absolute_path_in_declared_map(self):
        native = PurePosixPath("/data/app/qualification/app.foldgpt/lib/arm64")
        declared = {name: value.replace("@nativeLibraryDir", str(native))
                    for name, value in self.config["backendOptions"]["executables"].items()}
        declared["/system/bin/sh"] = "/system/bin/sh"
        with self.assertRaises(ValueError):
            bootstrap.production_entrypoints(declared, native, self.config["nativeLibraries"])

    def rg(self):
        if "ripgrepBuild" not in self.qualification:
            self.skipTest("This actual APK predates native ripgrep")

    def test_rg_requires_provenance(self):
        self.rg()
        del self.qualification["ripgrepBuild"]
        with self.assertRaises(ValueError): self.check()

    def test_rg_requires_actual_probe_bytes(self):
        self.rg()
        self.binaries["libfoldgpt_pcre2_jit_probe.so"] += b"changed"
        with self.assertRaises(ValueError): self.check()

    def test_rg_requires_actual_cli_bytes(self):
        self.rg()
        self.binaries["libfoldgpt_rg.so"] += b"changed"
        with self.assertRaises(ValueError): self.check()

    def test_rg_rejects_unselected_native_library(self):
        self.rg()
        del self.config["backendOptions"]["executables"]["rg"]
        with self.assertRaises(ValueError): self.check()

    def test_rg_provenance_cannot_escape_project(self):
        self.rg()
        self.qualification["ripgrepBuild"]["path"] = "../outside"
        with self.assertRaises(ValueError): self.check()

    def test_rg_build_cannot_claim_android_execution(self):
        self.rg()
        self.qualification["ripgrepBuild"]["androidExecuted"] = True
        with self.assertRaises(ValueError): self.check()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    ARGS = parser.parse_args()
    ARGS.output.resolve().relative_to(ROOT)
    if ARGS.output.exists():
        raise FileExistsError("Retain previous test evidence")
    result = unittest.main(argv=[sys.argv[0]], verbosity=2, exit=False).result
    record = {"success": result.wasSuccessful(), "testsRun": result.testsRun,
              "androidExecuted": False, "apkSha256": verify.digest(ARGS.apk.read_bytes()),
              "failures": [{"test": test.id(), "detail": detail} for test, detail in result.failures],
              "errors": [{"test": test.id(), "detail": detail} for test, detail in result.errors],
              "skipped": [{"test": test.id(), "reason": reason} for test, reason in result.skipped]}
    with ARGS.output.open("x", encoding="utf-8") as destination:
        json.dump(record, destination, indent=2)
        destination.write("\n")
    raise SystemExit(0 if result.wasSuccessful() else 1)
