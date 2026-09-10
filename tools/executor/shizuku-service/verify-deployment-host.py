"""Real process-path admission of installed cwd/direct options, PC only.

Copies the host Python executable and actual built shim into an isolated test
package directory. This checks path/digest admission, not Android isolation.
"""
import hashlib
import argparse
import copy
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BOOTSTRAP = HERE / "transport/src/main/assets/foldgpt-executor"
LIBRARY_NAME = "libfoldgpt_bionic_cwd.so"
MARKER = "@nativeLibraryDir/" + LIBRARY_NAME
ENTRY = """import json,os,sys
sys.path.insert(0,sys.argv[1])
from foldgpt_shizuku_bootstrap import installed_backend_options
config=json.loads(sys.argv[2])
try:
 result=installed_backend_options(config)
 print(json.dumps({'ok':True,'options':result,'actualExecutable':os.readlink('/proc/self/exe')}))
except (ValueError,OSError) as error:
 print(json.dumps({'ok':False,'error':str(error)}))
"""


def run(shim, direct_runner=None, output=None):
    if sys.flags.optimize:
        raise SystemExit("Admission verification requires enabled assertions")
    if os.getuid() == 0:
        raise SystemExit("Use an ordinary Linux UID")
    actual = Path(os.readlink("/proc/self/exe"))
    output = (output or ROOT / "work/deployment-host-tests").resolve()
    output.relative_to(ROOT.resolve())
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="foldgpt-package-path-", dir=output) as temporary:
        directory = Path(temporary)
        interpreter = directory / "libfoldgpt_python_cli.so"
        shutil.copyfile(actual, interpreter)
        interpreter.chmod(0o755)
        library = directory / LIBRARY_NAME
        shutil.copyfile(shim, library)
        library.chmod(0o644)
        digest = hashlib.sha256(library.read_bytes()).hexdigest()
        config = {"pythonLibrary": interpreter.name,
                  "backendOptions": {"cwdShim": {"path": MARKER, "sha256": digest}, "preserved": {"nested": [1, None]}}}

        def invoke(value):
            result = subprocess.run([str(interpreter), "-I", "-S", "-B", "-c", ENTRY, str(BOOTSTRAP), json.dumps(value)],
                env={}, capture_output=True, text=True, check=True, timeout=10)
            return json.loads(result.stdout)

        good = invoke(config)
        assert good["ok"] and good["actualExecutable"] == str(interpreter), good
        assert good["options"] == {**config["backendOptions"], "cwdShim": {"path": str(library), "sha256": digest}}, good
        assert config["backendOptions"]["cwdShim"]["path"] == MARKER
        observations = {"actualPackagePath": str(directory), "success": good}
        native_config = {"pythonLibrary": interpreter.name, "pythonSha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(),
            "nativeLibraries": {interpreter.name: hashlib.sha256(interpreter.read_bytes()).hexdigest(), LIBRARY_NAME: digest},
            "backendOptions": {"helper": MARKER, "handleHelper": MARKER, "processRunner": MARKER,
                "executables": {"fixed-worker": MARKER}, "runtime": [{"path": MARKER, "execute": True},
                    {"path": "/system/lib64", "execute": True}], "workspace": "/unchanged-workspace"}}
        native_good = invoke(native_config)
        assert native_good["ok"] and native_good["options"]["helper"] == str(library), native_good
        assert native_good["options"]["executables"] == {"fixed-worker": str(library)}, native_good
        assert native_good["options"]["runtime"] == [{"path": str(library), "execute": True},
                    {"path": "/system/lib64", "execute": True}], native_good
        assert native_good["options"]["workspace"] == "/unchanged-workspace", native_good
        assert native_config["backendOptions"]["helper"] == MARKER
        observations["nativeInventory"] = native_good
        assert "ordinaryUid" not in native_good["options"], native_good
        if direct_runner is not None:
            direct_library = directory / "libfoldgpt_direct_runner.so"
            shutil.copyfile(direct_runner, direct_library)
            direct_library.chmod(0o755)
            direct_digest = hashlib.sha256(direct_library.read_bytes()).hexdigest()
            direct_marker = "@nativeLibraryDir/" + direct_library.name
            direct_config = copy.deepcopy(native_config)
            direct_config["nativeLibraries"][direct_library.name] = direct_digest
            direct_config["backendOptions"]["ordinaryUid"] = {"processRunner": direct_marker, "limits": {}}
            direct_original = copy.deepcopy(direct_config)
            direct_good = invoke(direct_config)
            assert direct_good["ok"], direct_good
            assert direct_good["options"]["ordinaryUid"] == {"processRunner": str(direct_library), "limits": {}}, direct_good
            assert direct_config == direct_original
            # Merely installing the attested ELF never enables its profile.
            absent = copy.deepcopy(direct_config)
            del absent["backendOptions"]["ordinaryUid"]
            absent_result = invoke(absent)
            assert absent_result["ok"] and "ordinaryUid" not in absent_result["options"], absent_result
            observations["ordinaryUidSelected"] = direct_good
            observations["ordinaryUidNotSelected"] = absent_result
            failures = {}
            for name, selected in {
                "null": None,
                "missingLimits": {"processRunner": direct_marker},
                "extraAuthority": {"processRunner": direct_marker, "limits": {}, "workspace": "/foreign"},
                "wrongLimitsType": {"processRunner": direct_marker, "limits": []},
                "absoluteRunner": {"processRunner": str(direct_library), "limits": {}},
                "foreignRunner": {"processRunner": "@nativeLibraryDir/libforeign.so", "limits": {}},
                "traversalRunner": {"processRunner": "@nativeLibraryDir/../libfoldgpt_direct_runner.so", "limits": {}},
            }.items():
                case = copy.deepcopy(direct_config)
                case["backendOptions"]["ordinaryUid"] = selected
                failure = invoke(case)
                assert not failure["ok"], (name, failure)
                failures[name] = failure
            no_inventory = copy.deepcopy(direct_config)
            del no_inventory["nativeLibraries"]
            failure = invoke(no_inventory)
            assert not failure["ok"], failure
            failures["missingInventory"] = failure
            wrong_digest = copy.deepcopy(direct_config)
            wrong_digest["nativeLibraries"][direct_library.name] = "0" * 64
            failure = invoke(wrong_digest)
            assert not failure["ok"], failure
            failures["wrongDigest"] = failure
            original_direct = directory / "direct-original.so"
            direct_library.rename(original_direct)
            direct_library.symlink_to(original_direct)
            failure = invoke(direct_config)
            assert not failure["ok"] and "alias" in failure["error"], failure
            failures["runnerAlias"] = failure
            direct_library.unlink()
            failure = invoke(direct_config)
            assert not failure["ok"], failure
            failures["missingRunner"] = failure
            original_direct.rename(direct_library)
            direct_library.chmod(0o777)
            failure = invoke(direct_config)
            assert not failure["ok"], failure
            failures["writableRunner"] = failure
            direct_library.chmod(0o755)
            observations["ordinaryUidRefusals"] = failures
        for field in ("helper", "handleHelper", "processRunner"):
            bad = invoke({**native_config, "backendOptions": {**native_config["backendOptions"], field: str(library)}})
            assert not bad["ok"], bad
        bad = invoke({**native_config, "nativeLibraries": {**native_config["nativeLibraries"], LIBRARY_NAME: "0" * 64}})
        assert not bad["ok"], bad
        bad = invoke({**native_config, "backendOptions": {**native_config["backendOptions"], "executables": {"fixed-worker": "@nativeLibraryDir/libabsent.so"}}})
        assert not bad["ok"], bad
        for name, invalid in {
            "absolute": {"path": str(library), "sha256": digest},
            "traversal": {"path": "@nativeLibraryDir/../" + LIBRARY_NAME, "sha256": digest},
            "otherLibrary": {"path": "@nativeLibraryDir/libother.so", "sha256": digest},
            "wrongDigest": {"path": MARKER, "sha256": "0" * 64},
            "extraField": {"path": MARKER, "sha256": digest, "override": True},
        }.items():
            bad = invoke({**config, "backendOptions": {"cwdShim": invalid}})
            assert not bad["ok"], bad
            observations[name] = bad
        bad = invoke({**config, "pythonLibrary": "libnot_the_running_interpreter.so"})
        assert not bad["ok"] and "Actual bootstrap executable differs" in bad["error"], bad
        observations["actualInterpreterMismatch"] = bad
        renamed = directory / "original.so"
        library.rename(renamed)
        library.symlink_to(renamed)
        bad = invoke(config)
        assert not bad["ok"] and "alias" in bad["error"], bad
        observations["symlink"] = bad
        library.unlink()
        bad = invoke(config)
        assert not bad["ok"], bad
        observations["missing"] = bad
        renamed.rename(library)
        library.chmod(0o666)
        bad = invoke(config)
        assert not bad["ok"] and "ordinary package file" in bad["error"], bad
        observations["writable"] = bad
        result = {"success": True, "scope": "host-package-path-admission", "uid": os.getuid(),
                  "ordinaryUidAdmissionTested": direct_runner is not None,
                  "androidExecution": False, "observations": observations}
        (output / "deployment-host-results.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("shim", type=Path)
    parser.add_argument("--direct-runner", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    run(args.shim.resolve(strict=True), args.direct_runner.resolve(strict=True) if args.direct_runner else None,
        args.output)
