"""Private startup inputs and factual manifest publication for the native owner.

The Android application chooses the launch file before a controller exists.
The native owner publishes its own kernel identity and the paths it has opened;
neither model RPC nor a controller packet can supply these facts.
"""
import json
import os
from pathlib import Path
import stat
from tools.executor.native_path_uri import path_uri, uri_path

MAX_MANIFEST_BYTES = 65536
LAUNCH_SCHEMA = "foldgpt.native-launch.v1"
STARTUP_SCHEMA = "foldgpt.native-startup.v1"


def strict_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate native startup field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite native startup value")))


def absolute_path(value):
    if (type(value) is not str or not value.startswith("/") or value == "/"
            or any(ord(char) < 32 or ord(char) == 127 for char in value)
            or any(part in ("", ".", "..") for part in value[1:].split("/"))
            or len(value.encode("utf-8")) >= 4096):
        raise ValueError("Native startup requires an unambiguous absolute path")
    return Path(value)


def canonical_path(value):
    path = absolute_path(value)
    if path.resolve(strict=True) != path:
        raise ValueError("Native startup paths must have their actual canonical spelling")
    return path


def canonical_uri(value):
    path = absolute_path(uri_path(value))
    # These are controller paths. Their native names need not exist: the GNU
    # root filesystem supplies them later, where Rust verifies their routing.
    return path


def private_directory(path, uid):
    path = canonical_path(str(path))
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != uid or stat.S_IMODE(info.st_mode) & 0o077:
            raise PermissionError("Native startup directory must be private to the application")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def read_private_json(path, uid):
    path = canonical_path(str(path))
    parent = private_directory(path.parent, uid)
    descriptor = None
    try:
        descriptor = os.open(path.name, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW, dir_fd=parent)
        before = os.fstat(descriptor)
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != uid or before.st_nlink != 1
                or before.st_mode & 0o077 or before.st_size > MAX_MANIFEST_BYTES):
            raise PermissionError("Native startup input must be a bounded private ordinary file")
        chunks, consumed = [], 0
        while chunk := os.read(descriptor, min(65536, MAX_MANIFEST_BYTES + 1 - consumed)):
            chunks.append(chunk)
            consumed += len(chunk)
            if consumed > MAX_MANIFEST_BYTES:
                raise ValueError("Native startup input grew beyond its bound")
        after = os.fstat(descriptor)
        current = os.stat(path.name, dir_fd=parent, follow_symlinks=False)
        if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
                or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError("Native startup input changed during admission")
        return strict_json(b"".join(chunks))
    finally:
        if descriptor is not None:
            os.close(descriptor)
        os.close(parent)


def read_launch(path, *, uid, broker_directory, projects_directory):
    value = read_private_json(path, uid)
    if (type(value) is not dict or set(value) != {
            "schema", "workspace", "socketPath", "manifestPath", "controllerRoots"}
            or value["schema"] != LAUNCH_SCHEMA):
        raise ValueError("Native launch input differs from its exact installed contract")
    broker = canonical_path(str(broker_directory))
    projects = canonical_path(str(projects_directory))
    workspace = canonical_path(value["workspace"])
    if not workspace.is_relative_to(projects):
        raise ValueError("Native workspace must be inside the application's projects")
    for name, filename in (("socketPath", "owner.sock"), ("manifestPath", "startup.json")):
        if absolute_path(value[name]) != broker / filename:
            raise ValueError("Native endpoint and manifest names are owned by the application")
    launch_path = canonical_path(str(path))
    if broker.is_relative_to(workspace) or launch_path.is_relative_to(workspace):
        raise ValueError("Native startup inputs must stay outside the model workspace")
    roots = value["controllerRoots"]
    if type(roots) is not list or not 1 <= len(roots) <= 128:
        raise ValueError("Native launch requires a bounded controller root list")
    seen = set()
    for uri in roots:
        root = canonical_uri(uri)
        if root in seen or root.is_relative_to(workspace) or workspace.is_relative_to(root):
            raise ValueError("Controller roots must be distinct and disjoint from the native workspace")
        seen.add(root)
    descriptor = private_directory(workspace, uid)
    os.close(descriptor)
    return value


class StartupManifest:
    """Publish once; remove only this inode after native cleanup is verified."""
    def __init__(self, path, *, socket_path, workspace, shared_paths, controller_roots,
                 parent_environment, directory_fd, host_schema=None):
        self.path = absolute_path(str(path))
        self.identity = None
        self.directory_fd = os.dup(directory_fd)
        os.set_inheritable(self.directory_fd, False)
        try:
            if host_schema not in (None, "foldgpt.host.v2"):
                raise ValueError("Unsupported explicitly selected human host schema")
            if os.getuid() <= 0 or os.getuid() != os.geteuid():
                raise ValueError("Native startup manifest requires an ordinary nonroot owner")
            directory = os.fstat(self.directory_fd)
            named = self.path.parent.stat(follow_symlinks=False)
            if ((named.st_dev, named.st_ino) != (directory.st_dev, directory.st_ino)
                    or directory.st_uid != os.getuid() or directory.st_mode & 0o077):
                raise ValueError("Manifest directory differs from the pinned native owner")
            workspace = canonical_path(str(workspace))
            socket_path = canonical_path(str(socket_path))
            endpoint = socket_path.stat(follow_symlinks=False)
            if (socket_path.parent != self.path.parent or not stat.S_ISSOCK(endpoint.st_mode)
                    or endpoint.st_uid != os.getuid() or endpoint.st_mode & 0o077
                    or self.path.is_relative_to(workspace)):
                raise ValueError("Manifest must refer to the owned private native endpoint")
            if not 1 <= len(shared_paths) <= 128:
                raise ValueError("Native shared path inventory must be bounded")
            identities, seen = [], set()
            for item in shared_paths:
                item = canonical_path(str(item))
                if item in seen:
                    raise ValueError("Duplicate shared native path")
                seen.add(item)
                info = item.stat(follow_symlinks=False)
                if not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                    raise ValueError("Shared native path must identify an ordinary file or directory")
                identities.append({"path": path_uri(item), "device": info.st_dev, "inode": info.st_ino})
            if workspace not in seen:
                raise ValueError("The actual workspace is absent from the shared path inventory")
            if type(controller_roots) is not list or not 1 <= len(controller_roots) <= 128:
                raise ValueError("Native startup requires a bounded controller root list")
            controller_seen = set()
            for uri in controller_roots:
                root = canonical_uri(uri)
                if (root in controller_seen or root.is_relative_to(workspace)
                        or workspace.is_relative_to(root)):
                    raise ValueError("Controller and workspace roots must remain distinct")
                controller_seen.add(root)
            if (type(parent_environment) is not dict or len(parent_environment) > 128
                    or any(type(name) is not str or not name or "=" in name or "\0" in name
                           or type(value) is not str or "\0" in value
                           for name, value in parent_environment.items())):
                raise ValueError("Native parent environment must be a bounded variable snapshot")
            value = {"schema": STARTUP_SCHEMA, "socketPath": str(socket_path),
                "peer": {"pid": os.getpid(), "uid": os.getuid(), "gid": os.getgid()},
                "workspaceRoot": path_uri(workspace), "sharedPaths": identities,
                "controllerRoots": controller_roots, "parentEnvironment": parent_environment}
            if host_schema is not None:
                value["hostSchema"] = host_schema
            data = (json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n").encode("ascii")
            if len(data) > MAX_MANIFEST_BYTES:
                raise ValueError("Native startup manifest exceeds its bound")
            descriptor = os.open(self.path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600, dir_fd=self.directory_fd)
            try:
                info = os.fstat(descriptor)
                self.identity = (info.st_dev, info.st_ino)
                remaining = memoryview(data)
                while remaining:
                    count = os.write(descriptor, remaining)
                    if count <= 0:
                        raise OSError("Native startup manifest write is incomplete")
                    remaining = remaining[count:]
                os.fsync(descriptor)
                os.fsync(self.directory_fd)
            finally:
                os.close(descriptor)
        except BaseException:
            # Failed publication is never an advertised endpoint. This object
            # has started no worker; discard only the file created by it.
            try:
                self.remove()
            finally:
                self.close()
            raise

    def remove(self):
        if self.identity is not None:
            current = os.stat(self.path.name, dir_fd=self.directory_fd, follow_symlinks=False)
            if (not stat.S_ISREG(current.st_mode) or current.st_nlink != 1
                    or (current.st_dev, current.st_ino) != self.identity):
                raise ValueError("Native startup manifest ownership changed")
            os.unlink(self.path.name, dir_fd=self.directory_fd)
            os.fsync(self.directory_fd)
            self.identity = None

    def close(self):
        if self.directory_fd is not None:
            os.close(self.directory_fd)
            self.directory_fd = None
