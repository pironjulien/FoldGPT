"""Policy-bearing read/write RPCs using a real native FD-based file helper.

This initial backend admits one supervisor-owned ordinary workspace and no
guest processes. It is not an installed production executor. Native Android
execution, symlink/gitdir handling and process isolation remain integration work.
"""
import asyncio
import base64
import binascii
import errno
import fcntl
import json
import os
from pathlib import Path
import stat

from tools.executor.exec_server import RpcError
from tools.executor.policy_intent import prepare_policy_intent
from tools.policy.managed_policy import GuestPath, PolicyError, parse_context

MAX_DATA = 16 * 1024 * 1024


def _native_failure(diagnostic):
    """Translate only a validated native error record into official RPC codes.

    In particular, Codex's RemoteFileSystem recognizes -32004 as NotFound.
    Policy rejection never passes through this mapper and cannot become a
    misleading absence. Malformed diagnostics remain internal backend failures.
    """
    stages = {"invocation", "root-fd", "length", "root-ownership", "allocation",
              "input", "input-length", "open", "file-kind", "write",
              "directory-sync", "read", "read-bound", "output", "close"}

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate native error field")
            result[key] = value
        return result

    try:
        if type(diagnostic) is not bytes or len(diagnostic) > 1024:
            raise ValueError("Invalid native diagnostic length")
        value = json.loads(diagnostic.decode("ascii"), object_pairs_hook=unique)
        if (type(value) is not dict or set(value) != {"stage", "errno"}
                or type(value["stage"]) is not str or value["stage"] not in stages
                or type(value["errno"]) is not int or not 1 <= value["errno"] <= 4095):
            raise ValueError("Invalid native error record")
    except (ValueError, UnicodeError, TypeError, RecursionError):
        return RpcError(-32603, "Native filesystem error violates its contract")
    number = value["errno"]
    if value["stage"] == "open" and number == errno.ENOENT:
        return RpcError(-32004, "Requested file or its parent does not exist")
    if number in {errno.EACCES, errno.EPERM, errno.EINVAL}:
        return RpcError(-32600, "Native filesystem request was refused", value)
    return RpcError(-32603, "Native filesystem operation failed", value)


class NativeFilesBackend:
    supported_methods = frozenset({"fs/readFile", "fs/writeFile"})
    capabilities = frozenset()

    def __init__(self, helper, workspace, *, guest_workspace="/workspace"):
        self.helper = str(Path(helper).resolve(strict=True))
        self.mount = GuestPath.from_absolute(guest_workspace)
        if not self.mount.parts:
            raise ValueError("A dedicated guest workspace is required")
        path = Path(workspace).absolute()
        if path != path.resolve(strict=True):
            raise ValueError("Workspace aliases are unsupported")
        self.root = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
        try:
            info = os.fstat(self.root)
            if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
                raise ValueError("Workspace must be owned and private")
            # Cooperating executor sessions cannot modify the same workspace
            # concurrently. This is not exclusion against a hostile host/admin.
            fcntl.flock(self.root, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(self.root)
            raise
        self.lock = asyncio.Lock()
        self.session = None
        self.process = None
        self.closed = False

    def _inspect(self, policy):
        """Refuse aliases and unsupported worktrees before an operation.

        The workspace is owned exclusively by this backend. A concurrent
        unconfined native writer is outside this admission contract. Native
        openat2 and pinned-file checks still protect the actual opened path.
        """
        count = 0
        metadata = []
        pending = [(os.dup(self.root), (), 0)]
        try:
            while pending:
                directory, parts, depth = pending.pop()
                try:
                    if depth > 64:
                        raise ValueError("Workspace depth exceeds admission limit")
                    for name in os.listdir(directory):
                        count += 1
                        if count > 100000:
                            raise ValueError("Workspace exceeds admission limit")
                        fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                        try:
                            info = os.fstat(fd)
                            if (info.st_uid != os.getuid() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                                raise ValueError("Workspace contains an unsupported alias, owner or file kind")
                            guest = self.mount.append(parts + (name,))
                            if name == ".git" and stat.S_ISREG(info.st_mode):
                                raise ValueError("gitdir worktrees require the native alias resolver")
                            if name in (".git", ".agents") and stat.S_ISDIR(info.st_mode):
                                metadata.append(guest)
                            if stat.S_ISDIR(info.st_mode):
                                # Open the already inspected directory inode.
                                child = os.open(f"/proc/self/fd/{fd}", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
                                pending.append((child, parts + (name,), depth + 1))
                        finally:
                            os.close(fd)
                finally:
                    os.close(directory)
        finally:
            for fd, _, _ in pending:
                os.close(fd)
        return metadata

    async def handle(self, call, notify):
        if call.method not in self.supported_methods:
            raise RpcError(-32601, "Native filesystem method is not implemented")
        async with self.lock:
            if self.closed:
                raise RpcError(-32000, "Filesystem session is closed")
            if self.session is None:
                self.session = call.session_id
            elif self.session != call.session_id:
                raise RpcError(-32000, "Workspace belongs to another executor session")
            params = call.params
            writing = call.method == "fs/writeFile"
            try:
                allowed = {"path", "sandbox", "followSymlinks"} | ({"dataBase64"} if writing else set())
                if type(params) is not dict or set(params) - allowed:
                    raise ValueError("Unsupported filesystem request field")
                if params.get("followSymlinks") is not None and type(params["followSymlinks"]) is not bool:
                    raise ValueError("Invalid followSymlinks option")
                # Retain the complete context unchanged, not a writable-root
                # approximation. Unsupported semantics refuse the entire RPC.
                intent = prepare_policy_intent(params.get("sandbox"), session_id=call.session_id,
                    request_id=str(call.request_id), method=call.method)
                policy = parse_context(intent.to_document()["context"])
                path = GuestPath.from_uri(params["path"])
                if not self.mount.contains(path) or path == self.mount:
                    raise ValueError("Path is outside the admitted workspace mapping")
                decision = policy.decide_uri(path.uri)
                if not (decision.can_write if writing else decision.can_read):
                    raise PermissionError("The supplied filesystem policy denies this operation")
                metadata = self._inspect(policy)
                if writing:
                    # A successful write must not introduce a file kind that
                    # invalidates every subsequent workspace operation. This
                    # admission limit also applies to explicit policy grants.
                    if path.parts[-1] == ".git":
                        raise ValueError("Creating gitdir files requires the native alias resolver")
                    for protected in metadata:
                        if protected.contains(path) and not any(
                                entry.access.value == "write" and protected.contains(entry.path) and entry.path.contains(path)
                                for entry in policy.resolved_entries):
                            raise PermissionError("Existing project metadata is protected")
                    encoded = params["dataBase64"]
                    if not isinstance(encoded, str) or len(encoded) > ((MAX_DATA + 2) // 3) * 4:
                        raise ValueError("Write exceeds the admitted data bound")
                    data = base64.b64decode(encoded, validate=True)
                    if len(data) > MAX_DATA:
                        raise ValueError("Write exceeds the admitted data bound")
                else:
                    data = b""
                relative = "/".join(path.parts[len(self.mount.parts):])
            except (PolicyError, ValueError, KeyError, PermissionError, OSError, binascii.Error) as error:
                raise RpcError(-32000, str(error)) from error
            self.process = await asyncio.create_subprocess_exec(
                self.helper, "write" if writing else "read", str(self.root), relative, str(len(data)),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                close_fds=True, pass_fds=(self.root,), env={})
            communicate = asyncio.create_task(self.process.communicate(data))
            try:
                output, diagnostic = await asyncio.wait_for(asyncio.shield(communicate), 30)
                if self.process.returncode != 0:
                    raise _native_failure(diagnostic)
                if diagnostic or (writing and output) or len(output) > MAX_DATA:
                    raise RpcError(-32000, "Native filesystem response violates its contract")
                return {} if writing else {"dataBase64": base64.b64encode(output).decode("ascii")}
            finally:
                # A transport cancellation is not a rollback of a write that
                # has begun. Await termination before releasing root ownership.
                if self.process.returncode is None:
                    self.process.kill()
                await communicate
                self.process = None

    async def close(self, session_id):
        async with self.lock:
            if not self.closed:
                if self.session is not None and self.session != session_id:
                    raise RpcError(-32000, "Cannot close a different filesystem session")
                self.closed = True
                os.close(self.root)
