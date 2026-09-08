"""Bootstrap-selected model profiles, with immutable ownership of live handles.

The authenticated controller's absent process sandbox is the upstream direct
launch contract. It is not inferred from prompt text or a retry after a refusal.
Explicit Disabled is a direct *filesystem* context; process sandbox objects keep
their upstream required-sandbox meaning and always enter the managed backend.
This module does not issue or reuse the separate human HostFileAuthority.
"""
from tools.executor.exec_server import RpcError, validate_operation
from tools.executor.native_processes import METHODS


class NativeModelProfiles:
    def __init__(self, owner, direct_processes, direct_files, pty_processes=None):
        if owner.session is not None or owner.closing or owner.files.closed:
            raise ValueError("Model profiles must be selected before session acquisition")
        if (direct_processes.files_backend is not owner.files
                or direct_processes.lease is not owner.files.lock
                or direct_files.lock is not owner.files.lock
                or direct_processes.quarantine_owner is not owner.processes):
            raise ValueError("Model profiles must share the actual native owner and lease")
        if (direct_processes.processes or direct_files.handles or direct_files.session is not None
                or direct_files.closed or direct_processes.quarantined
                or owner.processes.processes or owner.files.handles or owner.files.lock.locked()):
            raise ValueError("A new model profile cannot import live handles")
        if pty_processes is not None:
            if (pty_processes.files_backend is not owner.files
                    or pty_processes.lease is not owner.files.lock
                    or pty_processes.quarantine_owner is not owner.processes):
                raise ValueError("PTY model profile must share the actual native owner and lease")
            if (pty_processes.processes or pty_processes.quarantined
                    or pty_processes.quarantine_event.is_set() or pty_processes.closing_sessions):
                raise ValueError("A new PTY model profile cannot import live handles or closing state")
        process_backends = (owner.processes, direct_processes) + ((pty_processes,) if pty_processes is not None else ())
        if (len({id(backend) for backend in process_backends}) != len(process_backends)
                or len({id(backend.processes) for backend in process_backends}) != len(process_backends)
                or any(backend is human for backend in process_backends for human in owner._host_process_owners)):
            raise ValueError("Model process backends require separate owners and registries")
        self.owner = owner
        self.direct_processes = direct_processes
        self.direct_files = direct_files
        self.pty_processes = pty_processes
        self.process_backends = process_backends
        self.pending_processes = set()
        self.pending_files = set()

    @staticmethod
    def _direct_file_request(params):
        context = params.get("sandbox")
        if context is None:
            return True
        # Selection is not admission: the direct backend validates the complete
        # Disabled object and its platform/path preferences before any operation.
        return (type(context) is dict and type(context.get("permissions")) is dict
                and context["permissions"].get("type") == "disabled")

    def _process_backend(self, session, identifier):
        key = (session, identifier)
        matches = [backend for backend in self.process_backends
                   if key in backend.processes]
        if len(matches) > 1:
            raise RpcError(-32603, "Native process handle has ambiguous ownership")
        return matches[0] if matches else None

    def _file_backend(self, identifier):
        matches = [backend for backend in (self.owner.files, self.direct_files)
                   if identifier in backend.handles]
        if len(matches) > 1:
            raise RpcError(-32603, "Native file handle has ambiguous ownership")
        return matches[0] if matches else None

    async def handle(self, call, notify):
        # Validate before selecting a profile. An unknown field or malformed
        # outer request is never treated as an absent sandbox or a lifecycle call.
        params = call.params
        validate_operation(call.method, params)
        if call.method in METHODS:
            key = (call.session_id, params["processId"])
            if call.method != "process/start":
                backend = self._process_backend(*key)
                if backend is None:
                    if call.method == "process/signal":
                        return {}
                    if call.method == "process/terminate":
                        return {"running": False}
                    raise RpcError(-32600, "Unknown native process handle")
                return await backend.handle(call, notify)
            if (key in self.pending_processes
                    or any(key in backend.processes for backend in self.process_backends)):
                raise RpcError(-32600, "Process id already exists in this session")
            occupied = self.pending_processes.union(*(backend.processes for backend in self.process_backends))
            if len(occupied) >= 128:
                raise RpcError(-32000, "Native process registry capacity exhausted")
            backend = self.direct_processes if params.get("sandbox") is None else self.owner.processes
            if params.get("sandbox") is None and params["tty"] and self.pty_processes is not None:
                backend = self.pty_processes
            self.pending_processes.add(key)
            try:
                return await backend.handle(call, notify)
            finally:
                self.pending_processes.remove(key)

        if call.method in {"fs/readBlock", "fs/close"}:
            identifier = params["handleId"]
            if len(identifier.encode("utf-8")) > 32:
                raise RpcError(-32600, "File read handle ID exceeds 32 bytes")
            if identifier in self.pending_files:
                raise RpcError(-32600, "File handle acquisition is still pending")
            backend = self._file_backend(identifier)
            if backend is None:
                if call.method == "fs/close":
                    return {}  # Upstream close is idempotent for an unknown ID.
                raise RpcError(-32004, "Unknown file read handle")
            return await backend.handle(call, notify)

        backend = self.direct_files if self._direct_file_request(params) else self.owner.files
        if call.method != "fs/open":
            return await backend.handle(call, notify)
        identifier = params["handleId"]
        if identifier in self.pending_files or self._file_backend(identifier) is not None:
            raise RpcError(-32600, "File read handle already exists")
        occupied = self.pending_files | set(self.owner.files.handles) | set(self.direct_files.handles)
        if len(occupied) >= 128:
            raise RpcError(-32600, "At most 128 file reads may be open per connection")
        self.pending_files.add(identifier)
        try:
            return await backend.handle(call, notify)
        finally:
            self.pending_files.remove(identifier)
