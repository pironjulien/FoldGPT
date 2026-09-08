"""Direct model filesystem for an already-authenticated ordinary-UID owner.

This is the upstream no-sandbox/Disabled filesystem contract, not a policy
fallback and not HostFileAuthority. Paths are actual owner-native file URIs.
The caller must authenticate the model channel and bind its lifetime. Managed
and external contexts are refused, never projected into this authority.

Blocking filesystem work is serialized and cancellation joins the worker before
releasing ownership. Regular read descriptors and their immutable mode/session
remain owned until explicit close, a read error, or connection shutdown.
"""
import asyncio
import base64
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass
import errno
import os
from pathlib import Path
import re
import stat
import threading
from urllib.parse import unquote_to_bytes, urlsplit

from tools.executor.exec_server import FILE_METHODS, RpcError, validate_operation


MAX_READ_FILE_BYTES = 512 * 1024 * 1024  # DirectFileSystem upstream limit.
MAX_BLOCK = 1024 * 1024  # FILE_READ_CHUNK_SIZE.
MAX_HANDLES = 128
MAX_HANDLE_BYTES = 32
STREAM_LIFECYCLE = frozenset({"fs/readBlock", "fs/close"})


def _invalid(message):
    return RpcError(-32602, message)


def native_path(uri):
    """Decode a local file URI without rebasing, resolving aliases, or a mount map."""
    if type(uri) is not str:
        raise _invalid("Expected a native file URI")
    try:
        parsed = urlsplit(uri)
        if (parsed.scheme != "file" or parsed.query or parsed.fragment
                or parsed.netloc not in {"", "localhost"}):
            raise ValueError("Expected a local absolute file URI")
        decoded = unquote_to_bytes(parsed.path)
        if b"\0" in decoded:
            raise ValueError("Expected an absolute native path without NUL")
        if os.name == "nt":
            text = decoded.decode("utf-8", errors="strict")
            if re.match(r"^/[A-Za-z]:/", text):
                text = text[1:]
            path = Path(text)
        else:
            if re.match(rb"^/[A-Za-z][:|](?:/|$)", decoded):
                raise ValueError("Windows file URI cannot name a native POSIX path")
            # Upstream PathUri preserves percent-encoded non-UTF-8 POSIX bytes.
            path = Path(os.fsdecode(decoded))
        if not path.is_absolute():
            raise ValueError("Expected an absolute native path without NUL")
        return path
    except (ValueError, UnicodeError) as error:
        raise _invalid(str(error)) from error


def validate_ordinary_filesystem_context(context):
    """Return one immutable authority mode; refuse malformed or other policies.

    FileSystemSandboxContext has optional cwd/home/temps but required permissions
    and windowsSandboxLevel. Disabled does not interpret path grants or platform
    sandbox preferences; their types are nevertheless validated, not discarded.
    """
    if context is None:
        return "ordinary-uid"
    allowed = {"permissions", "cwd", "workspaceRoots", "userHomeDir",
        "temporaryDirectories", "windowsSandboxLevel", "windowsSandboxPrivateDesktop",
        "windowsSandboxProxySettingsMode", "useLegacyLandlock"}
    if (type(context) is not dict or set(context) - allowed
            or not {"permissions", "windowsSandboxLevel"} <= set(context)):
        raise _invalid("Invalid complete filesystem sandbox context")
    permissions = context["permissions"]
    if type(permissions) is not dict or permissions != {"type": "disabled"}:
        raise _invalid("Ordinary UID filesystem requires absent context or explicit Disabled permissions")
    if context["windowsSandboxLevel"] not in ("disabled", "restricted-token", "elevated"):
        raise _invalid("Invalid Windows sandbox level")
    for name in ("windowsSandboxPrivateDesktop", "useLegacyLandlock"):
        if name in context and type(context[name]) is not bool:
            raise _invalid(name + " must be a boolean")
    if context.get("windowsSandboxProxySettingsMode") not in (None, "reconcile", "preserve"):
        raise _invalid("Invalid Windows sandbox proxy preference")
    for name in ("cwd", "userHomeDir"):
        if context.get(name) is not None:
            native_path(context[name])
    for name in ("workspaceRoots", "temporaryDirectories"):
        if name not in context or (name == "temporaryDirectories" and context[name] is None):
            continue
        if type(context[name]) is not list:
            raise _invalid(name + " must be an array of native file URIs")
        for uri in context[name]:
            native_path(uri)
    return "ordinary-uid"


def _check(cancelled):
    if cancelled.is_set():
        raise InterruptedError(errno.EINTR, "Filesystem operation cancelled")


def _rpc_io(error):
    code = -32004 if isinstance(error, FileNotFoundError) else (
        -32600 if isinstance(error, (ValueError, OverflowError, PermissionError)) or getattr(error, "errno", None) == errno.EINVAL
        else -32603)
    return RpcError(code, str(error))


def _directory_flags():
    if os.name != "posix" or not hasattr(os, "O_NOFOLLOW") or os.open not in os.supports_dir_fd:
        raise OSError(errno.ENOTSUP, "Descriptor-based no-follow filesystem requires POSIX")
    return getattr(os, "O_PATH", os.O_RDONLY) | os.O_DIRECTORY | os.O_CLOEXEC


def _parts(path):
    parts = path.parts[1:]
    if any(part in (".", "..") for part in parts):
        raise ValueError("No-follow filesystem requires a normalized absolute path")
    return parts


@contextmanager
def _parent(path):
    flags = _directory_flags()
    parts = _parts(path)
    if not parts:
        raise ValueError("Path must name an entry")
    fd = os.open(path.anchor, flags)
    try:
        for part in parts[:-1]:
            child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd, parts[-1]
    finally:
        os.close(fd)


def _open(path, flags, follow):
    flags |= getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_BINARY", 0)
    if follow:
        return os.open(path, flags, 0o666)
    with _parent(path) as (parent, leaf):
        return os.open(leaf, flags | os.O_NOFOLLOW, 0o666, dir_fd=parent)


def _open_read(path, follow=True):
    fd = _open(path, os.O_RDONLY, follow)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise ValueError("Path is not a regular file")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _stat(path, follow=True):
    if follow:
        info = path.lstat()
        link = stat.S_ISLNK(info.st_mode)
        return (path.stat() if link else info), link
    if not _parts(path):
        fd = os.open(path.anchor, _directory_flags())
        try:
            return os.fstat(fd), False
        finally:
            os.close(fd)
    with _parent(path) as (parent, leaf):
        info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode):
            raise ValueError("Path contains a symbolic link")
        return info, False


def _metadata(path, follow):
    info, link = _stat(path, follow)
    return {"isDirectory": stat.S_ISDIR(info.st_mode), "isFile": stat.S_ISREG(info.st_mode),
        "isSymlink": link, "size": info.st_size,
        "createdAtMs": getattr(info, "st_birthtime_ns", 0) // 1000000,
        "modifiedAtMs": info.st_mtime_ns // 1000000}


def _mkdir(path, recursive, follow, cancelled):
    if follow:
        _check(cancelled)
        path.mkdir(parents=recursive, exist_ok=recursive)
        return
    flags = _directory_flags()
    parts = _parts(path)
    if not parts and not recursive:
        raise FileExistsError(errno.EEXIST, "Directory already exists", str(path))
    fd = os.open(path.anchor, flags)
    try:
        for index, part in enumerate(parts):
            _check(cancelled)
            if not recursive and index == len(parts) - 1:
                os.mkdir(part, dir_fd=fd)
                return
            try:
                child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                if not recursive:
                    raise
                try:
                    os.mkdir(part, dir_fd=fd)
                except FileExistsError:
                    pass
                child = os.open(part, flags | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
    finally:
        os.close(fd)


def _names(path, cancelled):
    result = []
    with os.scandir(path) as entries:
        for entry in entries:
            _check(cancelled)
            try:
                info = entry.stat(follow_symlinks=True)
            except OSError:
                continue  # Same omission for inaccessible/dangling links as upstream.
            name = os.fsencode(entry.name).decode("utf-8", errors="replace") if os.name == "posix" else entry.name
            result.append((name, info))
    return result


def _walk(path, options, cancelled):
    fields = {"maxDepth", "maxDirectories", "maxEntries", "followDirectorySymlinks", "pruneHiddenDirectories"}
    if type(options) is not dict or set(options) - fields or not fields - {"pruneHiddenDirectories"} <= set(options):
        raise _invalid("Invalid filesystem walk options")
    for name, minimum, maximum in (("maxDepth", 0, 64), ("maxDirectories", 1, 10000), ("maxEntries", 1, 50000)):
        if type(options[name]) is not int or not minimum <= options[name] <= maximum:
            raise _invalid("Invalid official filesystem walk limit: " + name)
    for name in ("followDirectorySymlinks", "pruneHiddenDirectories"):
        if name in options and type(options[name]) is not bool:
            raise _invalid(name + " must be a boolean")
    outcome = {"entries": [], "errors": [], "truncated": False}
    info, link = _stat(path)
    follow = options["followDirectorySymlinks"]
    if not stat.S_ISDIR(info.st_mode) or (link and not follow):
        return outcome
    queue = deque([(path, 0)])
    visited = {path.resolve(strict=True) if follow else path}
    directories, count, size = 1, 0, 0

    def append(kind, value):
        nonlocal size
        size += 64 + len(value["path"].encode("utf-8")) + len(value.get("message", "").encode("utf-8"))
        if size > 4 * 1024 * 1024:
            outcome["truncated"] = True
            return False
        outcome[kind].append(value)
        return True

    while queue:
        directory, depth = queue.popleft()
        _check(cancelled)
        try:
            names = sorted(name for name, _ in _names(directory, cancelled))
        except OSError as error:
            if not append("errors", {"path": directory.as_uri(), "message": str(error)}):
                return outcome
            continue
        for name in names:
            _check(cancelled)
            if count == options["maxEntries"]:
                outcome["truncated"] = True
                return outcome
            count += 1
            child = directory / name
            try:
                info, link = _stat(child)
            except OSError as error:
                if not append("errors", {"path": child.as_uri(), "message": str(error)}):
                    return outcome
                continue
            is_dir = stat.S_ISDIR(info.st_mode)
            if (link and (not follow or not is_dir)) or not (is_dir or stat.S_ISREG(info.st_mode)):
                continue
            if not append("entries", {"path": child.as_uri(), "kind": "directory" if is_dir else "file"}):
                return outcome
            if is_dir and depth < options["maxDepth"]:
                if options.get("pruneHiddenDirectories", False) and name.startswith("."):
                    continue
                try:
                    identity = child.resolve(strict=True) if follow else child
                except OSError as error:
                    if not append("errors", {"path": child.as_uri(), "message": str(error)}):
                        return outcome
                    continue
                if identity in visited:
                    continue
                visited.add(identity)
                if directories == options["maxDirectories"]:
                    outcome["truncated"] = True
                else:
                    directories += 1
                    queue.append((child, depth + 1))
    return outcome


def _write_all(fd, data, cancelled):
    view = memoryview(data)
    while view:
        _check(cancelled)
        written = os.write(fd, view[:MAX_BLOCK])
        if written == 0:
            raise OSError(errno.EIO, "File write made no progress")
        view = view[written:]


def _copy(source, target, recursive, cancelled):
    _check(cancelled)
    info = source.lstat()
    if stat.S_ISLNK(info.st_mode):
        os.symlink(os.readlink(source), target, target_is_directory=source.is_dir())
    elif stat.S_ISDIR(info.st_mode):
        if not recursive:
            raise ValueError("fs/copy requires recursive: true for a directory")
        resolved_source = source.resolve(strict=True)
        resolved_target = target.resolve(strict=False)
        if resolved_target == resolved_source or resolved_source in resolved_target.parents:
            raise ValueError("fs/copy cannot copy a directory to itself or its descendants")
        target.mkdir(parents=True, exist_ok=True)
        with os.scandir(source) as entries:
            for entry in entries:
                _check(cancelled)
                mode = entry.stat(follow_symlinks=False).st_mode
                if stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode):
                    _copy(source / entry.name, target / entry.name, True, cancelled)
    elif stat.S_ISREG(info.st_mode):
        read_fd = _open_read(source)
        try:
            write_fd = _open(target, os.O_WRONLY | os.O_CREAT, True)
            try:
                original, destination = os.fstat(read_fd), os.fstat(write_fd)
                if (original.st_dev, original.st_ino) == (destination.st_dev, destination.st_ino):
                    raise ValueError("fs/copy source and destination refer to the same file")
                os.ftruncate(write_fd, 0)
                while True:
                    _check(cancelled)
                    data = os.read(read_fd, MAX_BLOCK)
                    if not data:
                        break
                    _write_all(write_fd, data, cancelled)
                if hasattr(os, "fchmod"):
                    os.fchmod(write_fd, stat.S_IMODE(original.st_mode))
                else:
                    os.chmod(target, stat.S_IMODE(original.st_mode))
            finally:
                os.close(write_fd)
        finally:
            os.close(read_fd)
    else:
        raise ValueError("fs/copy supports regular files, directories, and symlinks")


def _remove(path, recursive, force, follow, cancelled):
    _check(cancelled)
    if not follow:
        if recursive:
            raise OSError(errno.ENOTSUP, "Recursive no-follow removal is unsupported by upstream")
        try:
            with _parent(path) as (parent, leaf):
                info = os.stat(leaf, dir_fd=parent, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode):
                    raise ValueError("Path contains a symbolic link")
                (os.rmdir if stat.S_ISDIR(info.st_mode) else os.unlink)(leaf, dir_fd=parent)
        except FileNotFoundError:
            if not force:
                raise
        return
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not force:
            raise
        return
    if stat.S_ISDIR(info.st_mode):
        if recursive:
            # shutil.rmtree uses descriptor-relative traversal on Android/POSIX.
            # Its per-syscall audit hook is unavailable, so retain the worker
            # until completion even when cancellation arrives during traversal.
            import shutil
            shutil.rmtree(path)
        else:
            path.rmdir()
    else:
        path.unlink()  # Follow=true still removes a final symlink, not its target.


@dataclass(frozen=True)
class OrdinaryReadHandle:
    fd: int
    session_id: str
    mode: str


@dataclass
class _Operation:
    cancelled: threading.Event
    acquired_handle: str | None = None


class OrdinaryUidFilesBackend:
    supported_methods = FILE_METHODS
    capabilities = frozenset({"sandboxedFileStreaming"})

    def __init__(self, *, lock=None):
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise ValueError("Ordinary UID filesystem must not run as root")
        self.lock = lock if lock is not None else asyncio.Lock()
        self.session = None
        self.closed = False
        self.handles = {}

    def _bind(self, session):
        if type(session) is not str or not session or any(ord(c) < 32 for c in session):
            raise _invalid("Invalid executor session identity")
        if self.session is None:
            self.session = session
        elif self.session != session:
            raise RpcError(-32000, "Filesystem belongs to another executor session")

    def _drop(self, identifier):
        handle = self.handles.pop(identifier, None)
        if handle is not None:
            os.close(handle.fd)

    async def handle(self, call, notify):
        if call.method not in self.supported_methods:
            raise RpcError(-32601, "Unknown ordinary UID filesystem method")
        validate_operation(call.method, call.params)
        params = call.params
        mode = None if call.method in STREAM_LIFECYCLE else validate_ordinary_filesystem_context(params.get("sandbox"))
        async with self.lock:
            self._bind(call.session_id)
            if self.closed:
                raise RpcError(-32000, "Filesystem session is closed")
            operation = _Operation(threading.Event())
            worker = asyncio.create_task(asyncio.to_thread(self._owned_result, call.method,
                params, call.session_id, mode, operation))
            try:
                success, result = await asyncio.shield(worker)
                if not success:
                    raise result
                return result
            except asyncio.CancelledError:
                operation.cancelled.set()
                # Do not leave a detached writer, reader, or opened descriptor.
                while not worker.done():
                    try:
                        await asyncio.shield(worker)
                    except asyncio.CancelledError:
                        continue
                    except BaseException:
                        break
                if operation.acquired_handle is not None:
                    self._drop(operation.acquired_handle)
                if worker.done() and not worker.cancelled():
                    worker.exception()
                raise
            except (OSError, ValueError, OverflowError) as error:
                raise _rpc_io(error) from error

    def _owned_result(self, method, params, session, mode, operation):
        # A joined worker returns its exact outcome. This avoids Python 3.14's
        # shield cancellation logging a handled I/O exception as unobserved.
        try:
            return True, self._execute(method, params, session, mode, operation)
        except BaseException as error:
            return False, error

    def _execute(self, method, params, session, mode, operation):
        cancelled = operation.cancelled
        _check(cancelled)
        if method in {"fs/open", "fs/readBlock", "fs/close"}:
            identifier = params["handleId"]
            if len(identifier.encode("utf-8")) > MAX_HANDLE_BYTES:
                raise ValueError("File read handle ID exceeds 32 bytes")
            if method == "fs/close":
                self._drop(identifier)
                return {}
            if method == "fs/open":
                if identifier in self.handles or len(self.handles) >= MAX_HANDLES:
                    raise ValueError("File read handle already exists or connection limit reached")
                fd = _open_read(native_path(params["path"]))
                self.handles[identifier] = OrdinaryReadHandle(fd, session, mode)
                operation.acquired_handle = identifier
                return {"handleId": identifier}
            if not 1 <= params["len"] <= MAX_BLOCK:
                raise ValueError("File read block length must be between 1 and 1048576")
            handle = self.handles.get(identifier)
            if handle is None:
                raise FileNotFoundError(errno.ENOENT, "Unknown file read handle")
            if handle.session_id != session or handle.mode != "ordinary-uid":
                raise RpcError(-32000, "File handle belongs to another session or mode")
            operation.acquired_handle = identifier
            try:
                data = bytearray()
                while len(data) < params["len"]:
                    _check(cancelled)
                    offset = params["offset"] + len(data)
                    if offset >= 2**64:
                        raise ValueError("File read offset overflowed")
                    try:
                        if hasattr(os, "pread"):
                            chunk = os.pread(handle.fd, params["len"] - len(data), offset)
                        else:
                            os.lseek(handle.fd, offset, os.SEEK_SET)
                            chunk = os.read(handle.fd, params["len"] - len(data))
                    except InterruptedError:
                        continue
                    if not chunk:
                        break
                    data.extend(chunk)
                return {"chunk": base64.b64encode(data).decode("ascii"), "eof": len(data) < params["len"]}
            except BaseException:
                self._drop(identifier)
                raise
        path = native_path(params["sourcePath"] if method == "fs/copy" else params["path"])
        follow = params.get("followSymlinks") is not False
        recursive = params.get("recursive") is not False
        if method == "fs/readFile":
            fd = _open_read(path, follow)
            try:
                if os.fstat(fd).st_size > MAX_READ_FILE_BYTES:
                    raise ValueError("File exceeds the upstream 512 MiB read limit")
                data = bytearray()
                while True:
                    _check(cancelled)
                    chunk = os.read(fd, min(MAX_BLOCK, MAX_READ_FILE_BYTES + 1 - len(data)))
                    if not chunk:
                        break
                    data.extend(chunk)
                    if len(data) > MAX_READ_FILE_BYTES:
                        raise ValueError("File exceeds the upstream 512 MiB read limit")
                return {"dataBase64": base64.b64encode(data).decode("ascii")}
            finally:
                os.close(fd)
        if method == "fs/writeFile":
            data = base64.b64decode(params["dataBase64"], validate=True)
            fd = _open(path, os.O_WRONLY | os.O_CREAT, follow)
            try:
                if not follow and not stat.S_ISREG(os.fstat(fd).st_mode):
                    raise ValueError("Path is not a regular file")
                os.ftruncate(fd, 0)
                _write_all(fd, data, cancelled)
            finally:
                os.close(fd)
            return {}
        if method == "fs/getMetadata":
            return _metadata(path, follow)
        if method == "fs/canonicalize":
            return {"path": path.resolve(strict=True).as_uri()}
        if method == "fs/createDirectory":
            _mkdir(path, recursive, follow, cancelled)
        elif method == "fs/readDirectory":
            return {"entries": [{"fileName": name, "isDirectory": stat.S_ISDIR(info.st_mode),
                "isFile": stat.S_ISREG(info.st_mode)} for name, info in _names(path, cancelled)]}
        elif method == "fs/walk":
            return _walk(path, params["options"], cancelled)
        elif method == "fs/remove":
            _remove(path, recursive, params.get("force") is not False, follow, cancelled)
        elif method == "fs/copy":
            _copy(path, native_path(params["destinationPath"]), recursive, cancelled)
        return {}

    async def close(self, session_id):
        async with self.lock:
            # The trusted owner may stop before ExecServer.initialize assigns
            # a session. Only an unused backend can close without that identity.
            if session_id is None:
                if self.session is not None or self.handles:
                    raise RpcError(-32000, "Cannot close an acquired filesystem without its session identity")
            else:
                self._bind(session_id)
            if not self.closed:
                for identifier in list(self.handles):
                    self._drop(identifier)
                self.closed = True
