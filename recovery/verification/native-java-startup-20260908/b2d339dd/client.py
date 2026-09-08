"""One real GNU-controller to installed Bionic-owner production qualification.

Run inside the Fold's existing GNU PRoot after Java PREPARE has published the
private startup manifest. This client uses actual kernel credentials and rights;
it never starts the owner or substitutes a fixture for a process/file response.
Only a newly reserved project is written. Android lifecycle/waitpid evidence
still comes from the owning Java service, independently of this client.
"""
import argparse
import array
import base64
import ctypes
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import time
from urllib.parse import unquote, urlsplit
import uuid

SCHEMA = "foldgpt.native-runtime.v1"
MAX_PACKET = 65536
CHUNK = 32768
MAX_DATA = 16777216


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(data):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "Duplicate native response field")
            value[key] = item
        return value
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite native response")))


def payload(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":")).encode("ascii")


def uri_path(value):
    uri = urlsplit(value)
    require(uri.scheme == "file" and not uri.netloc and not uri.query and not uri.fragment,
            "Expected a local native file URI")
    path = Path(unquote(uri.path, errors="strict"))
    require(path.is_absolute() and path.as_uri() == value, "Noncanonical native file URI")
    require(str(path) == os.path.realpath(path), "Native path alias is unsupported")
    return path


def private(path, *, directory=False):
    require(path.is_absolute() and path.resolve(strict=True) == path, "Private startup path has an alias")
    info = path.stat(follow_symlinks=False)
    require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, "Startup path is not owner-private")
    if directory:
        require(stat.S_ISDIR(info.st_mode), "Startup parent is not an ordinary directory")
    return info


def manifest(path):
    private(path.parent, directory=True)
    info = private(path)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 65536,
            "Startup manifest has an invalid size/type")
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        opened = os.fstat(descriptor)
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), "Manifest inode changed")
        data = os.read(descriptor, 65537)
        require(len(data) <= 65536 and not os.read(descriptor, 1), "Manifest exceeds its bound")
        value = decode(data)
    finally:
        os.close(descriptor)
    require(type(value) is dict and set(value) == {"schema", "socketPath", "peer", "workspaceRoot",
            "sharedPaths", "controllerRoots", "parentEnvironment"}
            and value["schema"] == "foldgpt.native-startup.v1", "Unexpected production startup schema")
    peer = value["peer"]
    require(type(peer) is dict and set(peer) == {"pid", "uid", "gid"}
            and all(type(peer[key]) is int and 0 < peer[key] < 2**31 for key in peer), "Invalid native identity")
    with open("/proc/self/status", encoding="ascii") as source:
        uid_line = next(line for line in source if line.startswith("Uid:"))
    require(list(map(int, uid_line.split()[1:])) == [peer["uid"]] * 4, "GNU controller kernel UID differs")
    endpoint = Path(value["socketPath"])
    private(endpoint.parent, directory=True)
    require(stat.S_ISSOCK(private(endpoint).st_mode), "Native endpoint is not a private socket")
    root = uri_path(value["workspaceRoot"])
    require(not path.is_relative_to(root) and not endpoint.is_relative_to(root), "Owner inputs overlap W")
    require(type(value["sharedPaths"]) is list and 1 <= len(value["sharedPaths"]) <= 128,
            "Unbounded shared path inventory")
    shared = set()
    for identity in value["sharedPaths"]:
        require(set(identity) == {"path", "device", "inode"}, "Unexpected shared identity")
        actual_path = uri_path(identity["path"])
        require(actual_path not in shared, "Duplicate shared path")
        shared.add(actual_path)
        actual = actual_path.stat(follow_symlinks=False)
        require((actual.st_dev, actual.st_ino) == (identity["device"], identity["inode"]),
                "GNU and native path identities differ")
    require(root in shared, "Actual workspace absent from shared path inventory")
    return value, tuple(peer[key] for key in ("pid", "uid", "gid")), root


def receive(endpoint, peer, rights=0, maximum=MAX_PACKET):
    data, controls, flags, _ = endpoint.recvmsg(maximum, socket.CMSG_SPACE(12) + socket.CMSG_SPACE(256 * 4),
                                             socket.MSG_CMSG_CLOEXEC)
    received, credentials, invalid = [], [], False
    try:
        for level, kind, control in controls:
            if level == socket.SOL_SOCKET and kind == socket.SCM_RIGHTS:
                values = array.array("i")
                values.frombytes(control[:len(control) - len(control) % values.itemsize])
                received.extend(values)
                invalid |= len(control) % values.itemsize != 0
            elif level == socket.SOL_SOCKET and kind == socket.SCM_CREDENTIALS and len(control) == 12:
                credentials.append(struct.unpack("iII", control))
            else:
                invalid = True
        require(data and not invalid and not flags & (socket.MSG_TRUNC | socket.MSG_CTRUNC)
                and credentials == [peer] and len(received) == rights, "Native packet credentials/framing differ")
        require(all(not os.get_inheritable(fd) for fd in received), "Received native FD is inheritable")
        return decode(data), received
    except BaseException:
        for descriptor in received:
            os.close(descriptor)
        raise


class FileChannel:
    def __init__(self, endpoint, peer, session, root, host):
        self.endpoint, self.peer, self.number = endpoint, peer, 1
        ready, _ = receive(endpoint, peer)
        operations = ["readFile", "writeFile", "getMetadata", "canonicalize", "readDirectory", "createDirectory"] if host else [
            "readFile", "getMetadata", "canonicalize", "readDirectory"]
        require(ready == {"type": "ready", "schema": "foldgpt.host-files.v1" if host else "foldgpt.bootstrap-files.v1",
            "sessionId": session, "workspaceRoot": root.as_uri(), "chunkBytes": CHUNK,
            "maxDataBytes": MAX_DATA, "maxPacketBytes": MAX_PACKET, "operations": operations},
            "File channel does not bind the actual exec session")

    def request(self, op, path, *, data=None, **extra):
        number = self.number
        request = {"id": number, "op": op, "path": path.as_uri(), **extra}
        if data is not None:
            request.update(bytes=len(data), chunks=(len(data) + CHUNK - 1) // CHUNK)
        self.endpoint.sendall(payload(request))
        if data is not None:
            for index, offset in enumerate(range(0, len(data), CHUNK)):
                self.endpoint.sendall(payload({"type": "chunk", "id": number, "index": index,
                    "dataBase64": base64.b64encode(data[offset:offset + CHUNK]).decode("ascii")}))
            self.endpoint.sendall(payload({"type": "commit", "id": number}))
        chunks = []
        while True:
            response, _ = receive(self.endpoint, self.peer)
            require(response.get("id") == number, "File response has a different request ID")
            if response.get("type") == "chunk":
                require(set(response) == {"type", "id", "index", "dataBase64"}
                        and response["index"] == len(chunks), "File chunk sequence differs")
                block = base64.b64decode(response["dataBase64"], validate=True)
                require(len(block) <= CHUNK and base64.b64encode(block).decode("ascii") == response["dataBase64"],
                        "File chunk is not bounded canonical base64")
                chunks.append(block)
                require(sum(map(len, chunks)) <= MAX_DATA, "File response exceeds bound")
                continue
            require(response.get("type") == "result" and set(response) == {"type", "id", "result"},
                    "Native file operation failed: " + str(response))
            self.number += 1
            if op in ("readFile", "readDirectory"):
                result = b"".join(chunks)
                require(response["result"] == {"bytes": len(result), "chunks": len(chunks)}, "Read counts differ")
                return result
            require(not chunks, "Unexpected file chunks")
            return response["result"]


class Rpc:
    def __init__(self, endpoint):
        self.stream = endpoint.makefile("rwb", buffering=0)
        self.number, self.notifications = 0, []

    def request(self, method, params):
        self.number += 1
        self.stream.write(payload({"id": self.number, "method": method, "params": params}) + b"\n")
        while True:
            line = self.stream.readline(MAX_DATA + 1)
            require(line.endswith(b"\n") and len(line) <= MAX_DATA, "Exec response is incomplete or oversized")
            response = decode(line)
            if "id" not in response:
                require(response.get("method") in {"process/output", "process/exited", "process/closed"},
                        "Unexpected exec notification")
                self.notifications.append(response)
                continue
            require(response.get("id") == self.number and "error" not in response and "result" in response,
                    "Native exec failed: " + str(response))
            return response["result"]


def qualify(path):
    require(sys.platform == "linux", "This qualification client must run in the actual GNU controller")
    libc = ctypes.CDLL(None)
    libc.gnu_get_libc_version.restype = ctypes.c_char_p
    libc_version = libc.gnu_get_libc_version().decode("ascii")
    value, peer, root = manifest(path)
    sockets, rpc, unowned = [], None, []
    report = {"schema": "foldgpt.native-production-qualification.v1", "passed": False,
        "nativeOwner": value["peer"], "controllerPid": os.getpid(), "controllerLibcUid": os.getuid(),
        "controllerGnuLibcVersion": libc_version,
        "appServerTested": False, "phoneUiTested": False, "nativeOwnerReaped": False}
    lifetime = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
    sockets.append(lifetime)
    try:
        lifetime.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        lifetime.settimeout(30)
        lifetime.connect(value["socketPath"])
        require(struct.unpack("iII", lifetime.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)) == peer,
                "Connected native owner credentials differ from its private manifest")
        lifetime.sendall(payload({"type": "acquire", "schema": SCHEMA}))
        channels, rights = receive(lifetime, peer, 3, maximum=4096)
        unowned.extend(rights)
        require(channels == {"type": "channels", "schema": SCHEMA,
            "workspaceRoot": root.as_uri(), "fdRoles": ["exec", "config", "host"]}, "Channel offer differs")
        for descriptor, kind in zip(rights, (socket.SOCK_STREAM, socket.SOCK_SEQPACKET, socket.SOCK_SEQPACKET), strict=True):
            endpoint = socket.socket(fileno=descriptor)
            sockets.append(endpoint)
            unowned.remove(descriptor)
            require(endpoint.family == socket.AF_UNIX and endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == kind
                    and endpoint.getsockname() in ("", b"") and endpoint.getpeername() in ("", b""),
                    "Transferred channel is not a direct anonymous socketpair")
            endpoint.settimeout(90)
        rpc = Rpc(sockets[1])
        initialized = rpc.request("initialize", {"clientName": "foldgpt-production-qualification"})
        session = initialized["sessionId"]
        rpc.stream.write(b'{"method":"initialized"}\n')
        ready, _ = receive(lifetime, peer, maximum=4096)
        require(ready == {"type": "ready", "schema": SCHEMA, "sessionId": session,
                         "workspaceRoot": root.as_uri()}, "Native ready differs from actual exec session")
        config = FileChannel(sockets[2], peer, session, root, False)
        host = FileChannel(sockets[3], peer, session, root, True)
        report["sessionId"] = session
        project = root / ("native-production-" + uuid.uuid4().hex)
        # Reserve exactly one new project. The subsequent native host operation
        # must see that same empty directory under the shared path contract.
        project.mkdir(mode=0o700)
        report["project"] = str(project)
        host.request("createDirectory", project / "app", recursive=False)
        host.request("createDirectory", project / "tests", recursive=False)
        program = b"def add(left, right):\n    return left + right\n\nif __name__ == '__main__':\n    print(add(19, 23))\n"
        tests = b"import unittest\nfrom app.__main__ import add\nclass Addition(unittest.TestCase):\n    def test_positive(self): self.assertEqual(add(19,23),42)\n    def test_negative(self): self.assertEqual(add(-9,4),-5)\n    def test_zero(self): self.assertEqual(add(0,0),0)\n"
        for name, contents in (("app/__main__.py", program), ("tests/test_add.py", tests)):
            target = project / name
            host.request("writeFile", target, data=contents)
            require(config.request("readFile", target) == contents and target.read_bytes() == contents,
                    "Host-written bytes differ across native config and GNU paths")
        worker = """import contextlib,io,json,os,runpy,sys,unittest,zipapp
sys.path.insert(0,os.getcwd())
suite=unittest.defaultTestLoader.discover('tests')
result=unittest.TextTestRunner(stream=sys.stderr,verbosity=2).run(suite)
assert result.wasSuccessful() and result.testsRun==3
zipapp.create_archive('app',target='native-project.pyz')
captured=io.StringIO()
with contextlib.redirect_stdout(captured): runpy.run_path('native-project.pyz',run_name='__main__')
assert captured.getvalue()=='42\\n'
record={'tests':result.testsRun,'builtOutput':captured.getvalue(),'platform':sys.platform,'machine':os.uname().machine,'uid':os.getuid(),'cwd':os.getcwd(),'python':sys.executable,'PATH':os.environ.get('PATH'),'HOME':os.environ.get('HOME'),'TMPDIR':os.environ.get('TMPDIR')}
with open('native-result.json','w',encoding='utf-8') as output: json.dump(record,output,sort_keys=True)
print(json.dumps(record,sort_keys=True))
"""
        cwd = project.as_uri()
        sandbox = {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
            {"path": {"type": "path", "path": cwd}, "access": "write"}]}, "network": "restricted"},
            "cwd": cwd, "workspaceRoots": [cwd], "windowsSandboxLevel": "disabled"}
        process_id = "production-python-" + uuid.uuid4().hex
        rpc.request("process/start", {"processId": process_id, "argv": ["python3", "-I", "-S", "-B", "-c", worker],
            "cwd": cwd, "env": {}, "envPolicy": {"inherit": "all", "ignoreDefaultExcludes": False,
            "exclude": [], "set": {}, "includeOnly": []}, "tty": False, "pipeStdin": False, "sandbox": sandbox})
        deadline, after, chunks = time.monotonic() + 90, 0, []
        while True:
            require(time.monotonic() < deadline, "Production Python did not finish before qualification deadline")
            result = rpc.request("process/read", {"processId": process_id, "afterSeq": after, "waitMs": 1000})
            chunks.extend(result["chunks"])
            after = result["nextSeq"] - 1
            if result["closed"]:
                require(result["exited"] and result["exitCode"] == 0 and result["failure"] is None,
                        "Native worker did not prove clean completion: " + str(result))
                break
        stdout = b"".join(base64.b64decode(chunk["chunk"], validate=True) for chunk in chunks if chunk["stream"] == "stdout")
        stderr = b"".join(base64.b64decode(chunk["chunk"], validate=True) for chunk in chunks if chunk["stream"] == "stderr")
        report["workerStderr"] = stderr.decode("utf-8", errors="strict")
        native = decode(stdout)
        require(native["platform"] == "android" and native["machine"] == "aarch64" and native["uid"] == peer[1]
                and native["tests"] == 3 and native["builtOutput"] == "42\n" and native["cwd"] == str(project),
                "Actual Python result differs from native production identity/workload")
        for name in ("PATH", "HOME", "TMPDIR"):
            require(native[name] == value["parentEnvironment"][name], "Native inheritance differs from actual startup snapshot")
        material = host.request("readFile", project / "native-result.json")
        require(decode(material) == native and (project / "native-result.json").read_bytes() == material,
                "Actual native output differs from material file across shared paths")
        built = host.request("readFile", project / "native-project.pyz")
        require(built == (project / "native-project.pyz").read_bytes(), "Built archive differs across real filesystems")
        report.update(passed=True, worker=native, zipappSha256=hashlib.sha256(built).hexdigest(),
                      directChannelsAuthenticated=True, nativeProcessClosed=True, lifetimeClosedAfterWork=True)
    except BaseException as error:
        report["error"] = type(error).__name__ + ": " + str(error)
    finally:
        lifetime.close()
        if rpc is not None:
            rpc.stream.close()
        for endpoint in sockets:
            endpoint.close()
        for descriptor in unowned:
            os.close(descriptor)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    try:
        result = qualify(args.manifest)
    except BaseException as error:
        result = {"schema": "foldgpt.native-production-qualification.v1", "passed": False,
                  "error": type(error).__name__ + ": " + str(error), "nativeOwnerReaped": False}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True), flush=True)
    return 0 if result["passed"] else 70


if __name__ == "__main__":
    sys.exit(main())
