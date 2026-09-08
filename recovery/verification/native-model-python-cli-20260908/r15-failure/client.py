"""Real controller qualification over the production startup's three channels.

Consumes one fresh startup manifest exactly as the engine does. It does not
launch a service, replace an APK, create a fake owner, or certify Java cleanup.
Run in the actual GNU/PRoot controller or Bionic Python under the app UID. The launcher
must retain its independent service wait/cleanup receipt after this exits.
"""
import argparse
import array
import base64
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import struct
import sys
import time
import uuid
from urllib.parse import unquote, urlsplit


def require(condition, message):
    if not condition:
        raise ValueError(message)


def decode(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate JSON field")
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite JSON")))


def canonical_uri(value):
    uri = urlsplit(value)
    require(uri.scheme == "file" and not uri.netloc and not uri.query and not uri.fragment,
            "Expected a canonical local file URI")
    path = Path(unquote(uri.path, errors="strict"))
    require(path.is_absolute() and path.as_uri() == value and path.resolve(strict=True) == path,
            "Noncanonical shared path")
    return path


def private(path, *, directory=False):
    require(path.is_absolute() and path.resolve(strict=True) == path, "Private path has an alias")
    info = path.stat(follow_symlinks=False)
    # PRoot substitutes libc/stat UID together. Kernel UID is checked separately.
    require(info.st_uid == os.geteuid() and not info.st_mode & 0o077, "Path is not owner-private")
    if directory:
        require(stat.S_ISDIR(info.st_mode), "Private parent must be an ordinary directory")
    return info


def read_manifest(path):
    private(path.parent, directory=True)
    info = private(path)
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= 65536,
            "Manifest must be bounded and ordinary")
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        opened = os.fstat(fd)
        require((opened.st_dev, opened.st_ino) == (info.st_dev, info.st_ino), "Manifest identity changed")
        chunks, consumed = [], 0
        while data := os.read(fd, 65537 - consumed):
            chunks.append(data)
            consumed += len(data)
            require(consumed <= 65536, "Manifest exceeded its bound")
        value = decode(b"".join(chunks))
        after = os.fstat(fd)
        require((opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns)
                == (after.st_size, after.st_mtime_ns, after.st_ctime_ns), "Manifest changed while reading")
    finally:
        os.close(fd)
    require(type(value) is dict and set(value) == {"schema", "socketPath", "peer", "workspaceRoot",
        "sharedPaths", "controllerRoots", "parentEnvironment", "hostSchema"}
        and value["schema"] == "foldgpt.native-startup.v1" and value["hostSchema"] == "foldgpt.host.v2",
        "Fresh exact production v2 manifest required")
    peer = value["peer"]
    require(type(peer) is dict and set(peer) == {"pid", "uid", "gid"}
            and all(type(number) is int and 0 < number < 2**31 for number in peer.values()),
            "Invalid actual owner identity")
    with open("/proc/self/status", encoding="ascii") as source:
        status = dict(line.split(":", 1) for line in source if ":" in line)
    for field, name in (("Uid", "uid"), ("Gid", "gid")):
        require(list(map(int, status[field].split())) == [peer[name]] * 4, "Controller kernel identity differs")
    endpoint = Path(value["socketPath"])
    private(endpoint.parent, directory=True)
    require(stat.S_ISSOCK(private(endpoint).st_mode), "Native endpoint must be a private socket")
    root = canonical_uri(value["workspaceRoot"])
    require(not path.is_relative_to(root) and not endpoint.is_relative_to(root), "Native owner inputs overlap W")
    identities = value["sharedPaths"]
    require(type(identities) is list and 1 <= len(identities) <= 128, "Unbounded shared path inventory")
    seen = set()
    for identity in identities:
        require(type(identity) is dict and set(identity) == {"path", "device", "inode"}, "Unknown shared identity")
        shared = canonical_uri(identity["path"])
        require(shared not in seen, "Duplicate shared identity")
        seen.add(shared)
        actual = shared.stat(follow_symlinks=False)
        require((actual.st_dev, actual.st_ino) == (identity["device"], identity["inode"]),
                "Controller and native owner refer to different files")
    require(root in seen, "Workspace identity absent")
    environment = value["parentEnvironment"]
    require(type(environment) is dict and len(environment) <= 128
            and all(type(k) is str and k and "=" not in k and "\0" not in k
                    and type(v) is str and "\0" not in v for k, v in environment.items()),
            "Invalid native environment snapshot")
    return value


class Client:
    def __init__(self, manifest):
        self.manifest = manifest
        self.peer = tuple(manifest["peer"][key] for key in ("pid", "uid", "gid"))
        self.sockets, self.rpc, self.sequence = [], None, 0
        self.exec_sequence, self.exec_notifications = 1, 0

    def receive(self, endpoint, count=0):
        packet, controls, flags, _ = endpoint.recvmsg(65536, socket.CMSG_SPACE(12) + socket.CMSG_SPACE(1024),
                                                    socket.MSG_CMSG_CLOEXEC)
        descriptors, credentials = [], []
        try:
            for level, kind, value in controls:
                require(level == socket.SOL_SOCKET, "Foreign socket control")
                if kind == socket.SCM_RIGHTS:
                    rights = array.array("i")
                    rights.frombytes(value[:len(value) - len(value) % rights.itemsize])
                    descriptors.extend(rights)
                elif kind == socket.SCM_CREDENTIALS:
                    require(len(value) == 12, "Malformed credential bytes")
                    credentials.append(struct.unpack("iII", value))
                else:
                    raise ValueError("Unknown socket control")
            require(packet and flags & ~socket.MSG_CMSG_CLOEXEC == 0
                    and credentials == [self.peer] and len(descriptors) == count,
                    "Production reply credentials, descriptors or packet bounds differ")
            require(all(not os.get_inheritable(fd) for fd in descriptors), "Received descriptor was inheritable")
            data = decode(packet)
            return data, descriptors
        except BaseException:
            for descriptor in descriptors:
                os.close(descriptor)
            raise

    @staticmethod
    def send(endpoint, value):
        packet = json.dumps(value, separators=(",", ":")).encode()
        require(len(packet) <= 65536 and endpoint.send(packet) == len(packet), "Incomplete host request packet")

    def connect(self):
        endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.sockets.append(endpoint)
        endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        endpoint.settimeout(30)
        endpoint.connect(self.manifest["socketPath"])
        require(struct.unpack("iII", endpoint.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)) == self.peer,
                "Rendezvous kernel owner differs from startup manifest")
        self.send(endpoint, {"type": "acquire", "schema": "foldgpt.native-runtime.v1"})
        offered, rights = self.receive(endpoint, 3)
        require(offered == {"type": "channels", "schema": "foldgpt.native-runtime.v1",
            "workspaceRoot": self.manifest["workspaceRoot"], "fdRoles": ["exec", "config", "host"]},
            "Production channels differ")
        channels = [socket.socket(fileno=descriptor) for descriptor in rights]
        self.sockets.extend(channels)
        for channel in channels:
            channel.settimeout(30)
        self.rpc = channels[0].makefile("rwb", buffering=0)
        self.rpc.write(b'{"id":1,"method":"initialize","params":{"clientName":"real-production-human-qualification"}}\n')
        initialized = decode(self.rpc.readline(65536))
        session = initialized["result"]["sessionId"]
        self.rpc.write(b'{"method":"initialized"}\n')
        ready, _ = self.receive(endpoint)
        require(ready == {"type": "ready", "schema": "foldgpt.native-runtime.v1",
            "workspaceRoot": self.manifest["workspaceRoot"], "sessionId": session}, "Production session differs")
        config, self.host = channels[1:]
        config_ready, _ = self.receive(config)
        host_ready, _ = self.receive(self.host)
        require(config_ready["sessionId"] == session and host_ready["sessionId"] == session
                and host_ready["workspaceRoot"] == self.manifest["workspaceRoot"]
                and host_ready["schema"] == "foldgpt.host.v2", "Owner did not select real human v2")
        return {"sessionId": session, "hostReady": host_ready}

    def request(self, op, *, upload=None, **parameters):
        self.sequence += 1
        number = self.sequence
        if upload is not None:
            parameters.update(bytes=len(upload), chunks=(len(upload) + 32767) // 32768)
        self.send(self.host, {"id": number, "op": op, **parameters})
        if upload is not None:
            for index, offset in enumerate(range(0, len(upload), 32768)):
                self.send(self.host, {"type": "chunk", "id": number, "index": index,
                    "dataBase64": base64.b64encode(upload[offset:offset + 32768]).decode()})
            self.send(self.host, {"type": "commit", "id": number})
        output, chunks = bytearray(), 0
        while True:
            response, _ = self.receive(self.host)
            require(response["id"] == number, "Response does not own this request")
            if response["type"] == "error":
                raise RuntimeError(response["error"]["message"])
            if response["type"] == "chunk":
                require(response["index"] == chunks, "File chunk order differs")
                chunks += 1
                output.extend(base64.b64decode(response["dataBase64"], validate=True))
            else:
                require(response["type"] == "result", "Unknown host response")
                return response["result"], bytes(output)

    def process(self, command, environment, *, stdin=None, terminate_on_output=False):
        started, _ = self.request("processStart", command=command, cwd="/", environment=environment,
                                  pipeStdin=stdin is not None)
        key = started["processId"]
        if stdin is not None:
            for offset in range(0, len(stdin), 32768):
                self.request("processWrite", processId=key,
                    dataBase64=base64.b64encode(stdin[offset:offset + 32768]).decode(), closeStdin=False)
            self.request("processWrite", processId=key, dataBase64="", closeStdin=True)
        streams = {"stdout": bytearray(), "stderr": bytearray()}
        events, terminated = [], False
        while not events or events[-1]["type"] != "closed":
            result, _ = self.request("processRead", processId=key)
            event = result["event"]
            require(event["seq"] == len(events) + 1, "Native process event sequence differs")
            events.append({key: value for key, value in event.items() if key != "dataBase64"})
            if event["type"] == "output":
                streams[event["stream"]].extend(base64.b64decode(event["dataBase64"], validate=True))
                if terminate_on_output and not terminated:
                    self.request("processTerminate", processId=key)
                    terminated = True
        require(events[-1].get("failure", "missing") is None, "Native owner did not close this worker cleanly")
        return {"command": command, "cwd": "/", "events": events, "terminationRequested": terminated,
                "streams": {key: {"bytes": len(value), "sha256": hashlib.sha256(value).hexdigest(),
                                  **({"diagnosticUtf8": bytes(value[:4096]).decode("utf-8", "backslashreplace"),
                                      "diagnosticBase64": base64.b64encode(value[:4096]).decode(),
                                      "diagnosticTruncated": len(value) > 4096} if key == "stderr" else {})}
                            for key, value in streams.items()}}, {key: bytes(value) for key, value in streams.items()}

    def exec_request(self, method, parameters):
        """Use the authenticated ExecServer channel already initialized above."""
        self.exec_sequence += 1
        number = self.exec_sequence
        encoded = json.dumps({"id": number, "method": method, "params": parameters},
                             separators=(",", ":")).encode() + b"\n"
        require(self.rpc.write(encoded) == len(encoded), "Incomplete model RPC request")
        while True:
            line = self.rpc.readline(16777217)
            require(line.endswith(b"\n") and len(line) <= 16777216,
                    "Incomplete or oversized model RPC response")
            response = decode(line)
            if "id" not in response:
                require(response.get("method") in {"process/output", "process/exited", "process/closed"},
                        "Unknown model process notification")
                self.exec_notifications += 1
                continue
            require(response.get("id") == number, "Model response belongs to another request")
            if "error" in response:
                raise RuntimeError("Model " + method + " refused: " + json.dumps(response["error"]))
            require("result" in response, "Model RPC has no result")
            return response["result"]

    def model_process(self, record, cwd, command):
        """Run actual model authority with its complete existing managed policy.

        Fixed qualification programs produce small outputs. Preserve complete
        stdout/stderr up to 64 KiB each, plus counts/hash/truncation for all bytes.
        No model result is synthesized from a human process or a file read.
        """
        uri = cwd.as_uri()
        sandbox = {"permissions": {"type": "managed", "file_system": {
            "type": "restricted", "entries": [{"path": {"type": "path", "path": uri}, "access": "write"}]},
            "network": "restricted"}, "cwd": uri, "workspaceRoots": [uri], "windowsSandboxLevel": "disabled"}
        key = "model-cli-" + uuid.uuid4().hex
        record.update(command=command, cwd=str(cwd), processId=key, channel="exec",
                      admitted=False, closed=False, passed=False)
        streams = {name: {"count": 0, "digest": hashlib.sha256(), "data": bytearray()}
                   for name in ("stdout", "stderr")}
        after, chunks = 0, 0
        try:
            record["start"] = self.exec_request("process/start", {"processId": key, "argv": command,
                "cwd": uri, "env": {}, "envPolicy": {"inherit": "all", "ignoreDefaultExcludes": False,
                "exclude": [], "set": {}, "includeOnly": []}, "tty": False, "pipeStdin": False, "sandbox": sandbox})
            record["admitted"] = True
            deadline = time.monotonic() + 90
            while True:
                require(time.monotonic() < deadline, "Actual model Python qualification deadline exceeded")
                result = self.exec_request("process/read", {"processId": key, "afterSeq": after, "waitMs": 1000})
                record["result"] = {name: value for name, value in result.items() if name != "chunks"}
                for chunk in result["chunks"]:
                    require(type(chunk["seq"]) is int and chunk["seq"] > after
                            and chunk["stream"] in streams, "Model output order or stream differs")
                    after = chunk["seq"]
                    data = base64.b64decode(chunk["chunk"], validate=True)
                    require(base64.b64encode(data).decode() == chunk["chunk"], "Noncanonical model output bytes")
                    capture = streams[chunk["stream"]]
                    capture["count"] += len(data)
                    capture["digest"].update(data)
                    capture["data"].extend(data[:max(0, 65536 - len(capture["data"]))])
                    chunks += 1
                require(type(result["nextSeq"]) is int and result["nextSeq"] > after,
                        "Model output cursor moved backwards")
                after = result["nextSeq"] - 1
                if result["closed"]:
                    record["closed"] = True
                    require(result["exited"] and result["failure"] is None,
                            "Model owner did not prove clean completion: " + str(record["result"]))
                    break
        except BaseException as error:
            record["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            record["outputChunks"] = chunks
            record["streams"] = {name: {"bytes": item["count"], "sha256": item["digest"].hexdigest(),
                "diagnosticUtf8": bytes(item["data"]).decode("utf-8", "backslashreplace"),
                "diagnosticBase64": base64.b64encode(item["data"]).decode(),
                "diagnosticTruncated": item["count"] > len(item["data"])} for name, item in streams.items()}
        return {name: bytes(item["data"]) for name, item in streams.items()}

    def close(self):
        if self.rpc is not None:
            self.rpc.close()
        for endpoint in self.sockets:
            endpoint.close()


def qualify(startup):
    manifest = read_manifest(startup)
    workspace = canonical_uri(manifest["workspaceRoot"])
    directory = workspace / (".host-v2-qualification-" + uuid.uuid4().hex)
    client = Client(manifest)
    report = {"schema": "foldgpt.production-host-qualification.v1", "passed": False,
              "officialEditorQualified": False, "javaCleanupReceiptRequired": True,
              "controllerPid": os.getpid(), "controllerUid": os.getuid(),
              "startupOwner": manifest["peer"], "directory": str(directory), "cases": [],
              "humanPassed": False, "modelPythonPassed": False, "modelCases": []}
    try:
        report["connection"] = client.connect()
        client.request("createDirectory", path=directory.as_uri(), recursive=False)
        small = directory / "hello.py"
        source = b"def add(a, b):\n    return a + b\n\nassert add(20, 22) == 42\nprint('real native human Python pass')\n"
        client.request("writeFile", path=small.as_uri(), upload=source)
        environment = dict(manifest["parentEnvironment"])
        def execute(argv, **kwargs):
            record, streams = client.process(argv, environment, **kwargs)
            report["cases"].append(record)
            return record, streams
        def clean_exit(record):
            require([event["exitCode"] for event in record["events"] if event["type"] == "exited"] == [0],
                    "Actual process did not exit zero")
        record, streams = execute(["cat", str(small)])
        clean_exit(record)
        require(streams == {"stdout": source, "stderr": b""}, "Real editor cat read differs")
        payload = bytes(range(256)) * 8193
        large = directory / "streamed.bin"
        record, streams = execute(["sh", "-c", 'cat > "$1"', "sh", str(large)], stdin=payload)
        clean_exit(record)
        require(streams == {"stdout": b"", "stderr": b""}, "Real editor shell save output differs")
        _, actual = client.request("readFile", path=large.as_uri())
        require(actual == payload, "Native host file authority differs from real shell bytes")
        record, streams = execute(["cat", str(large)])
        clean_exit(record)
        require(streams == {"stdout": payload, "stderr": b""}, "Real editor cat streamed read differs")
        record, streams = execute(["python", "-I", "-S", "-B", str(small)])
        clean_exit(record)
        require(streams == {"stdout": b"real native human Python pass\n", "stderr": b""}, "Real Python output differs")
        record, streams = execute(["cat", str(startup)])
        require(not streams["stdout"] and any(event["exitCode"] != 0 for event in record["events"]
                                             if event["type"] == "exited"), "Outside-W read was not refused")
        record, streams = execute(["sh", "-c", "sleep 20 & printf ready; wait"], terminate_on_output=True)
        require(streams["stdout"] == b"ready" and record["terminationRequested"], "Real descendant cancel differs")
        report["humanPassed"] = True
        project = directory / "model-python"
        app, tests = project / "app", project / "tests"
        for target in (project, app, tests):
            client.request("createDirectory", path=target.as_uri(), recursive=False)
        source = b"def add(a, b):\n    return a + b\n\nif __name__ == '__main__':\n    print(add(20, 22))\n"
        test_source = (b"import unittest\nfrom app.__main__ import add\nclass Addition(unittest.TestCase):\n"
                       b"    def test_positive(self): self.assertEqual(add(20,22),42)\n"
                       b"    def test_negative(self): self.assertEqual(add(-9,4),-5)\n"
                       b"    def test_zero(self): self.assertEqual(add(0,0),0)\n")
        for target, data in ((app / "__main__.py", source), (app / "__init__.py", b""),
                             (tests / "test_add.py", test_source)):
            client.request("writeFile", path=target.as_uri(), upload=data)
        archive = project / "model-project.pyz"
        commands = [
            ("script", ["python3", "-I", "-S", "-B", str(app / "__main__.py")]),
            ("unittest", ["python3", "-S", "-B", "-m", "unittest", "discover", "-s", "tests", "-v"]),
            ("zipapp-build", ["python3", "-I", "-S", "-B", "-m", "zipapp", str(app), "-o", str(archive)]),
            ("zipapp-execute", ["python3", "-I", "-S", "-B", str(archive)]),
        ]
        for name, command in commands:
            record = {"case": name}
            report["modelCases"].append(record)
            streams = client.model_process(record, project, command)
            record["passed"] = record["result"]["exitCode"] == 0 and all(
                not stream["diagnosticTruncated"] for stream in record["streams"].values())
            if name in {"script", "zipapp-execute"}:
                record["passed"] &= streams == {"stdout": b"42\n", "stderr": b""}
            elif name == "unittest":
                record["passed"] &= (streams["stdout"] == b"" and b"Ran 3 tests in " in streams["stderr"]
                    and streams["stderr"].endswith(b"\nOK\n"))
            else:
                record["passed"] &= streams == {"stdout": b"", "stderr": b""}
                if record["passed"]:
                    _, built = client.request("readFile", path=archive.as_uri())
                    record["archive"] = {"bytes": len(built), "sha256": hashlib.sha256(built).hexdigest()}
                    record["passed"] &= bool(built)
        report["modelPythonPassed"] = all(case["passed"] for case in report["modelCases"])
        report["execNotifications"] = client.exec_notifications
        report["passed"] = report["humanPassed"] and report["modelPythonPassed"]
        if not report["passed"]:
            report["error"] = {"type": "ModelPythonQualificationFailed",
                "message": "At least one real model Python CLI command failed; inspect modelCases"}
    except BaseException as error:
        report["error"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        client.close()
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("startup", type=Path)
    args = parser.parse_args()
    try:
        result = qualify(args.startup)
    except BaseException as error:
        result = {"schema": "foldgpt.production-host-qualification.v1", "passed": False,
                  "officialEditorQualified": False, "javaCleanupReceiptRequired": True,
                  "error": {"type": type(error).__name__, "message": str(error)}}
    print(json.dumps(result, separators=(",", ":")), flush=True)
    sys.exit(0 if result["passed"] else 1)
