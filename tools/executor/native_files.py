"""Policy-bearing file/directory RPCs using a real native FD-based helper.

This backend admits one supervisor-owned ordinary workspace and no guest
processes. It is not an installed production executor. Symlink/gitdir handling
and process isolation remain integration work. Walk/list/remove/copy follow the
reviewed official tag rust-v0.153.4 (042fb41b7c813ac7999105e886b2b7aa715b5081),
exec-server-protocol/src/protocol.rs, file-system/src/lib.rs and
exec-server/src/{local_file_system,server/file_system_handler}.rs.

Bulk operations retain the exclusive workspace admission. A directory read
returns its real immediate names and kinds, including denied children; it grants
no access to those children. Recursive walk/copy still check each traversed
object. Listings never silently omit policy-denied files. Copy refuses overlapping
trees and bounds aggregate file data to 16 MiB; no truncation of a copy plan is
treated as success. A transport/OS failure during an admitted mutation is not
a transactional rollback. Only a fully successful native operation returns {}.
"""
import asyncio
import base64
import binascii
from collections import deque
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
MAX_ENTRIES = 100000
MAX_DEPTH = 64


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate native response field")
        result[key] = value
    return result


def _native_metadata(output):
    """Require exactly the reviewed metadata shape from the native statx call."""
    try:
        if type(output) is not bytes or len(output) > 1024:
            raise ValueError("Invalid native metadata length")
        value = json.loads(output.decode("ascii"), object_pairs_hook=_unique_object)
        if (type(value) is not dict or set(value) != {
                "isDirectory", "isFile", "isSymlink", "size", "createdAtMs", "modifiedAtMs"}
                or any(type(value[key]) is not bool for key in ("isDirectory", "isFile", "isSymlink"))
                or value["isDirectory"] == value["isFile"] or value["isSymlink"]
                or type(value["size"]) is not int or not 0 <= value["size"] < 2**64
                or any(type(value[key]) is not int or not -(2**63) <= value[key] < 2**63
                    for key in ("createdAtMs", "modifiedAtMs"))):
            raise ValueError("Invalid native metadata record")
    except (ValueError, UnicodeError, TypeError, RecursionError) as error:
        raise RpcError(-32603, "Native filesystem metadata violates its contract") from error
    return value


def _native_failure(diagnostic):
    """Translate only a validated native error record into official RPC codes.

    In particular, Codex's RemoteFileSystem recognizes -32004 as NotFound.
    Policy rejection never passes through this mapper and cannot become a
    misleading absence. Malformed diagnostics remain internal backend failures.
    """
    stages = {"invocation", "root-fd", "length", "root-ownership", "allocation",
              "input", "input-length", "open", "file-kind", "write",
              "directory-sync", "directory-state", "mkdir", "metadata", "read", "read-bound", "output", "close",
              "tree-plan", "tree-state", "remove", "copy"}

    try:
        if type(diagnostic) is not bytes or len(diagnostic) > 1024:
            raise ValueError("Invalid native diagnostic length")
        value = json.loads(diagnostic.decode("ascii"), object_pairs_hook=_unique_object)
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
    supported_methods = frozenset({"fs/readFile", "fs/writeFile", "fs/createDirectory",
                                   "fs/getMetadata", "fs/canonicalize", "fs/readDirectory",
                                   "fs/walk", "fs/remove", "fs/copy"})
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

    def _inspect(self, policy=None):
        """Refuse aliases and unsupported worktrees before an operation.

        The workspace is owned exclusively by this backend. A concurrent
        unconfined native writer is outside this admission contract. Native
        openat2 and pinned-file checks still protect the actual opened path.
        """
        count = 0
        metadata = []
        directories = {(): os.fstat(self.root)}
        nodes = dict(directories)
        pending = [(os.dup(self.root), (), 0)]
        try:
            while pending:
                directory, parts, depth = pending.pop()
                try:
                    if depth > MAX_DEPTH:
                        raise ValueError("Workspace depth exceeds admission limit")
                    for name in os.listdir(directory):
                        name.encode("utf-8", errors="strict")
                        count += 1
                        if count > MAX_ENTRIES:
                            raise ValueError("Workspace exceeds admission limit")
                        fd = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
                        try:
                            info = os.fstat(fd)
                            if (info.st_uid != os.getuid() or not (stat.S_ISREG(info.st_mode) or stat.S_ISDIR(info.st_mode))
                                    or (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
                                raise ValueError("Workspace contains an unsupported alias, owner or file kind")
                            guest = self.mount.append(parts + (name,))
                            nodes[parts + (name,)] = info
                            if name == ".git" and stat.S_ISREG(info.st_mode):
                                raise ValueError("gitdir worktrees require the native alias resolver")
                            if name in (".git", ".agents") and stat.S_ISDIR(info.st_mode):
                                metadata.append(guest)
                            if stat.S_ISDIR(info.st_mode):
                                directories[parts + (name,)] = info
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
        return metadata, directories, count, nodes

    @staticmethod
    def _snapshot(nodes):
        """Exact native lstat snapshot; NUL framing permits tabs/newlines safely.

        The helper enumerates the whole pinned tree and compares every actual
        inode, kind, mode, size, mtime and ctime before executing a planned RPC.
        No policy is reduced to this snapshot: authorization remains per request.
        """
        rows = []
        for parts, info in sorted(nodes.items(), key=lambda item: ("/".join(item[0]) or ".").encode("utf-8")):
            fields = ["/".join(parts) or ".", info.st_dev, info.st_ino, info.st_mode, info.st_size,
                      info.st_mtime_ns // 1000000000, info.st_mtime_ns % 1000000000,
                      info.st_ctime_ns // 1000000000, info.st_ctime_ns % 1000000000]
            rows.append(b"\0".join(str(value).encode("utf-8") for value in fields) + b"\0")
        data = b"".join(rows)
        if not data or len(data) > MAX_DATA:
            raise ValueError("Native operation snapshot exceeds admission bound")
        return data

    def _guest(self, parts):
        return self.mount.append(parts)

    def _require_read(self, policy, parts):
        if not policy.decide_uri(self._guest(parts).uri).can_read:
            raise PermissionError("The supplied filesystem policy denies this operation")

    @staticmethod
    def _children(nodes, parts):
        return sorted((child for child in nodes if len(child) == len(parts) + 1 and child[:-1] == parts),
                      key=lambda child: child[-1].encode("utf-8"))

    def _listing(self, parts, nodes, policy):
        self._require_read(policy, parts)
        if parts not in nodes:
            return None  # Native lookup must supply the real NotFound result.
        if not stat.S_ISDIR(nodes[parts].st_mode):
            raise RpcError(-32600, "Requested readDirectory path is not a directory")
        entries = []
        for child in self._children(nodes, parts):
            if len(entries) == 50000:
                raise ValueError("Directory listing exceeds the admitted protocol response bound")
            # Directory read permission covers its immediate names and kinds,
            # as native readdir does. Reading a child or descending into it is
            # a separate operation with its own complete policy check.
            entries.append({"fileName": child[-1], "isDirectory": stat.S_ISDIR(nodes[child].st_mode),
                            "isFile": stat.S_ISREG(nodes[child].st_mode)})
        return {"entries": entries}

    def _walk(self, parts, nodes, policy, options):
        keys = {"maxDepth", "maxDirectories", "maxEntries", "followDirectorySymlinks", "pruneHiddenDirectories"}
        if type(options) is not dict or set(options) - keys or keys - {"pruneHiddenDirectories"} - set(options):
            raise ValueError("Walk requires all exact reviewed options")
        options = {"pruneHiddenDirectories": False, **options}
        for key in ("maxDepth", "maxDirectories", "maxEntries"):
            if type(options[key]) is not int or options[key] < (0 if key == "maxDepth" else 1):
                raise ValueError("Invalid filesystem walk bound")
        for key in ("followDirectorySymlinks", "pruneHiddenDirectories"):
            if type(options[key]) is not bool:
                raise ValueError("Invalid filesystem walk option")
        if options["maxDepth"] > 64 or options["maxDirectories"] > 10000 or options["maxEntries"] > 50000:
            raise ValueError("Walk limits exceed the admitted workspace bounds")
        outcome = {"entries": [], "errors": [], "truncated": False}
        if parts not in nodes:
            return None
        if not stat.S_ISDIR(nodes[parts].st_mode):
            return outcome
        children = {}
        for child in nodes:
            if child:
                children.setdefault(child[:-1], []).append(child)
        for names in children.values():
            names.sort(key=lambda child: child[-1].encode("utf-8"))
        queue = deque([(parts, 0)])
        directory_count, entry_count, response_bytes = 1, 0, 0
        while queue:
            directory, depth = queue.popleft()
            self._require_read(policy, directory)
            for child in children.get(directory, ()):
                if entry_count == options["maxEntries"]:
                    outcome["truncated"] = True
                    return outcome
                entry_count += 1
                self._require_read(policy, child)
                is_directory = stat.S_ISDIR(nodes[child].st_mode)
                uri = self._guest(child).uri
                response_bytes += len(uri.encode("utf-8")) + 64
                if response_bytes > 4 * 1024 * 1024:
                    outcome["truncated"] = True
                    return outcome
                outcome["entries"].append({"path": uri, "kind": "directory" if is_directory else "file"})
                if is_directory and depth < options["maxDepth"]:
                    if options["pruneHiddenDirectories"] and child[-1].startswith("."):
                        continue
                    if directory_count == options["maxDirectories"]:
                        outcome["truncated"] = True
                    else:
                        directory_count += 1
                        queue.append((child, depth + 1))
        return outcome

    def _remove_plan(self, parts, nodes, policy, metadata, recursive):
        for child in nodes:
            if child[:len(parts)] == parts:
                if child != parts and not recursive:
                    raise RpcError(-32600, "Requested directory is not empty")
                self._require_write(policy, self._guest(child), metadata)

    def _copy_plan(self, source, destination, nodes, policy, metadata, recursive):
        if source[:len(destination)] == destination or destination[:len(source)] == source:
            raise ValueError("Copy paths must not overlap in the admitted workspace")
        if source not in nodes:
            return
        source_directory = stat.S_ISDIR(nodes[source].st_mode)
        if source_directory and not recursive:
            raise ValueError("Copying a directory requires recursive true")
        selected = [(parts, info) for parts, info in nodes.items() if parts[:len(source)] == source]
        prospective_metadata = list(metadata)
        for parts, info in selected:
            target = destination + parts[len(source):]
            if stat.S_ISDIR(info.st_mode) and target[-1] in (".git", ".agents"):
                prospective_metadata.append(self._guest(target))
        created, total = set(), 0
        for parts, info in selected:
            self._require_read(policy, parts)
            target = destination + parts[len(source):]
            if len(target) > MAX_DEPTH + (1 if stat.S_ISREG(info.st_mode) else 0):
                raise ValueError("Copy exceeds the admitted workspace depth")
            self._require_write(policy, self._guest(target), prospective_metadata)
            existing = nodes.get(target)
            if existing and stat.S_IFMT(existing.st_mode) != stat.S_IFMT(info.st_mode):
                raise ValueError("Copy destination kind conflicts with the source")
            if stat.S_ISREG(info.st_mode):
                if target[-1] == ".git":
                    raise ValueError("Creating gitdir files requires the native alias resolver")
                total += info.st_size
                if total > MAX_DATA or info.st_mode & 0o7000:
                    raise ValueError("Copy exceeds data bound or has unsupported special mode bits")
            for depth in range(1, len(target)):
                parent = target[:depth]
                if parent in nodes:
                    if not stat.S_ISDIR(nodes[parent].st_mode):
                        raise ValueError("Copy destination ancestor is not a directory")
                elif source_directory:
                    self._require_write(policy, self._guest(parent), prospective_metadata)
                    created.add(parent)
                else:
                    raise RpcError(-32004, "Copy destination parent does not exist")
            if target not in nodes:
                created.add(target)
        if len(nodes) - 1 + len(created) > MAX_ENTRIES:
            raise ValueError("Copy exceeds the workspace entry limit")

    @staticmethod
    def _require_write(policy, path, metadata):
        if not policy.decide_uri(path.uri).can_write:
            raise PermissionError("The supplied filesystem policy denies this operation")
        for protected in metadata:
            if protected.contains(path) and not any(
                    entry.access.value == "write" and protected.contains(entry.path) and entry.path.contains(path)
                    for entry in policy.resolved_entries):
                raise PermissionError("Existing project metadata is protected")

    def _directory_plan(self, path, recursive, policy, metadata, directories, count):
        """Authorize the complete missing suffix before ANY directory is made.

        Existing ancestors need no new write authority: a narrower explicit
        child grant can legitimately override a read/deny ancestor. Every
        missing ancestor, however, is a separate creation and needs its own
        effective write permission. The native helper rechecks the inspected
        prefix inode and missing suffix, refusing a changed plan without retry.
        """
        parts = path.parts[len(self.mount.parts):]
        if len(parts) > MAX_DEPTH:
            raise ValueError("Directory creation exceeds workspace depth limit")
        existing = 0
        while existing < len(parts) and parts[:existing + 1] in directories:
            existing += 1
        missing = len(parts) - existing
        if not recursive and missing > 1:
            raise RpcError(-32004, "Requested directory parent does not exist")
        if count + missing > MAX_ENTRIES:
            raise ValueError("Directory creation exceeds workspace admission limit")
        for size in range(existing + 1, len(parts) + 1):
            self._require_write(policy, self.mount.append(parts[:size]), metadata)
        parent = directories[parts[:existing]]
        return ["mkdirs" if recursive else "mkdir", str(self.root), "/".join(parts) or ".",
                str(missing), str(parent.st_dev), str(parent.st_ino)]

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
            making = call.method == "fs/createDirectory"
            metadata_query = call.method == "fs/getMetadata"
            canonicalizing = call.method == "fs/canonicalize"
            inspecting = metadata_query or canonicalizing
            listing = call.method == "fs/readDirectory"
            walking = call.method == "fs/walk"
            removing = call.method == "fs/remove"
            copying = call.method == "fs/copy"
            planned = listing or walking or removing or copying
            planned_result = None
            try:
                if copying:
                    allowed = {"sourcePath", "destinationPath", "recursive", "sandbox"}
                elif listing or walking:
                    allowed = {"path", "sandbox"} | ({"options"} if walking else set())
                else:
                    allowed = {"path", "sandbox"} | (set() if canonicalizing else {"followSymlinks"}) | (
                        {"dataBase64"} if writing else {"recursive"} if making else {"recursive", "force"} if removing else set())
                if type(params) is not dict or set(params) - allowed:
                    raise ValueError("Unsupported filesystem request field")
                if params.get("followSymlinks") is not None and type(params["followSymlinks"]) is not bool:
                    raise ValueError("Invalid followSymlinks option")
                if (making or removing or copying) and params.get("recursive") is not None and type(params["recursive"]) is not bool:
                    raise ValueError("Invalid recursive option")
                if removing and params.get("force") is not None and type(params["force"]) is not bool:
                    raise ValueError("Invalid force option")
                if copying and type(params.get("recursive")) is not bool:
                    raise ValueError("Copy requires an explicit recursive boolean")
                # Retain the complete context unchanged, not a writable-root
                # approximation. Unsupported semantics refuse the entire RPC.
                intent = prepare_policy_intent(params.get("sandbox"), session_id=call.session_id,
                    request_id=str(call.request_id), method=call.method)
                policy = parse_context(intent.to_document()["context"])
                path = GuestPath.from_uri(params["sourcePath"] if copying else params["path"])
                if not self.mount.contains(path) or (path == self.mount and not (making or inspecting or listing or walking)):
                    raise ValueError("Path is outside the admitted workspace mapping")
                decision = policy.decide_uri(path.uri)
                if not (decision.can_write if writing or making or removing else decision.can_read):
                    raise PermissionError("The supplied filesystem policy denies this operation")
                destination = GuestPath.from_uri(params["destinationPath"]) if copying else None
                if copying and (not self.mount.contains(destination) or destination == self.mount):
                    raise ValueError("Copy destination is outside the admitted workspace mapping")
                metadata, directories, count, nodes = self._inspect(policy)
                if writing or making or removing:
                    self._require_write(policy, path, metadata)
                if copying:
                    self._require_write(policy, destination, metadata)
                if writing:
                    # A successful write must not introduce a file kind that
                    # invalidates every subsequent workspace operation. This
                    # admission limit also applies to explicit policy grants.
                    if path.parts[-1] == ".git":
                        raise ValueError("Creating gitdir files requires the native alias resolver")
                    encoded = params["dataBase64"]
                    if not isinstance(encoded, str) or len(encoded) > ((MAX_DATA + 2) // 3) * 4:
                        raise ValueError("Write exceeds the admitted data bound")
                    data = base64.b64decode(encoded, validate=True)
                    if len(data) > MAX_DATA:
                        raise ValueError("Write exceeds the admitted data bound")
                else:
                    data = b""
                relative = "/".join(path.parts[len(self.mount.parts):]) or "."
                parts = path.parts[len(self.mount.parts):]
                if planned:
                    data = self._snapshot(nodes)
                    if listing:
                        planned_result = self._listing(parts, nodes, policy)
                    elif walking:
                        planned_result = self._walk(parts, nodes, policy, params["options"])
                    elif removing:
                        self._remove_plan(parts, nodes, policy, metadata, params.get("recursive") is not False)
                    else:
                        target = destination.parts[len(self.mount.parts):]
                        self._copy_plan(parts, target, nodes, policy, metadata, params["recursive"])
                    if removing:
                        arguments = ["remove", str(self.root), relative, str(len(data)),
                                     "0" if params.get("recursive") is False else "1", "0" if params.get("force") is False else "1"]
                    elif copying:
                        arguments = ["copy", str(self.root), relative, str(len(data)), "/".join(target), "1" if params["recursive"] else "0"]
                    else:
                        arguments = ["tree", str(self.root), relative, str(len(data))]
                elif making:
                    arguments = self._directory_plan(path, params.get("recursive") is not False,
                        policy, metadata, directories, count)
                elif inspecting:
                    operation = "canonicalize" if canonicalizing else (
                        "metadata-nofollow" if params.get("followSymlinks") is False else "metadata")
                    arguments = [operation, str(self.root), relative, "0"]
                else:
                    arguments = ["write" if writing else "read", str(self.root), relative, str(len(data))]
            except (PolicyError, ValueError, KeyError, PermissionError, OSError, binascii.Error, UnicodeError) as error:
                raise RpcError(-32000, str(error)) from error
            output = await self._native_operation(arguments, data,
                empty_output=writing or making or canonicalizing or planned)
            if planned:
                # Listings are assembled from actual descriptor metadata only
                # after the native helper independently verifies the complete
                # tree and identities. A missing native target is never a
                # successful empty listing. Mutation success is syscall success.
                if listing or walking:
                    if planned_result is None:
                        raise RpcError(-32603, "Native listing unexpectedly admitted a missing target")
                    return planned_result
                return {}
            if metadata_query:
                return _native_metadata(output)
            if canonicalizing:
                # The native helper has resolved the real admitted object
                # through the pinned mount with aliases forbidden. Only now
                # may its canonical guest URI be returned. Physical host
                # paths and successful lexical-only guesses never escape.
                return {"path": path.uri}
            return {} if writing or making else {"dataBase64": base64.b64encode(output).decode("ascii")}

    async def _native_operation(self, arguments, data=b"", *, empty_output=False):
        """Run the existing FD helper while the caller owns this backend's lock.

        Authorization stays with the caller: managed RPC or the separate
        bootstrap read authority. This method creates no policy or new root.
        Actual child reaping precedes lock release even under cancellation.
        """
        spawning = asyncio.create_task(asyncio.create_subprocess_exec(
            self.helper, *arguments,
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            close_fds=True, pass_fds=(self.root,), env={}))
        process = communicate = None
        async def settle(task):
            while True:
                try:
                    return await asyncio.shield(task)
                except asyncio.CancelledError:
                    if task.done():
                        return task.result()
        try:
            process = self.process = await asyncio.shield(spawning)
            communicate = asyncio.create_task(process.communicate(data))
            output, diagnostic = await asyncio.wait_for(asyncio.shield(communicate), 30)
            if process.returncode != 0:
                raise _native_failure(diagnostic)
            if diagnostic or (empty_output and output) or len(output) > MAX_DATA:
                raise RpcError(-32000, "Native filesystem response violates its contract")
            return output
        finally:
            # Reclaim a spawn whose caller was cancelled before receiving its
            # process object; never leave a child outside the shared ownership.
            if process is None:
                process = self.process = await settle(spawning)
            try:
                if process.returncode is None:
                    process.kill()
                if communicate is None:
                    communicate = asyncio.create_task(process.communicate())
                await settle(communicate)
            finally:
                self.process = None

    async def close(self, session_id):
        async with self.lock:
            if not self.closed:
                if self.session is not None and self.session != session_id:
                    raise RpcError(-32000, "Cannot close a different filesystem session")
                self.closed = True
                os.close(self.root)
