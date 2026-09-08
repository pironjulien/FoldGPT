"""Owner-issued human process decisions without a constructed model policy.

The caller holds the existing native workspace lease for the complete process
lifetime. A real cwd outside W is permitted only for `/`; it adds no file grant.
"""
import errno
import os
import stat

from tools.executor.native_host_files import HostFileAuthority
from tools.executor.native_files import MAX_DEPTH, MAX_ENTRIES
from tools.policy.managed_policy import GuestPath
from .runtime_paths import native_name, require_outside_workspace


class HostProcessPolicy:
    def __init__(self, authority, cwd):
        if type(authority) is not HostFileAuthority:
            raise TypeError("An existing owner-issued host authority is required")
        owner, files = authority._owner, authority._files
        owner._bind(authority._session_id)
        if (owner.closing or files.closed or owner.processes.quarantined
                or not files.lock.locked() or owner.files is not files
                or files.root != authority._root_fd or files.mount != authority._root
                or files.session not in (None, authority._session_id)):
            raise PermissionError("Host process no longer owns the native session lease")
        info = os.fstat(files.root)
        if (info.st_dev, info.st_ino) != authority._root_identity:
            raise PermissionError("Host process workspace descriptor changed")
        self.files, self.root = files, files.root
        self.cwd = GuestPath.from_absolute(native_name(cwd))
        self.authority = authority
        _, directories, _, _ = files._inspect()
        if self.cwd.path != "/":
            if not files.mount.contains(self.cwd):
                raise PermissionError("Host cwd is outside the owned workspace")
            parts = self.cwd.parts[len(files.mount.parts):]
            if parts not in directories:
                raise PermissionError("Host cwd must be an existing ordinary directory")
        files.session = authority._session_id
        self.closed = False

    def require_runtime(self, runtime):
        for path, _ in runtime:
            require_outside_workspace(path, self.files.mount.path)

    def parts(self, value):
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("Invalid copied host pathname")
        value.encode("utf-8", errors="strict")
        output = [] if value.startswith("/") else list(self.cwd.parts)
        for component in value.split("/"):
            if component in ("", "."):
                continue
            if component == "..":
                if output:
                    output.pop()
            else:
                output.append(component)
        path = GuestPath(tuple(output))
        if not self.files.mount.contains(path):
            raise PermissionError("Host pathname is outside the owned workspace")
        return path.parts[len(self.files.mount.parts):]

    def decide(self, request):
        required = {"type", "id", "operation", "flags", "pathHex"}
        if (type(request) is not dict or set(request) != required or request["type"] != "acquire"
                or type(request["id"]) is not int or not 0 <= request["id"] < 2**64
                or type(request["flags"]) is not int or not 0 <= request["flags"] < 2**64
                or request["operation"] not in ("open", "metadata", "mkdir", "list")):
            raise ValueError("Malformed native host acquisition request")
        try:
            if self.closed or self.authority._owner.closing or self.authority._owner.processes.quarantined:
                raise PermissionError("Host process authority is closing or quarantined")
            raw = bytes.fromhex(request["pathHex"])
            if not raw or len(raw) >= 4096 or raw.hex() != request["pathHex"]:
                raise ValueError("Invalid copied host pathname encoding")
            parts = self.parts(raw.decode("utf-8", errors="strict"))
            _, directories, count, nodes = self.files._inspect()
            node = nodes.get(parts)
            parent = directories.get(parts[:-1]) if parts else directories[()]
            if (request["operation"] == "mkdir" or request["operation"] == "open"
                    and request["flags"] & os.O_CREAT and node is None):
                if count >= MAX_ENTRIES or len(parts) > MAX_DEPTH + (request["operation"] == "open"):
                    raise PermissionError("Host mutation exceeds the native workspace structural bounds")
            if request["operation"] == "open" and parts and parts[-1] == ".git" and node is None:
                raise PermissionError("Creating gitdir aliases requires the native alias resolver")
            if node is not None and not (stat.S_ISREG(node.st_mode) or stat.S_ISDIR(node.st_mode)):
                raise PermissionError("Unsupported host filesystem object")
            return {"id": request["id"], "error": 0, "relative": "/".join(parts) or ".",
                    "device": node.st_dev if node else 0, "inode": node.st_ino if node else 0,
                    "parentDevice": parent.st_dev if parent else 0,
                    "parentInode": parent.st_ino if parent else 0}
        except (PermissionError, UnicodeError):
            return {"id": request["id"], "error": errno.EACCES, "relative": "",
                    "device": 0, "inode": 0, "parentDevice": 0, "parentInode": 0}

    def close(self):
        # The existing native owner retains the pinned descriptor and lease.
        self.closed = True
