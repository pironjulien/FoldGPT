"""Fixed, bounded qualification; embedded in probe, never a command service."""
import errno
import fcntl
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import zipapp


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def denied(label, operation):
    try:
        result = operation()
    except OSError as error:
        require(error.errno in (errno.EACCES, errno.EPERM),
                f"{label}: unexpected errno {error.errno}")
        print(json.dumps({"check": label, "denied": True,
                          "errno": error.errno}), flush=True)
        return
    if isinstance(result, int):
        os.close(result)
    elif hasattr(result, "close"):
        result.close()
    raise AssertionError(f"{label}: operation unexpectedly succeeded")


def run(arguments, *, input=None, expected=0, env=None):
    process = subprocess.run(
        arguments, input=input, text=True, capture_output=True,
        timeout=8, env=env, check=False,
    )
    require(process.returncode == expected,
            f"exit {process.returncode}, expected {expected}: "
            f"{process.stdout!r} {process.stderr!r}")
    return process


workspace = Path(os.environ["FOLDGPT_WORKSPACE"])
outside = os.environ["FOLDGPT_OUTSIDE"]
supervisor = int(os.environ["FOLDGPT_SUPERVISOR"])
require(Path.cwd() == workspace, "unexpected cwd")
require(not list(workspace.iterdir()), "workspace was not empty")
require(sys.flags.isolated and sys.dont_write_bytecode, "CLI flags lost")
require(sys.executable == os.environ["FOLDGPT_PYTHON_REAL"],
        "sys.executable is not the packaged executable")

# These occur in the actual interpreter after both restrictions, in addition
# to trusted C self-checks. No signal is delivered by kill(pid, 0).
denied("python-outside-read", lambda: os.open(outside, os.O_RDONLY))
denied("python-outside-write", lambda: os.open(outside, os.O_WRONLY))
denied("python-network-ipv4", lambda: socket.socket(socket.AF_INET))
denied("python-network-unix", lambda: socket.socket(socket.AF_UNIX))
denied("python-ioctl", lambda: fcntl.ioctl(1, 0, 0))
denied("python-outside-process", lambda: os.kill(supervisor, 0))

project = workspace / "project"
project.mkdir(mode=0o700)
source = project / "calculator.py"
source.write_text("def add(a, b):\n    return a + b\n\n"
                  "def answer():\n    return 41\n", encoding="utf-8")
before = source.read_text(encoding="utf-8")
require("return 41" in before, "initial project content missing")
source.write_text(before.replace("return 41", "return 42"), encoding="utf-8")
(project / "test_calculator.py").write_text(
    "import unittest\nfrom calculator import add, answer\n"
    "class CalculatorTests(unittest.TestCase):\n"
    "    def test_edited_answer(self):\n"
    "        self.assertEqual(answer(), 42)\n"
    "    def test_signed_addition(self):\n"
    "        self.assertEqual(add(-13, 55), 42)\n"
    "    def test_invalid_operand(self):\n"
    "        with self.assertRaises(TypeError):\n"
    "            add(1, None)\n", encoding="utf-8")
(project / "__main__.py").write_text(
    "from calculator import answer\nprint(answer())\n", encoding="utf-8")

tests = run([sys.executable, "-I", "-B", "-m", "unittest", "discover",
             "-s", str(project), "-v"], env={})
require("Ran 3 tests" in tests.stderr and "OK" in tests.stderr,
        "unit tests did not report the expected three passes")
print(tests.stderr, end="", flush=True)

distribution = workspace / "dist"
distribution.mkdir(mode=0o700)
archive = distribution / "calculator.pyz"
zipapp.create_archive(project, archive, compressed=True)
require(archive.is_file() and archive.stat().st_size > 0,
        "zipapp was not built")
# Isolated mode intentionally omits a zipapp from sys.path. Standard script
# execution is separately qualified here, using an empty process environment.
package = run([sys.executable, "-B", str(archive)], env={})
require(package.stdout == "42\n", "the built zipapp did not run")

child_code = (
    "import os,sys; "
    "assert 'FOLDGPT_CODE' not in os.environ; "
    "assert sys.stdin.read() == 'native input\\n'; "
    "print('native stdout'); "
    "print('native stderr', file=sys.stderr); sys.exit(23)"
)
child = run([sys.executable, "-I", "-B", "-c", child_code],
            input="native input\n", expected=23, env={})
require(child.stdout == "native stdout\n", "stdout capture failed")
require(child.stderr == "native stderr\n", "stderr capture failed")

# Material results are retained for the supervisor/PC to inspect. The report
# says only what this bounded offline Python/Bash qualification has exercised.
report = {
    "type": "fixture-pass",
    "python": sys.version.split()[0],
    "platform": sys.platform,
    "prefix": sys.prefix,
    "project_created_and_edited": True,
    "unittest_passes": 3,
    "zipapp_bytes": archive.stat().st_size,
    "zipapp_stdout": package.stdout,
    "subprocess_exit": child.returncode,
    "empty_child_environment": True,
    "denials_in_interpreter": 6,
}
(workspace / "qualification-result.json").write_text(
    json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report), flush=True)
