"""Compose the real native file, stream and process backends for one session.

The constructor owns runtime mappings and limits. A request cannot choose native
programs or replace a process's complete policy. This composition does not select
a Desktop environment or expand the process profile's admitted operations.
"""
import asyncio
import os

from tools.executor.exec_server import RpcError
from tools.executor.native_file_streams import NativeFileStreamsBackend
from tools.executor.native_processes import METHODS, NativeProcessesBackend, _finish


class NativeExecutorBackend:
    def __init__(self, helper, workspace, *, handle_helper, process_runner,
                 executables=None, guest_workspace="/workspace", limits=None,
                 parent_environment=None, process_factory=None):
        if process_factory is not None and (not callable(process_factory) or executables is not None):
            raise ValueError("An alternate process factory must be callable and own its executable mapping")
        self.files = NativeFileStreamsBackend(helper, workspace,
            handle_helper=handle_helper, guest_workspace=guest_workspace)
        try:
            factory = NativeProcessesBackend if process_factory is None else process_factory
            options = {"executables": executables} if process_factory is None else {}
            self.processes = factory(process_runner, workspace, **options,
                guest_workspace=guest_workspace,
                limits=limits, files_backend=self.files, parent_environment=parent_environment)
        except BaseException:
            # No operation or streaming handle exists during construction.
            os.close(self.files.root)
            self.files.closed = True
            raise
        self.supported_methods = frozenset(self.files.supported_methods | self.processes.supported_methods)
        self.capabilities = frozenset(self.files.capabilities | self.processes.capabilities)
        self.mount = self.files.mount
        self.session = None
        self.closing = False
        self._close_task = None
        # Optional bootstrap-owned human processes share this exact filesystem.
        # They never enter the model method dispatch above.
        self._host_process_owners = []
        # Optional bootstrap selection. No request field may add this profile,
        # and the qualified managed-only constructor keeps its current behavior.
        self._model_profiles = None

    def install_ordinary_uid_profile(self, processes, files, *, pty_processes=None):
        """Select direct model backends before binding the authenticated channel."""
        if self._model_profiles is not None:
            raise ValueError("Native model profiles are already selected")
        from tools.executor.native_model_profiles import NativeModelProfiles
        profiles = NativeModelProfiles(self, processes, files, pty_processes)
        self._model_profiles = profiles
        self.supported_methods = frozenset(self.supported_methods | processes.supported_methods | files.supported_methods)
        self.capabilities = frozenset(self.capabilities | processes.capabilities | files.capabilities)
        if pty_processes is not None:
            self.supported_methods = frozenset(self.supported_methods | pty_processes.supported_methods)
            self.capabilities = frozenset(self.capabilities | pty_processes.capabilities)

    def _bind(self, session):
        if self.session is None:
            self.session = session
        elif self.session != session:
            raise RpcError(-32000, "Native executor belongs to a different session")

    async def handle(self, call, notify):
        self._bind(call.session_id)
        if self.closing:
            raise RpcError(-32600, "Native executor session is closing")
        if call.method in METHODS and call.method != "process/start":
            if self._model_profiles is not None:
                return await self._model_profiles.handle(call, notify)
            return await self.processes.handle(call, notify)
        if call.method != "process/start" and call.method not in self.files.supported_methods:
            raise RpcError(-32601, "Unsupported native executor method")
        backend = self._model_profiles or (self.processes if call.method == "process/start" else self.files)
        return await self._run_owned_operation(lambda: backend.handle(call, notify))

    async def _run_owned_operation(self, operation_factory):
        """Common lifecycle gate for managed RPC and bootstrap-owned reads."""
        if self.closing:
            raise RpcError(-32600, "Native executor session is closing")
        if self.processes.quarantined or self.processes.quarantine_event.is_set():
            raise RpcError(-32603, "Native process cleanup is unknown; filesystem access is quarantined")
        operation = asyncio.create_task(operation_factory())
        quarantined = asyncio.create_task(self.processes.quarantine_event.wait())
        try:
            await asyncio.wait((operation, quarantined), return_when=asyncio.FIRST_COMPLETED)
            # The shared lock excludes file operations for the entire process
            # lifetime. A completed operation here preceded that ownership.
            if operation.done():
                return operation.result()
            operation.cancel()
            await asyncio.gather(operation, return_exceptions=True)
            raise RpcError(-32603, "Native process cleanup is unknown; pending filesystem access was refused")
        finally:
            if not operation.done():
                operation.cancel()
            quarantined.cancel()
            await _finish(asyncio.gather(operation, quarantined, return_exceptions=True))

    async def close(self, session_id):
        self._bind(session_id)
        self.closing = True
        if self._close_task is None:
            self._close_task = asyncio.create_task(self._close(session_id))
        # Preserve the same failure on every close. The process backend may
        # remove completed records while refusing unknown cleanup; retrying its
        # close and then waiting on the deliberately retained lock would hang.
        await _finish(self._close_task)

    async def _close(self, session_id):
        # Unknown process cleanup deliberately leaves the pinned root/lease
        # owned. Closing its file backend would release the kernel flock and
        # allow a new connection to race surviving workers.
        other_processes = list(self._host_process_owners)
        if self._model_profiles is not None:
            other_processes.extend(self._model_profiles.process_backends[1:])
        if other_processes:
            results = await asyncio.gather(self.processes.close(session_id),
                *(owner.close(session_id) for owner in other_processes), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
        else:
            await self.processes.close(session_id)
        if self.processes.quarantined or self.processes.quarantine_event.is_set():
            raise RpcError(-32603, "Native executor cannot release an unknown process workspace")
        if self._model_profiles is not None:
            await self._model_profiles.direct_files.close(session_id)
        await self.files.close(session_id)
