"""The runtime diagnostic has no configurable application/base aliases."""
from pathlib import Path
import importlib.util
import sys
from dataclasses import dataclass

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO / "tools/runtime"))
from runtime_qualification_identity import RuntimeQualificationIdentity, runtime_identity


@dataclass(frozen=True)
class RuntimeProfile:
    identity: RuntimeQualificationIdentity

    @property
    def version(self): return self.identity.report_version
    @property
    def package(self): return self.identity.package
    @property
    def base(self): return self.identity.base
    @property
    def build(self): return HERE / ("build/runtimequalification-v" + str(self.version))
    @property
    def stage(self): return self.build / ("runtime-stage-v" + str(self.version))
    @property
    def apk(self): return self.build / "modules/runtimequalification/outputs/apk/debug/runtimequalification-debug.apk"
    @property
    def inputs(self): return HERE / ("runtimequalification-inputs-v" + str(self.version) + ".json")
    @property
    def backend_factory(self): return self.identity.backend_factory
    @property
    def retained_packages(self): return self.identity.retained_packages


def get_profile(version=1):
    return RuntimeProfile(runtime_identity(version))


V1 = get_profile(1)
PACKAGE, BASE = V1.package, V1.base
BUILD, STAGE, APK, INPUTS = V1.build, V1.stage, V1.apk, V1.inputs
JNI = REPO / "tools/executor/shizuku-lab/build/frozen-transport-jni/arm64-v8a"
CERTIFICATE = "30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16"
RETAINED_PACKAGES = V1.retained_packages


def load_contract(root=REPO):
    path = Path(root) / "tools/executor/bionic-supervisor/runtime_qualification.py"
    spec = importlib.util.spec_from_file_location("foldgpt_runtime_contract", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if str(module.BASE) != BASE:
        raise ValueError("Runtime contract belongs to a different native base")
    return module


def requests(contract, profile=V1):
    workspace = profile.base + "/workspace"
    return {"schema": "foldgpt.runtime-qualification.requests.v1",
        "start": {"id": 2, "method": "process/start", "params": contract.process_request(
            workspace, "@nativeLibraryDir/libfoldgpt_python_cli.so")},
        "write": {"id": 3, "method": "process/write", "params": contract.input_request()},
        "read": {"id": 4, "method": "process/read", "params": {"processId": contract.PROCESS_ID}},
        "file": {"id": 5, "method": "fs/readFile", "params": contract.file_request(workspace)}}
