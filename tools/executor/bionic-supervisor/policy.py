"""Complete portable-policy decisions for the native notification channel.

No policy is converted to additive path grants. Runtime grants are separate,
explicit supervisor configuration. The native worker still enforces its fixed
syscall boundary; this module authorizes only copied, normalized operations.
"""
import errno
import os
from pathlib import Path
import stat

from tools.executor.policy_intent import prepare_policy_intent
from tools.policy.managed_policy import Access, GuestPath, parse_context


class Policy:
    def __init__(self, files, context, cwd, *, session, request):
        self.files = files
        self.intent = prepare_policy_intent(context, session_id=session,
                                            request_id=request, method="process/start")
        self.policy = parse_context(self.intent.context_json)
        self.cwd = GuestPath.from_uri(cwd)
        if self.cwd != self.policy.cwd or not files.mount.contains(self.cwd):
            raise ValueError("Process cwd must match its full policy within the executor workspace")
        self.cwd_parts = self.cwd.parts[len(files.mount.parts):]
        metadata, directories, _, _ = files._inspect(self.policy)
        if self.cwd_parts not in directories:
            raise ValueError("Process cwd must already be an admitted ordinary directory")
        files._require_read(self.policy, self.cwd_parts)
        self.root = files.root
        self.closed = False

    def require_runtime(self, runtime):
        """A required runtime can never silently override an explicit denial.

        Admission is conservative when a deny contains a more specific read
        exception: the whole immutable runtime mapping is a required ceiling.
        """
        for path, _ in runtime:
            for spelling in {str(Path(path).absolute()), str(Path(path).resolve(strict=True))}:
                root = GuestPath.from_absolute(spelling)
                if any(entry.access == Access.DENY and
                       (entry.path.contains(root) or root.contains(entry.path))
                       for entry in self.policy.resolved_entries):
                    raise PermissionError("Explicit policy denial intersects required native runtime")

    def parts(self, value):
        if not isinstance(value, str) or not value or "\0" in value:
            raise ValueError("Invalid copied pathname")
        value.encode("utf-8", errors="strict")
        if value.startswith("/"):
            raw = value.split("/")
            output = []
        else:
            raw = value.split("/")
            output = list(self.cwd.parts)
        for component in raw:
            if component in ("", "."):
                continue
            if component == "..":
                if output:
                    output.pop()
            else:
                output.append(component)
        guest = GuestPath(tuple(output))
        if not self.files.mount.contains(guest):
            raise PermissionError("Path is outside the explicitly mapped workspace")
        return guest.parts[len(self.files.mount.parts):]

    def decide(self, request):
        required = {"type", "id", "operation", "flags", "pathHex"}
        if type(request) is not dict or set(request) != required or request["type"] != "acquire":
            raise ValueError("Malformed native policy request")
        if type(request["id"]) is not int or not 0 <= request["id"] < 2**64:
            raise ValueError("Invalid notification identity")
        if type(request["flags"]) is not int or not 0 <= request["flags"] < 2**64:
            raise ValueError("Invalid operation flags")
        if request["operation"] not in ("open", "metadata", "mkdir", "list"):
            raise ValueError("Unimplemented native operation")
        try:
            raw = bytes.fromhex(request["pathHex"])
            if not raw or len(raw) >= 4096 or raw.hex() != request["pathHex"]:
                raise ValueError("Invalid copied pathname encoding")
            parts = self.parts(raw.decode("utf-8", errors="strict"))
            metadata, directories, _, nodes = self.files._inspect(self.policy)
            node = nodes.get(parts)
            parent = directories.get(parts[:-1]) if parts else directories[()]
            operation, flags = request["operation"], request["flags"]
            read = operation != "mkdir" and (operation != "open" or flags & os.O_ACCMODE != os.O_WRONLY)
            write = operation == "mkdir" or (operation == "open" and (
                flags & os.O_ACCMODE != os.O_RDONLY or flags & os.O_TRUNC or
                flags & os.O_CREAT and node is None))
            if read:
                self.files._require_read(self.policy, parts)
            if operation == "list":
                # Preserve the file RPC rule: a listing containing unreadable
                # children is refused, never silently filtered into fake data.
                self.files._listing(parts, nodes, self.policy)
            if write:
                self.files._require_write(self.policy, self.files.mount.append(parts), metadata)
                if parts and parts[-1] == ".git" and operation == "open" and node is None:
                    raise PermissionError("Creating gitdir aliases is not implemented")
            if node is not None and not (stat.S_ISREG(node.st_mode) or stat.S_ISDIR(node.st_mode)):
                raise PermissionError("Unsupported filesystem object")
            return {"id": request["id"], "error": 0, "relative": "/".join(parts) or ".",
                    "device": node.st_dev if node else 0, "inode": node.st_ino if node else 0,
                    "parentDevice": parent.st_dev if parent else 0,
                    "parentInode": parent.st_ino if parent else 0}
        except (PermissionError, UnicodeError):
            return {"id": request["id"], "error": errno.EACCES, "relative": "",
                    "device": 0, "inode": 0, "parentDevice": 0, "parentInode": 0}

    def close(self):
        # The composed files backend retains the actual root and mutation lease.
        self.closed = True
