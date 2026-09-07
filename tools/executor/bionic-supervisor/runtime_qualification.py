"""Exact small-project contract for the real Bionic factory, never a sandbox.

The APK embeds the request this module constructs. Its fixed diagnostic facade
admits only that request; the unchanged production backend enforces every real
Python/Bash filesystem and process operation. This module is also PC-importable.
"""
import base64
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import shlex
import zipfile

BASE = PurePosixPath("/data/local/tmp/foldgpt-bionic-runtime-qualification-v1")
PROCESS_ID = "runtime-qualification"
INPUT = b"native input\n"
LIMITS = {"wall_ms": 15000, "cpu_seconds": 8, "uid_task_budget": 8,
          "data_bytes": 268435456, "file_bytes": 16777216,
          "output_bytes": 8192, "descriptors": 128}
SENTINEL = b"probe-private-unchanged\n"
SOURCES = {
    "calculator.py": "def add(a, b):\n    return a + b\n\ndef answer():\n    return 42\n",
    "test_calculator.py": (
        "import unittest\nfrom calculator import add, answer\n"
        "class CalculatorTests(unittest.TestCase):\n"
        "    def test_edited_answer(self):\n        self.assertEqual(answer(), 42)\n"
        "    def test_signed_addition(self):\n        self.assertEqual(add(-13, 55), 42)\n"
        "    def test_invalid_operand(self):\n"
        "        with self.assertRaises(TypeError):\n            add(1, None)\n"),
    "__main__.py": "from calculator import answer\nprint(answer())\n",
}
FLAGS = frozenset({"projectCreated", "sourceEdited", "unittestPassed", "zipappBuilt",
    "zipappExecuted", "rpcStdin", "childStreams", "childEnvironment", "bashCwd",
    "pythonCwd", "privateReadDenied", "privateWriteDenied", "protectedWriteDenied",
    "networkIpv4Denied", "networkUnixDenied", "ioctlDenied", "supervisorSignalDenied",
    "privateCwdDenied"})

PAYLOAD = r'''
import base64,errno,fcntl,hashlib,json,os,socket,subprocess,sys,zipapp
from pathlib import Path

def require(value, message):
    if not value:
        raise AssertionError(message)

proofs = {}
denials = {}
def denied(name, operation):
    try:
        value = operation()
    except OSError as error:
        require(error.errno in (errno.EACCES, errno.EPERM), (name, error.errno))
        denials[name] = error.errno
        proofs[name] = True
        return
    if isinstance(value, int):
        os.close(value)
    elif hasattr(value, "close"):
        value.close()
    raise AssertionError(name + " unexpectedly succeeded")

def run(argv, *, input=None, expected=0, env=None):
    value = subprocess.run(argv, input=input, capture_output=True, timeout=6,
                           env={} if env is None else env, check=False)
    require(value.returncode == expected,
            (argv, value.returncode, value.stdout, value.stderr))
    return value

workspace = Path(os.environ["FOLDGPT_WORKSPACE"])
directory = workspace / "directory"
require(sys.platform == os.environ["FOLDGPT_EXPECTED_PLATFORM"], "unexpected platform")
require(sys.flags.isolated and sys.dont_write_bytecode, "interpreter isolation flags lost")
require(sys.executable == os.environ["FOLDGPT_PYTHON_REAL"], "wrong packaged interpreter")
require(Path.cwd() == directory, "Bash cd did not change real cwd")
proofs["bashCwd"] = True
require(sys.stdin.buffer.read(13) == b"native input\n", "real RPC stdin differed")
proofs["rpcStdin"] = True
require(list(directory.iterdir()) == [], "qualification directory was not empty")
denied("privateReadDenied", lambda: os.open(workspace / "private/secret", os.O_RDONLY))
denied("privateWriteDenied", lambda: os.open(workspace / "private/secret", os.O_WRONLY))
denied("protectedWriteDenied", lambda: os.open(workspace / ".git/config", os.O_WRONLY | os.O_CREAT, 0o600))
denied("networkIpv4Denied", lambda: socket.socket(socket.AF_INET))
denied("networkUnixDenied", lambda: socket.socket(socket.AF_UNIX))
denied("ioctlDenied", lambda: fcntl.ioctl(1, 0, 0))
denied("supervisorSignalDenied", lambda: os.kill(os.getppid(), 0))
denied("privateCwdDenied", lambda: os.chdir(workspace / "private"))
require(Path.cwd() == directory, "refused chdir changed cwd")

project = directory / "project"
project.mkdir(mode=0o700)
os.chdir(project)
require(Path.cwd() == project, "Python chdir did not change real cwd")
proofs["pythonCwd"] = True
source = Path("calculator.py")
source.write_text("def add(a, b):\n    return a + b\n\ndef answer():\n    return 41\n", encoding="utf-8")
before = source.read_bytes()
require(before.count(b"return 41") == 1, "initial source differs")
proofs["projectCreated"] = True
source.write_bytes(before.replace(b"return 41", b"return 42"))
require(b"return 42" in source.read_bytes() and b"return 41" not in source.read_bytes(), "source edit failed")
proofs["sourceEdited"] = True
Path("test_calculator.py").write_text(
    "import unittest\nfrom calculator import add, answer\n"
    "class CalculatorTests(unittest.TestCase):\n"
    "    def test_edited_answer(self):\n        self.assertEqual(answer(), 42)\n"
    "    def test_signed_addition(self):\n        self.assertEqual(add(-13, 55), 42)\n"
    "    def test_invalid_operand(self):\n"
    "        with self.assertRaises(TypeError):\n            add(1, None)\n", encoding="utf-8")
Path("__main__.py").write_text("from calculator import answer\nprint(answer())\n", encoding="utf-8")
tests = run([sys.executable, "-I", "-B", "-m", "unittest", "discover", "-s", str(project), "-v"])
require(tests.stdout == b"" and b"Ran 3 tests in " in tests.stderr
        and tests.stderr.endswith(b"\nOK\n"), "three unittest passes missing")
proofs["unittestPassed"] = True
distribution = directory / "dist"
distribution.mkdir(mode=0o700)
archive = distribution / "calculator.pyz"
zipapp.create_archive(project, archive, compressed=True)
archive_bytes = archive.read_bytes()
require(len(archive_bytes) > 0, "build did not produce an archive")
proofs["zipappBuilt"] = True
package = run([sys.executable, "-B", str(archive)])
require(package.stdout == b"42\n" and package.stderr == b"", "built zipapp output differs")
proofs["zipappExecuted"] = True
child_code = (
    "import os,sys; "
    "assert 'FOLDGPT_WORKSPACE' not in os.environ; "
    "assert 'LD_PRELOAD' not in os.environ; "
    "assert sys.stdin.buffer.read() == b'\\x00\\xffABC'; "
    "sys.stdout.buffer.write(b'\\x00\\xffABC'); "
    "sys.stderr.write('native stderr\\n'); sys.exit(23)"
)
child = run([sys.executable, "-I", "-B", "-c", child_code], input=b"\x00\xffABC", expected=23)
require(child.stdout == b"\x00\xffABC" and child.stderr == b"native stderr\n", "child streams differ")
proofs["childStreams"] = proofs["childEnvironment"] = True
source_hashes = {name: hashlib.sha256(Path(name).read_bytes()).hexdigest()
                 for name in ("calculator.py", "test_calculator.py", "__main__.py")}
report = {"type": "runtime-qualification", "success": True, "platform": sys.platform,
          "python": sys.version.split()[0], "executable": sys.executable,
          "workspace": str(workspace), "bashCwd": str(directory), "pythonCwd": str(project),
          "proofs": proofs, "denials": denials, "unittestCount": 3,
          "unittestStderr": tests.stderr.decode("utf-8"), "sourceSha256": source_hashes,
          "initialSourceSha256": hashlib.sha256(before).hexdigest(),
          "zipappBytes": len(archive_bytes), "zipappSha256": hashlib.sha256(archive_bytes).hexdigest(),
          "zipappStdout": package.stdout.decode("ascii"), "childExitCode": child.returncode,
          "childStdoutBase64": base64.b64encode(child.stdout).decode("ascii"),
          "childStderr": child.stderr.decode("ascii")}
encoded = json.dumps(report, sort_keys=True, separators=(",", ":")) + "\n"
(workspace / "qualification-result.json").write_text(encoded, encoding="utf-8")
print(encoded, end="", flush=True)
'''


def context(workspace):
    uri = PurePosixPath(workspace).as_uri()
    return {"permissions": {"type": "managed", "file_system": {"type": "restricted", "entries": [
        {"path": {"type": "path", "path": uri}, "access": "write"},
        {"path": {"type": "path", "path": uri + "/private"}, "access": "deny"}]}, "network": "restricted"},
        "cwd": uri, "workspaceRoots": [uri], "windowsSandboxLevel": "disabled"}


def process_request(workspace, python_executable, platform="android"):
    policy = context(workspace)
    command = 'cd directory && exec "$FOLDGPT_PYTHON_REAL" -I -B -c ' + shlex.quote(PAYLOAD)
    return {"processId": PROCESS_ID, "argv": ["bash", "--noprofile", "--norc", "-c", command],
        "cwd": policy["cwd"], "env": {"FOLDGPT_WORKSPACE": str(workspace),
        "FOLDGPT_PYTHON_REAL": str(python_executable), "FOLDGPT_EXPECTED_PLATFORM": platform},
        "pipeStdin": True, "tty": False, "sandbox": policy}


def input_request():
    return {"processId": PROCESS_ID, "writeId": "qualification-input-v1",
            "chunk": base64.b64encode(INPUT).decode("ascii")}


def file_request(workspace):
    return {"path": (PurePosixPath(workspace) / "qualification-result.json").as_uri(), "sandbox": context(workspace)}


def validate_report(stdout, stderr, workspace, python_executable, platform):
    if stderr or not stdout.endswith(b"\n") or len(stdout.splitlines()) != 1:
        raise ValueError("Runtime worker must produce one JSON line and no stderr")
    report = json.loads(stdout)
    required = {"type", "success", "platform", "python", "executable", "workspace", "bashCwd", "pythonCwd",
        "proofs", "denials", "unittestCount", "unittestStderr", "sourceSha256", "initialSourceSha256",
        "zipappBytes", "zipappSha256", "zipappStdout", "childExitCode", "childStdoutBase64", "childStderr"}
    denials = {name for name in FLAGS if name.endswith("Denied")}
    if (type(report) is not dict or set(report) != required or report["type"] != "runtime-qualification"
            or report["success"] is not True or report["platform"] != platform
            or report["executable"] != str(python_executable) or report["workspace"] != str(workspace)
            or report["bashCwd"] != str(PurePosixPath(workspace) / "directory")
            or report["pythonCwd"] != str(PurePosixPath(workspace) / "directory/project")
            or type(report["proofs"]) is not dict or set(report["proofs"]) != FLAGS
            or any(value is not True for value in report["proofs"].values())
            or type(report["denials"]) is not dict or set(report["denials"]) != denials
            or any(type(value) is not int or value not in (1, 13) for value in report["denials"].values())
            or type(report["unittestCount"]) is not int or report["unittestCount"] != 3
            or type(report["childExitCode"]) is not int or report["childExitCode"] != 23
            or report["childStdoutBase64"] != base64.b64encode(b"\x00\xffABC").decode("ascii")
            or report["childStderr"] != "native stderr\n" or report["zipappStdout"] != "42\n"
            or type(report["zipappBytes"]) is not int or not 0 < report["zipappBytes"] <= LIMITS["file_bytes"]):
        raise ValueError("Runtime worker differs from the exact fixed qualification contract")
    expected = {name: hashlib.sha256(value.encode()).hexdigest() for name, value in SOURCES.items()}
    initial = SOURCES["calculator.py"].replace("return 42", "return 41").encode()
    if report["sourceSha256"] != expected or report["initialSourceSha256"] != hashlib.sha256(initial).hexdigest():
        raise ValueError("Created or edited Python source identity differs")
    tests = report["unittestStderr"]
    if (not isinstance(tests, str) or "Ran 3 tests in " not in tests or not tests.endswith("\nOK\n")
            or any((name + " (test_calculator.CalculatorTests." + name + ") ... ok\n") not in tests
                   for name in ("test_edited_answer", "test_signed_addition", "test_invalid_operand"))):
        raise ValueError("Actual unittest output does not prove the three expected tests")
    return report


def validate_artifacts(workspace, report):
    """Only after actual clean ownership: compare material files and built archive."""
    workspace = Path(workspace)
    if (workspace / "private/secret").read_bytes() != SENTINEL or (workspace / ".git/config").exists():
        raise ValueError("Protected qualification sentinel changed")
    for name, data in SOURCES.items():
        if (workspace / "directory/project" / name).read_bytes() != data.encode():
            raise ValueError("Material project source differs: " + name)
    data = (workspace / "directory/dist/calculator.pyz").read_bytes()
    if len(data) != report["zipappBytes"] or hashlib.sha256(data).hexdigest() != report["zipappSha256"]:
        raise ValueError("Material zipapp identity differs")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        if sorted(archive.namelist()) != sorted(SOURCES) or archive.testzip() is not None:
            raise ValueError("Built zipapp does not contain the exact tested project")
        for name, value in SOURCES.items():
            if archive.read(name) != value.encode():
                raise ValueError("Built zipapp source differs: " + name)
    return {"sources": report["sourceSha256"], "zipappSha256": report["zipappSha256"],
            "zipappBytes": len(data), "archiveVerified": True, "sentinelsUnchanged": True}
