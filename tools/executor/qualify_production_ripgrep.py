"""Exercise real installed ripgrep through the ordinary production channels.

Only model RPC creates the reserved project and starts native workers. Config
and human channels independently read its bytes. No package installation, ADB,
runtime selection, fake rg, or claim of an official editor conversation occurs.
"""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import time
import uuid


_spec = importlib.util.spec_from_file_location("foldgpt_rg_ordinary_client",
    Path(__file__).with_name("qualify_production_ordinary_uid.py"))
_ordinary = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ordinary)
require, decode, path_uri = _ordinary.require, _ordinary.decode, _ordinary.path_uri

SOURCES = {
    ".gitignore": b"ignored/\n*.log\n",
    "README.md": b"Native search qualification project.\n",
    "data/items.csv": "name,amount\ncafé,42\ntea,17\n".encode(),
    "notes/café.txt": "café naïve ☕\nprix=42 EUR\n".encode(),
    "notes/plain.txt": b"alpha\nprix=17 EUR\n",
    "notes/debug.log": "café diagnostic\nprix=999 EUR\n".encode(),
    "ignored/secret.txt": "café ignored\nprix=999 EUR\n".encode(),
    "samples/raw.bin": b"\x00\xffkeep-native-bytes\r\n",
}


def cases():
    """Inputs and expected semantics shared with tests invoking a real host rg."""
    stable = ["--no-config", "--color", "never", "--path-separator", "/"]
    return [
        {"case": "direct-version", "argv": ["--version"], "exitCode": 0},
        {"case": "pcre2-jit-version", "argv": ["--pcre2-version"], "exitCode": 0},
        {"case": "files-respect-gitignore", "argv": [*stable, "--files", "--sort", "path", "."], "exitCode": 0},
        {"case": "unicode-search-respects-gitignore", "argv": [*stable, "--sort", "path", "--no-heading",
            "--with-filename", "-n", "café", "."], "exitCode": 0},
        {"case": "explicit-no-ignore", "argv": [*stable, "--sort", "path", "--no-heading",
            "--with-filename", "--no-ignore", "-n", "café", "."], "exitCode": 0},
        {"case": "json-unicode-byte-offsets", "argv": [*stable, "--json", "--fixed-strings", "café", "notes/café.txt"], "exitCode": 0},
        {"case": "pcre2-lookbehind", "argv": [*stable, "--pcre2", "--only-matching", "--no-heading",
            "--no-filename", r"(?<=prix=)\d+(?= EUR)", "notes/café.txt"], "exitCode": 0},
        {"case": "stdin-first-match", "argv": [*stable, "--text", "--line-buffered", "--max-count", "1",
            "--no-heading", "-n", "café", "-"], "exitCode": 0,
            "stdin": "noise\ncafé stdin €\n".encode()},
        {"case": "stdin-default-eof", "argv": [*stable, "absent", "-"], "exitCode": 1},
        {"case": "no-match-exit-one", "argv": [*stable, "not-in-these-files", "notes/plain.txt"], "exitCode": 1},
        {"case": "invalid-regex-exit-two", "argv": [*stable, "[", "notes/plain.txt"], "exitCode": 2},
    ]


def validate_case(case, streams, *, expected_version="15.2.0"):
    name = case["case"]
    stdout, stderr = streams["stdout"], streams["stderr"]
    if name == "invalid-regex-exit-two":
        require(stdout == b"" and b"regex parse error" in stderr and b"unclosed character class" in stderr,
                "Invalid regex did not preserve rg's real diagnostic")
        return {}
    require(stderr == b"", "ripgrep emitted an unexpected stderr diagnostic")
    if name == "direct-version":
        require(stdout.startswith(("ripgrep " + expected_version + " ").encode())
                or stdout.startswith(("ripgrep " + expected_version + "\n").encode()),
                "Installed ripgrep version differs")
        require(b"+pcre2" in stdout and b"JIT is available" in stdout,
                "Installed ripgrep lacks its PCRE2/JIT capability")
        return {"versionUtf8": stdout.decode()}
    if name == "pcre2-jit-version":
        require(stdout.startswith(b"PCRE2 ") and b"JIT is available" in stdout,
                "Real PCRE2/JIT availability is missing")
        return {"pcre2Utf8": stdout.decode()}
    if name == "files-respect-gitignore":
        expected = ["./README.md", "./data/items.csv", "./notes/café.txt", "./notes/plain.txt", "./samples/raw.bin"]
        require(stdout.decode().splitlines() == expected, "rg --files ignored the wrong project entries")
    elif name in {"unicode-search-respects-gitignore", "explicit-no-ignore"}:
        lines = ["./data/items.csv:2:café,42\n", "./notes/café.txt:1:café naïve ☕\n"]
        if name == "explicit-no-ignore":
            lines.extend(["./ignored/secret.txt:1:café ignored\n", "./notes/debug.log:1:café diagnostic\n"])
        require(stdout == "".join(sorted(lines)).encode(), "Unicode search bytes or gitignore handling differ")
    elif name == "json-unicode-byte-offsets":
        events = [decode(line) for line in stdout.splitlines()]
        require([event["type"] for event in events] == ["begin", "match", "end", "summary"],
                "rg JSON event sequence differs")
        match = events[1]["data"]
        require(match["path"] == {"text": "notes/café.txt"}
                and match["lines"] == {"text": "café naïve ☕\n"}
                and match["line_number"] == 1 and match["absolute_offset"] == 0
                and match["submatches"] == [{"match": {"text": "café"}, "start": 0, "end": 5}],
                "rg JSON lost Unicode text or byte offsets")
        require(events[2]["data"]["stats"]["matches"] == 1
                and events[3]["data"]["stats"]["matched_lines"] == 1,
                "rg JSON summary does not describe the actual match")
        return {"events": events}
    elif name == "pcre2-lookbehind":
        require(stdout == b"42\n", "Actual PCRE2 lookbehind did not select the expected amount")
    elif name == "stdin-first-match":
        require(stdout == "2:café stdin €\n".encode(), "rg did not read the actual model stdin bytes")
    elif name in {"stdin-default-eof", "no-match-exit-one"}:
        require(stdout == b"", "No-match search emitted unexpected bytes")
    else:
        raise ValueError("Unknown ripgrep qualification case: " + name)
    return {}


class Client(_ordinary.Client):
    def process(self, record, cwd, command, *, expected_exit=0, stdin=None, null_context=False):
        key = "rg-cli-" + uuid.uuid4().hex
        params = {"processId": key, "argv": command, "cwd": path_uri(cwd), "env": {},
            "envPolicy": {"inherit": "all", "ignoreDefaultExcludes": False,
                "exclude": [], "set": {}, "includeOnly": []}, "tty": False, "pipeStdin": stdin is not None}
        if null_context:
            params["sandbox"] = None
        record.update(command=command, cwd=str(cwd), processId=key, channel="exec",
            sandboxField="null" if null_context else "absent", admitted=False, closed=False, passed=False,
            expectedExitCode=expected_exit)
        streams = {name: bytearray() for name in ("stdout", "stderr")}
        cursor = 0
        try:
            record["start"] = self.exec_request("process/start", params)
            require(record["start"] == {"processId": key, "sandboxType": "none"},
                    "Ordinary rg launch receipt differs")
            record["admitted"] = True
            if stdin is not None:
                require(type(stdin) is bytes and len(stdin) <= 32768, "Qualification stdin is outside its bounded payload")
                record["stdin"] = {"bytes": len(stdin), "sha256": hashlib.sha256(stdin).hexdigest(),
                    "dataBase64": base64.b64encode(stdin).decode(), "eofRequested": False}
                record["stdin"]["receipt"] = self.exec_request("process/write", {"processId": key,
                    "writeId": "qualification-stdin-" + uuid.uuid4().hex,
                    "chunk": record["stdin"]["dataBase64"]})
                require(record["stdin"]["receipt"] == {"status": "accepted"}, "Model stdin bytes were not accepted")
            deadline = time.monotonic() + 90
            while True:
                require(time.monotonic() < deadline, "Native rg command deadline exceeded")
                result = self.exec_request("process/read", {"processId": key, "afterSeq": cursor, "waitMs": 1000})
                record["result"] = {name: value for name, value in result.items() if name != "chunks"}
                for chunk in result["chunks"]:
                    require(type(chunk["seq"]) is int and chunk["seq"] > cursor and chunk["stream"] in streams,
                            "Native rg output ordering or stream differs")
                    data = base64.b64decode(chunk["chunk"], validate=True)
                    require(base64.b64encode(data).decode() == chunk["chunk"], "Noncanonical native rg output")
                    streams[chunk["stream"]].extend(data)
                    require(len(streams[chunk["stream"]]) <= 65536, "Native rg output exceeds the complete capture bound")
                    cursor = chunk["seq"]
                require(type(result["nextSeq"]) is int and result["nextSeq"] > cursor, "Native rg cursor moved backwards")
                cursor = result["nextSeq"] - 1
                if result["closed"]:
                    record["closed"] = True
                    require(result["exited"] and result["failure"] is None
                            and type(result["exitCode"]) is int and result["exitCode"] == expected_exit
                            and result["sandboxDenied"] is False,
                            "Native rg process result differs: " + json.dumps(record["result"]))
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
    manifest = _ordinary._host.read_manifest(startup)
    workspace = _ordinary._host.canonical_uri(manifest["workspaceRoot"])
    project = workspace / (".ripgrep-qualification-" + uuid.uuid4().hex)
    client = Client(manifest)
    report = {"schema": "foldgpt.production-ripgrep-qualification.v1", "passed": False,
        "officialEditorQualified": False, "javaCleanupReceiptRequired": True,
        "controllerPid": os.getpid(), "controllerUid": os.getuid(), "startupOwner": manifest["peer"],
        "directory": str(project), "modelFileCases": [], "modelCases": [], "independentReads": [],
        "stdinScope": "Actual model write and first-match exit, default closed stdin, and real Bash pipeline EOF",
        "modelExplicitStdinEofQualified": False, "androidJitExecutionQualified": False}
    try:
        require(expected_platform in {"android", "linux"}, "Expected platform must be Android or explicit host Linux")
        report["connection"] = client.connect()
        info = client.exec_request("environment/info", {})
        report["environmentInfo"] = info
        require(info.get("platformOs") == expected_platform and info["shell"]["name"] == "bash",
                "Actual native platform or advertised Bash differs")
        shell = info["shell"]["path"]
        require(type(shell) is str and shell.startswith("/"), "Installed Bash path must be absolute")
        try:
            client.exec_request("fs/getMetadata", {"path": path_uri(project)})
        except _ordinary.ModelRpcError as error:
            require(error.error.get("code") == -32004, "Reserved rg project absence was not proven")
        else:
            raise ValueError("Reserved rg qualification project already exists")
        for directory in (project, *(project / name for name in (".git", "data", "notes", "ignored", "samples"))):
            client.exec_request("fs/createDirectory", {"path": path_uri(directory), "recursive": False})
        for name, data in SOURCES.items():
            path = path_uri(project / name)
            client.exec_request("fs/writeFile", {"path": path, "dataBase64": base64.b64encode(data).decode(), "sandbox": None})
            value = client.exec_request("fs/readFile", {"path": path})
            require(base64.b64decode(value["dataBase64"], validate=True) == data, "Model rg source readback differs")
            report["modelFileCases"].append({"path": str(project / name), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "passed": True})

        identity_code = ("import hashlib,json,os,platform,shutil,sys; p=shutil.which('rg'); "
            "assert p; data=open(p,'rb').read(); print(json.dumps({'platform':sys.platform,"
            "'machine':platform.machine(),'uid':os.getuid(),'pid':os.getpid(),'cwd':os.getcwd(),"
            "'rgPath':p,'rgRealpath':os.path.realpath(p),'rgSha256':hashlib.sha256(data).hexdigest(),"
            "'rgElfMagic':data[:4].hex(),'rgElfMachine':int.from_bytes(data[18:20],'little')}))")
        identity_record = {"case": "native-identity-and-rg-path"}
        report["modelCases"].append(identity_record)
        streams = client.process(identity_record, project, ["python3", "-c", identity_code])
        require(streams["stderr"] == b"", "Native identity emitted a diagnostic")
        identity = decode(streams["stdout"])
        require(identity["platform"] == expected_platform and identity["uid"] == manifest["peer"]["uid"]
                and identity["uid"] != 0 and identity["cwd"] == str(project)
                and identity["rgPath"].startswith("/") and len(identity["rgSha256"]) == 64,
                "Native worker or rg PATH identity differs")
        if expected_platform == "android":
            require(identity["machine"] == "aarch64" and identity["rgElfMagic"] == "7f454c46"
                    and identity["rgElfMachine"] == 183, "PATH rg is not an actual ARM64 ELF")
        identity_record.update(workerIdentity=identity, passed=True)

        if expected_platform == "android":
            record = {"case": "pcre2-actual-jit-execution"}
            report["modelCases"].append(record)
            probe_code = ("import pathlib,subprocess,sys; "
                "probe=pathlib.Path(sys.executable).parent/'libfoldgpt_pcre2_jit_probe.so'; "
                "raise SystemExit(subprocess.run([str(probe)],check=False).returncode)")
            streams = client.process(record, project, ["python3", "-c", probe_code], null_context=True)
            require(streams["stderr"] == b"", "Real PCRE2 JIT probe emitted an error")
            jit = decode(streams["stdout"])
            require(jit["pcre2Version"].split()[0] == "10.47" and jit["jitAvailable"] == 1
                    and type(jit["jitBytes"]) is int and jit["jitBytes"] > 0
                    and jit["jitMatch"] == 2 and jit["unicodeLookbehindBackreferencePassed"] is True,
                    "PCRE2 did not actually compile and execute the expected JIT pattern")
            record.update(jitResult=jit, passed=True)
            report["androidJitExecutionQualified"] = True

        version = None
        for index, case in enumerate(cases()):
            record = {"case": case["case"]}
            report["modelCases"].append(record)
            streams = client.process(record, project, ["rg", *case["argv"]],
                expected_exit=case["exitCode"], stdin=case.get("stdin"), null_context=bool(index % 2))
            record.update(validate_case(case, streams))
            record["passed"] = True
            if case["case"] == "direct-version":
                version = streams["stdout"]
        record = {"case": "bash-path-version"}
        report["modelCases"].append(record)
        streams = client.process(record, project, [shell, "-c", "command -v rg && rg --version"], null_context=True)
        require(streams == {"stdout": identity["rgPath"].encode() + b"\n" + version, "stderr": b""},
                "Bash PATH did not resolve the same version and path of rg")
        record["passed"] = True
        record = {"case": "bash-pipeline-stdin-eof"}
        report["modelCases"].append(record)
        script = "set -o pipefail; printf '%s\\n' " + shlex.join(["café pipe", "tea"]) + " | rg --no-config --color never -n café -"
        streams = client.process(record, project, [shell, "-c", script])
        require(streams == {"stdout": "1:café pipe\n".encode(), "stderr": b""}, "Native Bash pipeline/rg EOF bytes differ")
        record["passed"] = True

        for name, expected in SOURCES.items():
            path = project / name
            value = client.exec_request("fs/readFile", {"path": path_uri(path), "sandbox": None})
            model_data = base64.b64decode(value["dataBase64"], validate=True)
            config_data = client.config_read(path)
            receipt, host_data = client.request("readFile", path=path_uri(path))
            require(model_data == config_data == host_data == expected, "rg changed project bytes or independent readers disagree")
            report["independentReads"].append({"path": str(path), "bytes": len(expected),
                "sha256": hashlib.sha256(expected).hexdigest(), "configMatched": True,
                "humanMatched": True, "modelMatched": True, "humanReceipt": receipt})
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
        result = {"schema": "foldgpt.production-ripgrep-qualification.v1", "passed": False,
            "officialEditorQualified": False, "javaCleanupReceiptRequired": True,
            "error": {"type": type(error).__name__, "message": str(error)}}
    print(json.dumps(result, separators=(",", ":")), flush=True)
    raise SystemExit(0 if result["passed"] else 1)
