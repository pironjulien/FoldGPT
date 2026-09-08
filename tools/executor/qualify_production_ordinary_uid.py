"""Real ordinary-UID model qualification through a fresh production acquisition.

Runs as the real GNU controller; only authenticated native model RPC creates or
executes project content. The existing config and human channels independently
read back actual bytes. This driver never starts Android, installs a package,
changes runtime selection, or claims a successful official editor conversation.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import socket
import struct
import sys
import time
import uuid

_spec = importlib.util.spec_from_file_location("foldgpt_qualification_host_v2",
    Path(__file__).with_name("qualify_production_host_v2.py"))
_host = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_host)
require, decode, path_uri = _host.require, _host.decode, _host.path_uri


class ModelRpcError(RuntimeError):
    def __init__(self, method, error):
        self.error = error
        super().__init__("Model " + method + " refused: " + json.dumps(error))


class Client(_host.Client):
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
            "Production acquisition channels differ")
        channels = [socket.socket(fileno=fd) for fd in rights]
        self.sockets.extend(channels)
        for channel in channels:
            channel.settimeout(30)
        self.rpc = channels[0].makefile("rwb", buffering=0)
        initialize = b'{"id":1,"method":"initialize","params":{"clientName":"real-production-ordinary-uid-qualification"}}\n'
        require(self.rpc.write(initialize) == len(initialize), "Incomplete production initialize")
        response = decode(self.rpc.readline(65536))
        require(response.get("id") == 1 and "result" in response, "Production initialize failed")
        session = response["result"]["sessionId"]
        self.rpc.write(b'{"method":"initialized"}\n')
        ready, _ = self.receive(endpoint)
        require(ready == {"type": "ready", "schema": "foldgpt.native-runtime.v1",
            "workspaceRoot": self.manifest["workspaceRoot"], "sessionId": session}, "Production session differs")
        self.config, self.host = channels[1:]
        config_ready, _ = self.receive(self.config)
        host_ready, _ = self.receive(self.host)
        require(config_ready.get("sessionId") == session and host_ready.get("sessionId") == session
                and config_ready.get("schema") == "foldgpt.bootstrap-files.v1"
                and config_ready.get("discoveryRoot") == self.manifest["workspaceRoot"]
                and host_ready.get("schema") == "foldgpt.host.v2"
                and host_ready.get("workspaceRoot") == self.manifest["workspaceRoot"],
                "Read-only config or human v2 authority differs")
        self.config_sequence = 0
        return {"sessionId": session, "environmentInfo": response["result"]["environmentInfo"],
                "hostReady": host_ready, "configReady": config_ready}

    def config_read(self, path):
        self.config_sequence += 1
        number = self.config_sequence
        self.send(self.config, {"id": number, "op": "readFile", "path": path_uri(path)})
        output, chunks = bytearray(), 0
        while True:
            response, _ = self.receive(self.config)
            require(response.get("id") == number, "Config response correlation differs")
            if response.get("type") == "error":
                raise RuntimeError("Independent config read failed: " + json.dumps(response["error"]))
            if response.get("type") == "chunk":
                require(response.get("index") == chunks, "Config read chunk order differs")
                output.extend(base64.b64decode(response["dataBase64"], validate=True))
                chunks += 1
                require(len(output) <= 16777216, "Independent config read exceeds its limit")
            else:
                require(response.get("type") == "result"
                        and response.get("result") == {"bytes": len(output), "chunks": chunks},
                        "Independent config read receipt differs")
                return bytes(output)

    def exec_request(self, method, parameters):
        self.exec_sequence += 1
        number = self.exec_sequence
        packet = json.dumps({"id": number, "method": method, "params": parameters},
            separators=(",", ":")).encode() + b"\n"
        require(self.rpc.write(packet) == len(packet), "Incomplete ordinary model RPC")
        while True:
            line = self.rpc.readline(16777217)
            require(line.endswith(b"\n") and len(line) <= 16777216, "Incomplete or oversized ordinary model reply")
            reply = decode(line)
            if "id" not in reply:
                require(reply.get("method") in {"process/output", "process/exited", "process/closed"},
                        "Unknown ordinary model notification")
                self.exec_notifications += 1
                continue
            require(reply.get("id") == number, "Ordinary model reply correlation differs")
            if "error" in reply:
                raise ModelRpcError(method, reply["error"])
            require(type(reply.get("result")) is dict, "Ordinary model RPC did not return an object")
            return reply["result"]

    def direct_process(self, record, cwd, command, *, null_context=False):
        key = "ordinary-cli-" + uuid.uuid4().hex
        params = {"processId": key, "argv": command, "cwd": path_uri(cwd), "env": {},
            "envPolicy": {"inherit": "all", "ignoreDefaultExcludes": False,
                "exclude": [], "set": {}, "includeOnly": []}, "tty": False, "pipeStdin": False}
        if null_context:
            params["sandbox"] = None
        record.update(command=command, cwd=str(cwd), processId=key, channel="exec",
            sandboxField="null" if null_context else "absent", admitted=False, closed=False, passed=False)
        streams = {name: bytearray() for name in ("stdout", "stderr")}
        cursor = 0
        try:
            record["start"] = self.exec_request("process/start", params)
            require(record["start"] == {"processId": key, "sandboxType": "none"},
                    "Ordinary launch must report its actual no-outer-sandbox type")
            record["admitted"] = True
            deadline = time.monotonic() + 90
            while True:
                require(time.monotonic() < deadline, "Ordinary native process deadline exceeded")
                result = self.exec_request("process/read", {"processId": key, "afterSeq": cursor, "waitMs": 1000})
                record["result"] = {name: value for name, value in result.items() if name != "chunks"}
                for chunk in result["chunks"]:
                    require(type(chunk["seq"]) is int and chunk["seq"] > cursor and chunk["stream"] in streams,
                            "Ordinary output order or stream differs")
                    data = base64.b64decode(chunk["chunk"], validate=True)
                    require(base64.b64encode(data).decode() == chunk["chunk"], "Noncanonical ordinary output")
                    streams[chunk["stream"]].extend(data)
                    require(len(streams[chunk["stream"]]) <= 65536, "Qualification output exceeded its exact capture bound")
                    cursor = chunk["seq"]
                require(type(result["nextSeq"]) is int and result["nextSeq"] > cursor,
                        "Ordinary model output cursor moved backwards")
                cursor = result["nextSeq"] - 1
                if result["closed"]:
                    record["closed"] = True
                    require(result["exited"] and result["failure"] is None
                            and result["exitCode"] == 0 and result["sandboxDenied"] is False,
                            "Ordinary native command failed: " + json.dumps(record["result"]))
                    break
        except BaseException as error:
            record["error"] = {"type": type(error).__name__, "message": str(error)}
            raise
        finally:
            record["streams"] = {name: {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
                "diagnosticUtf8": bytes(data).decode("utf-8", "backslashreplace"),
                "diagnosticBase64": base64.b64encode(data).decode(), "diagnosticTruncated": False}
                for name, data in streams.items()}
        return {name: bytes(data) for name, data in streams.items()}


def qualify(startup, *, expected_platform="android"):
    manifest = _host.read_manifest(startup)
    workspace = _host.canonical_uri(manifest["workspaceRoot"])
    project = workspace / (".ordinary-uid-qualification-" + uuid.uuid4().hex)
    client = Client(manifest)
    report = {"schema": "foldgpt.production-ordinary-uid-qualification.v1", "passed": False,
        "officialEditorQualified": False, "javaCleanupReceiptRequired": True,
        "controllerPid": os.getpid(), "controllerUid": os.getuid(), "startupOwner": manifest["peer"],
        "directory": str(project), "modelFileCases": [], "modelCases": [], "independentReads": []}
    try:
        require(expected_platform in {"android", "linux"}, "Expected platform must be Android or explicit host Linux")
        report["connection"] = client.connect()
        info = client.exec_request("environment/info", {})
        report["environmentInfo"] = info
        require(info.get("platformOs") == expected_platform and info["shell"]["name"] == "bash",
                "Actual selected native environment platform or shell differs")
        shell = info["shell"]["path"]
        require(type(shell) is str and shell.startswith("/"), "Native environment must advertise its installed Bash path")
        uri = path_uri(project)
        disabled = {"permissions": {"type": "disabled"}, "cwd": uri,
                    "workspaceRoots": [uri], "windowsSandboxLevel": "disabled"}
        try:
            client.exec_request("fs/getMetadata", {"path": uri})
        except ModelRpcError as error:
            require(error.error.get("code") == -32004, "Fresh project absence was not proven")
        else:
            raise ValueError("Reserved qualification project already exists")

        def filesystem(method, parameters, label):
            value = client.exec_request(method, parameters)
            report["modelFileCases"].append({"method": method, "case": label,
                "context": "absent" if "sandbox" not in parameters else "null" if parameters["sandbox"] is None else "disabled",
                "path": parameters.get("path"), "passed": True})
            return value

        for target in (project, project / "app", project / "tests"):
            filesystem("fs/createDirectory", {"path": path_uri(target), "recursive": False}, "create-reserved-project")
        sources = {
            "app/addition.py": b"def addition(a, b):\n    return a + b\n",
            "app/__init__.py": b"",
            "app/__main__.py": b"from addition import addition\nprint(addition(20, 22))\n",
            "tests/test_addition.py": (b"import unittest\nfrom app.addition import addition\n"
                b"class Addition(unittest.TestCase):\n"
                b"    def test_20_plus_22(self): self.assertEqual(addition(20, 22), 42)\n"
                b"    def test_minus_2_plus_2(self): self.assertEqual(addition(-2, 2), 0)\n"
                b"    def test_1_plus_2(self): self.assertEqual(addition(1, 2), 3)\n"),
        }
        for index, (name, data) in enumerate(sources.items()):
            context = None if index % 2 == 0 else disabled
            filesystem("fs/writeFile", {"path": path_uri(project / name),
                "dataBase64": base64.b64encode(data).decode(), "sandbox": context}, "create-python-source")
            value = filesystem("fs/readFile", {"path": path_uri(project / name), "sandbox": disabled}, "read-model-source")
            require(base64.b64decode(value["dataBase64"], validate=True) == data, "Model readback differs from actual source")
        canonical = filesystem("fs/canonicalize", {"path": uri, "sandbox": None}, "canonical-project")
        require(canonical == {"path": uri}, "Canonical native model project differs")

        identity_code = ("import json,os,platform,sys; print(json.dumps({'platform':sys.platform,"
            "'machine':platform.machine(),'uid':os.getuid(),'pid':os.getpid(),'cwd':os.getcwd(),"
            "'executable':sys.executable}))")
        commands = (
            ("bash-login-native-identity", [shell, "-lc", "python3 -I -B -c " + shlex.quote(identity_code)], False),
            ("bash-nonlogin-native-identity", [shell, "-c", "python3 -I -B -c " + shlex.quote(identity_code)], True),
            ("three-unittest", [shell, "-lc", "python3 -B -m unittest discover -s tests -v"], False),
            ("zipapp-build", ["python3", "-I", "-B", "-m", "zipapp", str(project / "app"), "-o", str(project / "addition.pyz")], True),
            ("zipapp-execute", ["python3", "-I", "-B", str(project / "addition.pyz")], False),
        )
        for name, command, null_context in commands:
            record = {"case": name}
            report["modelCases"].append(record)
            streams = client.direct_process(record, project, command, null_context=null_context)
            if name.startswith("bash-"):
                require(streams["stderr"] == b"", "Native Bash identity probe emitted a startup error")
                identity = decode(streams["stdout"])
                require(identity["platform"] == expected_platform and identity["uid"] == manifest["peer"]["uid"]
                        and identity["cwd"] == str(project) and identity["uid"] != 0
                        and type(identity["pid"]) is int and identity["pid"] > 0,
                        "Actual Bash/Python worker identity or cwd differs")
                if expected_platform == "android":
                    require(identity["machine"] == "aarch64", "Production Python is not running on Android ARM64")
                record["workerIdentity"] = identity
            elif name == "three-unittest":
                require(streams["stdout"] == b"" and b"Ran 3 tests in " in streams["stderr"]
                        and streams["stderr"].endswith(b"\nOK\n"), "Three real unittest passes are missing")
                for test in (b"test_20_plus_22", b"test_minus_2_plus_2", b"test_1_plus_2"):
                    require(test in streams["stderr"], "A requested unittest case was not run")
            elif name == "zipapp-build":
                require(streams == {"stdout": b"", "stderr": b""}, "Native zipapp build emitted errors")
            else:
                require(streams == {"stdout": b"42\n", "stderr": b""}, "Built native zipapp did not print exactly 42")
            record["passed"] = True

        archive = project / "addition.pyz"
        value = filesystem("fs/readFile", {"path": path_uri(archive), "sandbox": None}, "model-built-archive")
        archive_data = base64.b64decode(value["dataBase64"], validate=True)
        require(archive_data.startswith(b"PK") and len(archive_data) > 0, "Native build produced no actual ZIP archive")
        for name, expected in (*sources.items(), ("addition.pyz", archive_data)):
            path = project / name
            config_data = client.config_read(path)
            receipt, host_data = client.request("readFile", path=path_uri(path))
            require(config_data == host_data == expected, "Config/human/model channels disagree on real project bytes")
            report["independentReads"].append({"path": str(path), "bytes": len(expected),
                "sha256": hashlib.sha256(expected).hexdigest(), "configMatched": True, "humanMatched": True,
                "humanReceipt": receipt})
        report["execNotifications"] = client.exec_notifications
        report["passed"] = all(case["passed"] for case in report["modelCases"])
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
        result = {"schema": "foldgpt.production-ordinary-uid-qualification.v1", "passed": False,
            "officialEditorQualified": False, "javaCleanupReceiptRequired": True,
            "error": {"type": type(error).__name__, "message": str(error)}}
    print(json.dumps(result, separators=(",", ":")), flush=True)
    raise SystemExit(0 if result["passed"] else 1)
