"""Fixed Android diagnostic facade over the unchanged production factory.

This is an APK-selected entry point, never a model execution backend. Its only
start request is the fixed native qualification. Evidence is a private result
of the actual process record, distinct from bootstrap/JNI lifetime reporting.
"""
import asyncio
import base64
import json
import os
from pathlib import Path
import stat
import sys

from tools.executor.exec_server import RpcError
from tools.executor.native_processes import _finish
from .factory import factory as native_factory
from .qualification import evidence, process_request

BASE = Path("/data/local/tmp/foldgpt-bionic-supervisor-qualification-v2")
WORKSPACE = BASE / "workspace"
EVIDENCE = BASE / "evidence.json"
LIMITS = {"wall_ms": 3000, "cpu_seconds": 1, "uid_task_budget": 2,
          "data_bytes": 16777216, "file_bytes": 1048576,
          "output_bytes": 8192, "descriptors": 32}


def canonical(value):
    # Type-sensitive comparison: JSON false and integer 0 are not equivalent.
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def open_evidence(path):
    """Pin an existing private parent, create one new ordinary evidence file."""
    path = Path(path)
    parent = path.parent
    if not path.is_absolute() or parent.resolve(strict=True) != parent:
        raise ValueError("Diagnostic evidence parent must be canonical")
    descriptor = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        pinned, named = os.fstat(descriptor), os.stat(parent, follow_symlinks=False)
        if (not stat.S_ISDIR(pinned.st_mode) or pinned.st_uid != os.getuid() or pinned.st_mode & 0o077
                or (pinned.st_dev, pinned.st_ino) != (named.st_dev, named.st_ino)):
            raise ValueError("Diagnostic evidence parent must be owned and private")
        return os.open(path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                       0o600, dir_fd=descriptor)
    finally:
        os.close(descriptor)


def bootstrap_identity():
    """Read only this still-live host; its own report cannot attest its wait."""
    result = {"pid": os.getpid(), "uid": os.getuid(), "euid": os.geteuid(),
              "gid": os.getgid(), "egid": os.getegid()}
    try:
        with open("/proc/self/status", "rb") as source:
            raw = source.read(65537)
        if len(raw) > 65536:
            raise ValueError("Host status exceeded its bound")
        fields = {"Name", "Pid", "Tgid", "PPid", "Uid", "Gid", "Groups", "NoNewPrivs",
                  "Seccomp", "Seccomp_filters", "CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"}
        result["status"] = {key: value.strip() for row in raw.decode("ascii").splitlines()
                            if ":" in row for key, value in [row.split(":", 1)] if key in fields}
        with open("/proc/self/attr/current", "rb") as source:
            label = source.read(4097)
        if len(label) > 4096:
            raise ValueError("Host security label exceeded its bound")
        result["securityContext"] = label.decode("ascii").rstrip("\n\0")
    except Exception as error:
        result["readError"] = type(error).__name__ + ": " + str(error)
    return result


class QualificationBackend:
    supported_methods = frozenset({"process/start", "process/read", "process/terminate"})
    capabilities = frozenset()

    def __init__(self, backend, descriptor):
        self.backend = backend
        self.files, self.processes, self.mount = backend.files, backend.processes, backend.mount
        self._descriptor = descriptor
        self._expected = canonical(process_request(self.processes.workspace))
        self._started = False
        self._session = None
        self._record = None
        self._collector = None
        self._start_operation = None
        self._start_error = None
        self._written = False

    def _find_record(self):
        if self._record is not None:
            return self._record
        self._record = self.processes.processes.get((self._session, "kernel-qualification"))
        if self._record is None:
            self._record = next((record for record in reversed(self.processes.failed)
                                 if record.session == self._session and record.key == "kernel-qualification"), None)
        return self._record

    def _attach(self, *, no_record=False):
        record = self._find_record()
        if self._collector is None and (record is not None or no_record):
            self._collector = asyncio.create_task(self._collect(record))

    async def handle(self, call, notify):
        if self._session is not None and self._session != call.session_id:
            raise RpcError(-32000, "Qualification belongs to another session")
        if call.method == "process/start":
            if self._started or canonical(call.params) != self._expected:
                raise RpcError(-32602, "Only one exact fixed kernel qualification is admitted")
            # Reserve synchronously before the delegated operation can await.
            self._started, self._session = True, call.session_id
            self._start_operation = asyncio.create_task(self.backend.handle(call, notify))
            try:
                return await self._start_operation
            except BaseException as error:
                self._start_error = type(error).__name__ + ": " + str(error)
                raise
            finally:
                self._attach(no_record=True)
        if (call.method not in {"process/read", "process/terminate"} or not self._started
                or canonical(call.params) != canonical({"processId": "kernel-qualification"})):
            raise RpcError(-32602, "Only the fixed qualification read/terminate control is admitted")
        return await self.backend.handle(call, notify)

    def _write(self, result):
        if self._written:
            return
        encoded = (json.dumps(result, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
        if len(encoded) > 65536:
            raise ValueError("Fixed qualification evidence exceeded its bound")
        if os.fstat(self._descriptor).st_size:
            raise ValueError("Diagnostic evidence unexpectedly contains data")
        offset = 0
        while offset < len(encoded):
            written = os.write(self._descriptor, encoded[offset:])
            if written <= 0:
                raise OSError("Incomplete diagnostic evidence write")
            offset += written
        os.fsync(self._descriptor)
        self._written = True

    async def _collect(self, record):
        if record is not None:
            # finished can report quarantine while its owner is still alive.
            # Always preserve actual returncode/closed flags independently.
            await asyncio.shield(record.finished)
        result = {"schema": "foldgpt.bionic-kernel-qualification.private.v1",
                  "phase": "process-finished" if record is not None else "no-process-record",
                  "success": False, "platform": sys.platform, "uid": os.getuid(), "gid": os.getgid(),
                  "androidExecution": sys.platform == "android", "workspace": self.processes.workspace,
                  "lifetimeScope": "native-process-only", "bootstrapPid": os.getpid(),
                  "bootstrapAliveDuringReport": True, "bootstrapIdentity": bootstrap_identity(),
                  "startError": self._start_error, "nativeResult": None, "supervisorReturncode": None,
                  "supervisorPid": None,
                  "supervisorWaited": False, "processClosed": False,
                  "quarantined": self.processes.quarantined, "failure": None,
                  "stdout": "", "stderr": "", "stdoutBase64": "", "stderrBase64": ""}
        try:
            if record is None:
                raise ValueError("No real qualification process record exists")
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
            if self.processes.quarantined or record.failure is not None:
                raise ValueError("Actual qualification retained quarantine or a process failure")
            result["proofs"] = evidence(streams["stdout"], streams["stderr"], record)
            # Only inspect the two fixed sentinels after true clean completion.
            # Unknown owner/lease states never lead to a workspace traversal.
            workspace = Path(self.processes.workspace)
            if ((workspace / "private/secret").read_bytes() != b"probe-private-unchanged\n"
                    or (workspace / ".git/config").exists()):
                raise ValueError("A protected qualification sentinel changed")
            result["success"] = True
        except Exception as error:
            result["error"] = type(error).__name__ + ": " + str(error)
        self._write(result)

    async def close(self, session_id):
        # Snapshot a record before the real close removes completed entries.
        self._attach()
        native_error = None
        try:
            await self.backend.close(session_id)
        except BaseException as error:
            native_error = error
        try:
            if self._start_operation is not None:
                await _finish(asyncio.gather(self._start_operation, return_exceptions=True))
            self._attach(no_record=True)
            await _finish(self._collector)
        finally:
            if self._descriptor >= 0:
                os.close(self._descriptor)
                self._descriptor = -1
        if native_error is not None:
            raise native_error


def factory(options):
    """Fixed Android APK entry point; no RPC or option chooses the evidence path."""
    return _factory(options, BASE)


def _factory(options, base):
    """The installed diagnostic module supplies its fixed base, never the RPC."""
    workspace = base / "workspace"
    if sys.platform != "android" or os.getuid() != 2000 or os.geteuid() != 2000 or os.getgid() != 2000:
        raise ValueError("Kernel qualification factory requires actual Android shell identity")
    required = {"helper", "handleHelper", "processRunner", "workspace", "executables", "runtime", "limits"}
    if (type(options) is not dict or not required <= set(options) or set(options) - required - {"parentEnvironment"}
            or options["workspace"] != str(workspace) or canonical(options["limits"]) != canonical(LIMITS)
            or options.get("parentEnvironment", {}) != {} or set(options["executables"]) != {"kernel-qualification"}):
        raise ValueError("Kernel qualification requires its exact fixed deployment")
    installed = Path(sys.executable).parent
    names = {"helper": "libfoldgpt_native_files.so", "handleHelper": "libfoldgpt_native_file_handle.so",
             "processRunner": "libfoldgpt_bionic_supervisor.so"}
    if (any(options[key] != str(installed / name) for key, name in names.items())
            or options["executables"]["kernel-qualification"] != str(installed / "libfoldgpt_qualification_worker.so")):
        raise ValueError("Qualification code must come from its actual installed native directory")
    runtime = [{"path": str(installed / "libfoldgpt_qualification_worker.so"), "execute": True}]
    runtime.extend({"path": path, "execute": execute} for path, execute in (
        ("/system/lib64", True), ("/system/bin/linker64", True), ("/apex/com.android.runtime", True),
        ("/linkerconfig/ld.config.txt", False), ("/dev/__properties__", False),
        ("/apex/com.android.tzdata/etc/tz/tzdata", False)))
    if (type(options["runtime"]) is not list or
            sorted(map(canonical, options["runtime"])) != sorted(map(canonical, runtime))):
        raise ValueError("Qualification requires its exact fixed Bionic runtime grants")
    descriptor = open_evidence(base / "evidence.json")
    try:
        return QualificationBackend(native_factory(options), descriptor)
    except BaseException:
        os.close(descriptor)
        raise
