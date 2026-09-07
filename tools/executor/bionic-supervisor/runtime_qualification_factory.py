"""One APK-owned small-project request over the unchanged dynamic native factory.

This facade is diagnostic admission, not a replacement for syscall mediation.
Only the package's actual interpreter location supplies the native runtime
directory. No model RPC chooses executable mappings, runtime grants or evidence.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import sys

from tools.executor.exec_server import RpcError
from .factory import factory as native_factory
from .qualification_factory import QualificationBackend, bootstrap_identity, canonical, open_evidence
from .runtime_qualification import (BASE, LIMITS, PROCESS_ID, file_request, input_request,
                                    process_request, validate_artifacts, validate_report)

SYSTEM_RUNTIME = (("/system/lib64", True), ("/system/bin/linker64", True),
    ("/apex/com.android.runtime", True), ("/linkerconfig/ld.config.txt", False),
    ("/dev/__properties__", False), ("/apex/com.android.tzdata/etc/tz/tzdata", False))


class RuntimeQualificationBackend(QualificationBackend):
    supported_methods = frozenset({"process/start", "process/read", "process/write",
                                   "process/terminate", "fs/readFile"})

    def __init__(self, backend, descriptor, python_executable, platform):
        super().__init__(backend, descriptor)
        self.python_executable = str(python_executable)
        self.platform = platform
        self._expected = canonical(process_request(self.processes.workspace, python_executable, platform))

    def _find_record(self):
        if self._record is not None:
            return self._record
        self._record = self.processes.processes.get((self._session, PROCESS_ID))
        if self._record is None:
            self._record = next((item for item in reversed(self.processes.failed)
                                 if item.session == self._session and item.key == PROCESS_ID), None)
        return self._record

    async def handle(self, call, notify):
        if self._session is not None and self._session != call.session_id:
            raise RpcError(-32000, "Qualification belongs to another session")
        if call.method == "process/start":
            if self._started or canonical(call.params) != self._expected:
                raise RpcError(-32602, "Only one exact fixed runtime qualification is admitted")
            self._started, self._session = True, call.session_id
            self._start_operation = asyncio.create_task(self.backend.handle(call, notify))
            try:
                return await self._start_operation
            except BaseException as error:
                self._start_error = type(error).__name__ + ": " + str(error)
                raise
            finally:
                self._attach(no_record=True)
        if not self._started:
            raise RpcError(-32602, "The fixed runtime qualification has not started")
        if call.method in {"process/read", "process/terminate"}:
            expected = {"processId": PROCESS_ID}
        elif call.method == "process/write":
            # The underlying production writeId owner makes exact retries
            # idempotent; a second payload cannot be substituted by this facade.
            expected = input_request()
        elif call.method == "fs/readFile":
            record = self._find_record()
            if (record is None or not record.closed or self.processes.quarantined
                    or record.failure is not None):
                raise RpcError(-32602, "Material result is unavailable before actual clean ownership")
            expected = file_request(self.processes.workspace)
        else:
            raise RpcError(-32602, "Only fixed runtime control and the material result read are admitted")
        if canonical(call.params) != canonical(expected):
            raise RpcError(-32602, "Runtime qualification control differs from its exact contract")
        return await self.backend.handle(call, notify)

    async def _collect(self, record):
        if record is not None:
            await asyncio.shield(record.finished)
        result = {"schema": "foldgpt.bionic-runtime-qualification.private.v1",
            "phase": "process-finished" if record is not None else "no-process-record",
            "success": False, "platform": sys.platform, "uid": os.getuid(), "gid": os.getgid(),
            "androidExecution": sys.platform == "android", "workspace": self.processes.workspace,
            "lifetimeScope": "native-process-only", "bootstrapPid": os.getpid(),
            "bootstrapAliveDuringReport": True, "bootstrapIdentity": bootstrap_identity(),
            "startError": self._start_error, "nativeResult": None, "supervisorReturncode": None,
            "supervisorPid": None, "supervisorWaited": False, "processClosed": False,
            "quarantined": self.processes.quarantined, "failure": None,
            "stdout": "", "stderr": "", "stdoutBase64": "", "stderrBase64": ""}
        try:
            if record is None:
                raise ValueError("No real runtime process record exists")
            streams = {name: b"".join(base64.b64decode(chunk["chunk"], validate=True)
                       for chunk, _ in record.output if chunk["stream"] == name)
                       for name in ("stdout", "stderr")}
            result.update({"nativeResult": record.native_result,
                "supervisorPid": record.process.pid if record.process is not None else None,
                "supervisorReturncode": record.process.returncode if record.process is not None else None,
                "supervisorWaited": record.process is not None and record.process.returncode is not None,
                "processClosed": record.closed, "failure": record.failure,
                "setupDiagnostic": record.setup_diagnostic.decode("utf-8", "replace")})
            for name, value in streams.items():
                result[name] = value.decode("utf-8", "replace")
                result[name + "Base64"] = base64.b64encode(value).decode("ascii")
            native = record.native_result
            if (self.processes.quarantined or record.failure is not None or not record.closed
                    or record.exit_code != 0 or native is None or native["cleanupComplete"] is not True
                    or native["started"] is not True or native["outcome"] != "exited"
                    or native["exitCode"] != 0 or native["signal"] != 0
                    or record.process is None or record.process.returncode != 0):
                raise ValueError("Real supervisor did not prove bounded clean runtime completion")
            worker = validate_report(streams["stdout"], streams["stderr"], self.processes.workspace,
                                     self.python_executable, self.platform)
            material = Path(self.processes.workspace) / "qualification-result.json"
            if material.read_bytes() != streams["stdout"]:
                raise ValueError("Material result bytes differ from actual worker stdout")
            result["worker"] = worker
            result["artifacts"] = validate_artifacts(self.processes.workspace, worker)
            result["success"] = True
        except Exception as error:
            result["error"] = type(error).__name__ + ": " + str(error)
        self._write(result)


def factory(options):
    return _factory(options, BASE)


def _factory(options, base):
    """Internal shared admission; only fixed APK-owned wrappers select a base."""
    if str(base) not in {str(BASE), "/data/local/tmp/foldgpt-bionic-runtime-qualification-v2"}:
        raise ValueError("Unknown APK-owned runtime qualification base")
    if sys.platform != "android" or os.getuid() != 2000 or os.geteuid() != 2000 or os.getgid() != 2000:
        raise ValueError("Runtime qualification requires actual Android shell identity")
    required = {"helper", "handleHelper", "processRunner", "workspace", "executables", "runtime",
                "limits", "cwdShim"}
    workspace = base / "workspace"
    if (type(options) is not dict or not required <= set(options) or set(options) - required - {"parentEnvironment"}
            or options["workspace"] != str(workspace) or canonical(options["limits"]) != canonical(LIMITS)
            or options.get("parentEnvironment", {}) != {}):
        raise ValueError("Runtime qualification requires its exact fixed deployment")
    installed = Path(sys.executable).parent
    names = {"helper": "libfoldgpt_native_files.so", "handleHelper": "libfoldgpt_native_file_handle.so",
             "processRunner": "libfoldgpt_bionic_supervisor.so"}
    python = installed / "libfoldgpt_python_cli.so"
    bash = installed / "libfoldgpt_bash.so"
    if (Path(sys.executable) != python or any(options[key] != str(installed / name) for key, name in names.items())
            or options["executables"] != {"bash": str(bash)}
            or type(options["cwdShim"]) is not dict or set(options["cwdShim"]) != {"path", "sha256"}
            or options["cwdShim"]["path"] != str(installed / "libfoldgpt_bionic_cwd.so")):
        raise ValueError("Runtime code must come from the actual attested installed native directory")
    runtime = [{"path": str(path), "execute": execute} for path, execute in
               ((bash, True), (python, True), (base / "python", False), *SYSTEM_RUNTIME)]
    if (type(options["runtime"]) is not list or
            sorted(map(canonical, options["runtime"])) != sorted(map(canonical, runtime))):
        raise ValueError("Runtime qualification requires its exact fixed runtime grants")
    # The bootstrap has verified all packaged native files. Its own actual
    # executable determines this immutable directory; neither RPC nor a marker
    # supplies it. Required Python extension libraries reside beside that ELF.
    native_options = dict(options, runtime=runtime + [{"path": str(installed), "execute": True}])
    descriptor = open_evidence(base / "evidence.json")
    try:
        return RuntimeQualificationBackend(native_factory(native_options), descriptor, python, "android")
    except BaseException:
        os.close(descriptor)
        raise
