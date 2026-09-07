"""Trusted host/UI file operations on one already owned native workspace.

This capability is separate from both model RPC admission and bootstrap reads.
Only the trusted native owner issues it. It accepts no model policy, request
authority selector, extra root or serialized capability, and has no RPC handler.
"""
from dataclasses import dataclass
import os
import stat

from tools.executor.exec_server import RpcError
from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_files import MAX_DATA, MAX_DEPTH, MAX_ENTRIES, _native_metadata
from tools.policy.managed_policy import GuestPath, PolicyError

_ISSUER = object()


@dataclass(frozen=True, slots=True, init=False)
class HostFileAuthority:
    _owner: NativeExecutorBackend
    _files: object
    _session_id: str
    _root_fd: int
    _root_identity: tuple
    _root: GuestPath

    def __init__(self, issuer, owner, session_id):
        if issuer is not _ISSUER or type(owner) is not NativeExecutorBackend:
            raise TypeError("Only the trusted native owner can issue host file authority")
        if type(session_id) is not str or not session_id or len(session_id.encode("utf-8")) > 128:
            raise ValueError("Host file authority requires its actual bounded session identity")
        owner._bind(session_id)
        if (owner.closing or owner.files.closed or owner.processes.quarantined
                or owner.files.session not in (None, session_id)):
            raise RpcError(-32603, "Native workspace is unavailable for host file authority")
        info = os.fstat(owner.files.root)
        for key, value in (("_owner", owner), ("_files", owner.files), ("_session_id", session_id),
                           ("_root_fd", owner.files.root), ("_root_identity", (info.st_dev, info.st_ino)),
                           ("_root", owner.files.mount)):
            object.__setattr__(self, key, value)

    def __reduce_ex__(self, protocol):
        raise TypeError("Host file authority cannot cross a serialization boundary")

    @property
    def workspace_root_uri(self):
        """The inclusive native root already granted by the owner, never by JSON."""
        return self._root.uri

    async def read_file(self, uri):
        """Read exact bounded bytes from an ordinary native file."""
        return await self._operate("read", uri)

    async def write_file(self, uri, data):
        """Write complete bytes, returning only after actual native synchronization.

        An error after the native mutation begins does not promise rollback.
        """
        return await self._operate("write", uri, data=data)

    async def get_metadata(self, uri, *, follow_symlinks=True):
        if type(follow_symlinks) is not bool:
            raise ValueError("Host metadata requires an explicit boolean")
        return await self._operate("metadata" if follow_symlinks else "metadata-nofollow", uri)

    async def read_directory(self, uri):
        """List real children after validation by the native snapshot helper."""
        return await self._operate("directory", uri)

    async def canonicalize(self, uri):
        """Return a canonical URI only after actual native object resolution."""
        return await self._operate("canonicalize", uri)

    async def create_directory(self, uri, *, recursive=True):
        if type(recursive) is not bool:
            raise ValueError("Host directory creation requires an explicit boolean")
        return await self._operate("mkdirs" if recursive else "mkdir", uri)

    async def _operate(self, operation, uri, *, data=b""):
        if operation not in {"read", "write", "metadata", "metadata-nofollow", "canonicalize", "directory", "mkdir", "mkdirs"}:
            raise ValueError("Unsupported host file operation")
        try:
            if type(uri) is not str:
                raise ValueError("Host path must be a canonical file URI")
            path = GuestPath.from_uri(uri)
            if uri != path.uri or not self._root.contains(path):
                raise PermissionError("Host operation is outside its owned workspace or uses an alias")
            if operation in {"read", "write"} and path == self._root:
                raise PermissionError("Host file operation requires an ordinary file below its root")
            if type(data) is not bytes or len(data) > MAX_DATA or (operation != "write" and data):
                raise ValueError("Host write requires complete bounded immutable bytes")
            if operation == "write" and path.parts[-1] == ".git":
                raise ValueError("Creating gitdir files requires the native alias resolver")
        except (ValueError, PolicyError, PermissionError) as error:
            raise RpcError(-32000, str(error)) from error

        async def owned_operation():
            files = self._files
            async with files.lock:
                if (self._owner.files is not files or self._owner.closing or files.closed
                        or files.mount != self._root or files.root != self._root_fd
                        or files.session not in (None, self._session_id)):
                    raise RpcError(-32000, "Host file authority no longer owns this filesystem session")
                if self._owner.processes.quarantined:
                    raise RpcError(-32603, "Native cleanup is unknown; host files remain quarantined")
                info = os.fstat(files.root)
                if (info.st_dev, info.st_ino) != self._root_identity:
                    raise RpcError(-32603, "Host workspace descriptor identity changed")
                files.session = self._session_id
                try:
                    # This inspects actual owners, kinds, links and bounds, not
                    # model permissions. No policy is invented for host access.
                    _, directories, count, nodes = files._inspect()
                    parts = path.parts[len(self._root.parts):]
                    relative = "/".join(parts) or "."
                    payload = data
                    entries = None
                    if operation == "directory":
                        target = nodes.get(parts)
                        if target is not None and not stat.S_ISDIR(target.st_mode):
                            raise RpcError(-32600, "Host readDirectory target is not a directory")
                        children = files._children(nodes, parts)
                        if len(children) > 50000:
                            raise ValueError("Host directory exceeds the admitted protocol bound")
                        payload = files._snapshot(nodes)
                        arguments = ["tree", str(files.root), relative, str(len(payload))]
                        if target is not None:
                            entries = [{"fileName": child[-1],
                                "isDirectory": stat.S_ISDIR(nodes[child].st_mode),
                                "isFile": stat.S_ISREG(nodes[child].st_mode)} for child in children]
                    elif operation in {"mkdir", "mkdirs"}:
                        if len(parts) > MAX_DEPTH:
                            raise ValueError("Host directory creation exceeds workspace depth limit")
                        existing = 0
                        while existing < len(parts) and parts[:existing + 1] in directories:
                            existing += 1
                        missing = len(parts) - existing
                        if count + missing > MAX_ENTRIES:
                            raise ValueError("Host directory creation exceeds workspace entry limit")
                        parent = directories[parts[:existing]]
                        arguments = [operation, str(files.root), relative, str(missing),
                            str(parent.st_dev), str(parent.st_ino)]
                    else:
                        if operation == "write":
                            if len(parts) > MAX_DEPTH + 1 or (parts not in nodes and count == MAX_ENTRIES):
                                raise ValueError("Host write exceeds workspace structural bounds")
                        arguments = [operation, str(files.root), relative, str(len(payload))]
                except (ValueError, OSError, UnicodeError) as error:
                    raise RpcError(-32000, str(error)) from error
                output = await files._native_operation(arguments, payload,
                    empty_output=operation in {"write", "mkdir", "mkdirs", "directory", "canonicalize"})
                if operation == "canonicalize":
                    return path.uri
                if operation == "directory":
                    if entries is None:
                        raise RpcError(-32603, "Native directory validation admitted a missing target")
                    return {"entries": entries}
                if operation in {"metadata", "metadata-nofollow"}:
                    return _native_metadata(output)
                return output if operation == "read" else None

        self._owner._bind(self._session_id)
        return await self._owner._run_owned_operation(owned_operation)


def create_host_file_authority(owner, *, session_id):
    """Issue host capability from the existing native owner; never an RPC option.

    The root, exclusive lease and quarantine already belong to this owner.
    Model requests remain on their mandatory-policy backend. Configuration
    retains its separate read-only BootstrapReadAuthority.
    """
    return HostFileAuthority(_ISSUER, owner, session_id)
