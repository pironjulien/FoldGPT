"""Real process-path resolution of the immutable-package cwd option, PC only.

Copies the host Python executable and actual built shim into an isolated test
package directory. This checks path/digest admission, not Android isolation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
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


def run(shim):
    if os.getuid() == 0:
        raise SystemExit("Use an ordinary Linux UID")
    actual = Path(os.readlink("/proc/self/exe"))
    with tempfile.TemporaryDirectory(prefix="foldgpt-package-path-", dir="/var/tmp") as temporary:
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
            result = subprocess.run([str(interpreter), "-I", "-S", "-c", ENTRY, str(BOOTSTRAP), json.dumps(value)],
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
        print(json.dumps({"success": True, "scope": "host-package-path-admission", "uid": os.getuid(),
                          "androidExecution": False, "observations": observations}, indent=2))


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: verify-deployment-host.py ACTUAL_HOST_SHIM_LIBRARY")
    run(Path(sys.argv[1]).resolve(strict=True))
