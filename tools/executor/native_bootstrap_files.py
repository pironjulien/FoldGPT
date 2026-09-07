"""Bootstrap-owned reads of one already pinned native executor workspace.

This is an in-process authority for trusted configuration/discovery code. It is
not a Backend, RPC method, sandbox document, or model-request option. Python
code inside the trusted bootstrap can hold it; guest/model code cannot obtain
authority by sending a missing context, JSON field or serialized object.
"""
from dataclasses import dataclass
import os

from tools.executor.exec_server import RpcError
from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_files import _native_metadata
from tools.policy.managed_policy import GuestPath, PolicyError

_ISSUER = object()


@dataclass(frozen=True, slots=True, init=False)
class BootstrapReadAuthority:
    _owner: NativeExecutorBackend
    _files: object
    _session_id: str
    _root_identity: tuple
    _root: GuestPath

    def __init__(self, issuer, owner, session_id):
        if issuer is not _ISSUER or type(owner) is not NativeExecutorBackend:
            raise TypeError("Only the trusted native bootstrap can issue this read authority")
        if type(session_id) is not str or not session_id or len(session_id.encode("utf-8")) > 128:
            raise ValueError("Bootstrap authority requires its actual bounded session identity")
        owner._bind(session_id)
        if (owner.closing or owner.files.closed or owner.processes.quarantined
                or owner.files.session not in (None, session_id)):
            raise RpcError(-32603, "Native workspace is not available for bootstrap read authority")
        info = os.fstat(owner.files.root)
        for key, value in (("_owner", owner), ("_files", owner.files), ("_session_id", session_id),
                           ("_root_identity", (info.st_dev, info.st_ino)), ("_root", owner.files.mount)):
            object.__setattr__(self, key, value)

    def __reduce_ex__(self, protocol):
        raise TypeError("Bootstrap read authority cannot cross a serialization boundary")

    @property
    def discovery_root_uri(self):
        """Inclusive ceiling for project/Git ancestor discovery, never a guess.

        Engines must stop at this explicit root. Reads outside it return an
        actual denial, even if an outside path happens not to exist.
        """
        return self._root.uri

    async def read_file(self, uri):
        """Return exact bytes after a real bounded native read."""
        return await self._read("read", uri)

    async def get_metadata(self, uri, *, follow_symlinks=True):
        if type(follow_symlinks) is not bool:
            raise ValueError("Bootstrap metadata requires an explicit boolean")
        return await self._read("metadata" if follow_symlinks else "metadata-nofollow", uri)

    async def canonicalize(self, uri):
        """Return the canonical URI only after real native object resolution."""
        return await self._read("canonicalize", uri)

    async def _read(self, operation, uri):
        # The private method is also exact; no generic mutation dispatcher is
        # hidden behind the public three-method interface.
        if operation not in {"read", "metadata", "metadata-nofollow", "canonicalize"}:
            raise ValueError("Bootstrap authority only admits read and inspection")
        try:
            if type(uri) is not str:
                raise ValueError("Bootstrap path must be a canonical file URI")
            path = GuestPath.from_uri(uri)
            if uri != path.uri or not self._root.contains(path):
                raise PermissionError("Bootstrap read is outside its pinned discovery root or uses an alias")
            if operation == "read" and path == self._root:
                raise PermissionError("Bootstrap file read requires an ordinary file below its root")
        except (ValueError, PolicyError, PermissionError) as error:
            raise RpcError(-32000, str(error)) from error

        async def owned_read():
            files = self._files
            async with files.lock:
                if (self._owner.files is not files or self._owner.closing or files.closed or files.mount != self._root
                        or files.session not in (None, self._session_id)):
                    raise RpcError(-32000, "Bootstrap read authority no longer owns this filesystem session")
                if self._owner.processes.quarantined:
                    raise RpcError(-32603, "Native cleanup is unknown; bootstrap reads remain quarantined")
                info = os.fstat(files.root)
                if (info.st_dev, info.st_ino) != self._root_identity:
                    raise RpcError(-32603, "Bootstrap workspace descriptor identity changed")
                files.session = self._session_id
                try:
                    # Structural admission has no policy argument: it inspects
                    # real owners, kinds, links and bounds using the pinned FD.
                    files._inspect()
                except (ValueError, OSError, UnicodeError) as error:
                    raise RpcError(-32000, str(error)) from error
                relative = "/".join(path.parts[len(self._root.parts):]) or "."
                output = await files._native_operation([operation, str(files.root), relative, "0"],
                    empty_output=operation == "canonicalize")
                if operation == "canonicalize":
                    return path.uri
                return output if operation == "read" else _native_metadata(output)

        self._owner._bind(self._session_id)
        return await self._owner._run_owned_operation(owned_read)


def create_bootstrap_read_authority(owner, *, session_id):
    """Trusted constructor call only; never registered with ExecServer/RPC.

    The owner already fixes the workspace FD, kernel flock, process lease and
    quarantine signal. No caller-supplied roots, policy, paths or capabilities
    can expand that scope while constructing this authority.
    """
    return BootstrapReadAuthority(_ISSUER, owner, session_id)
