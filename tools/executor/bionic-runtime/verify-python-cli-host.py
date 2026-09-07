"""Exercise the actual launcher source against host CPython, never a phone.

This checks portable PyConfig/CLI behavior. It cannot qualify Android loading,
Android's stdio adaptation, its seccomp policy or the managed executor.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import sysconfig
import tempfile


def main() -> None:
    if sys.platform != "linux" or os.geteuid() == 0:
        raise SystemExit("Run as an ordinary Linux user with host Python development headers")
    source = Path(__file__).with_name("python-cli.c")
    work = Path(tempfile.mkdtemp(prefix="foldgpt-bionic-cli-host-", dir="/var/tmp"))
    frozen = work / source.name
    frozen.write_bytes(source.read_bytes())
    binary = work / "python-cli"
    version = sysconfig.get_config_var("LDVERSION")
    command = ["cc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
               "-fPIE", "-pie", "-Wl,-z,relro,-z,now,-z,noexecstack",
               "-DFOLDGPT_PYTHON_HOME=" + json.dumps(sys.base_prefix),
               "-I" + sysconfig.get_path("include"), str(frozen),
               "-L" + sysconfig.get_config_var("LIBDIR"), "-lpython" + version,
               *shlex.split(sysconfig.get_config_var("LIBS") or ""),
               *shlex.split(sysconfig.get_config_var("SYSLIBS") or ""),
               "-o", str(binary)]
    subprocess.run(command, check=True, capture_output=True, timeout=60)
    report = {"schema": "foldgpt.bionic-python-cli-host.v1", "uid": os.geteuid(),
              "scope": "Portable launcher CLI only; host CPython, not Android or confinement",
              "hostPython": sys.version, "sourceSha256": hashlib.sha256(frozen.read_bytes()).hexdigest(),
              "binarySha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
              "compile": command, "checks": []}

    def run(name, args, *, data=b"", env=None, expected=b"", code=0, stderr=b""):
        result = subprocess.run([str(binary), *args], input=data, cwd=work,
                                env={} if env is None else env,
                                capture_output=True, timeout=15)
        observation = {"name": name, "argv": args, "exit": result.returncode,
                       "stdoutHex": result.stdout.hex(), "stderrHex": result.stderr.hex()}
        report["checks"].append(observation)
        if result.returncode != code or result.stdout != expected or (
                stderr is not None and result.stderr != stderr):
            raise AssertionError(observation)
        return result

    try:
        run("version-with-empty-environment", ["--version"],
            expected=f"Python {sys.version.split()[0]}\n".encode())
        arguments = ["espace ici", "écriture", "line\nbreak"]
        run("command-and-unicode-argv", ["-c", "import json,sys; print(json.dumps(sys.argv))", *arguments],
            expected=(json.dumps(["-c", *arguments]) + "\n").encode())
        run("binary-stdin-stdout", ["-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            data=bytes(range(256)) * 7, expected=bytes(range(256)) * 7)
        run("separate-stderr-and-exit", ["-c", "import sys; print('out'); print('err',file=sys.stderr); sys.exit(23)"],
            expected=b"out\n", stderr=b"err\n", code=23)
        run("stdin-script", ["-"], data=b"print(6 * 7)\n", expected=b"42\n")
        (work / "cli_module.py").write_text("import sys\nprint(sys.argv[1])\n", encoding="utf-8")
        run("module-cli", ["-m", "cli_module", "module-ok"], expected=b"module-ok\n")
        run("script-cli", [str(work / "cli_module.py"), "script-ok"], expected=b"script-ok\n")
        run("isolated-flags-and-invalid-pythonhome", ["-I", "-E", "-S", "-B", "-u", "-c",
            "import sys; print(sys.flags.isolated,sys.flags.ignore_environment,sys.flags.no_site,sys.dont_write_bytecode)"],
            env={"PYTHONHOME": "/definitely/missing/foldgpt-host-proof"}, expected=b"1 1 1 True\n")
        alternate = work / "alternate-home"
        alternate.mkdir()
        (alternate / "lib").symlink_to(Path(sys.base_prefix) / "lib", target_is_directory=True)
        run("explicit-pythonhome-retained", ["-c", "import sys; print(sys.prefix)"],
            env={"PYTHONHOME": str(alternate)}, expected=(str(alternate) + "\n").encode())
        run("real-child-through-sys-executable", ["-I", "-c",
            "import os,subprocess,sys; assert os.path.samefile(sys.executable,sys.argv[1]); "
            "r=subprocess.run([sys.executable,'-I','-c','print(6*7)'],env={},capture_output=True,check=True); "
            "sys.stdout.buffer.write(r.stdout)", str(binary)], expected=b"42\n")
        run("invalid-option-retains-error", ["--foldgpt-no-such-option"], code=2, stderr=None)
        run("real-fork-wait", ["-I", "-c",
            "import os; p=os.fork(); os._exit(19) if p==0 else None; "
            "pid,status=os.waitpid(p,0); print(pid==p,os.waitstatus_to_exitcode(status))"], expected=b"True 19\n")
        project = work / "project"
        project.mkdir()
        (project / "maths.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        (project / "__main__.py").write_text("from maths import add\nprint(add(19, 23))\n", encoding="utf-8")
        (project / "test_maths.py").write_text(
            "import unittest\nfrom maths import add\nclass Addition(unittest.TestCase):\n"
            "    def test_positive(self): self.assertEqual(add(19,23),42)\n"
            "    def test_negative(self): self.assertEqual(add(-3,2),-1)\n"
            "    def test_zero(self): self.assertEqual(add(0,0),0)\n", encoding="utf-8")
        tested = run("real-project-unit-tests", ["-m", "unittest", "discover", "-s", str(project)], stderr=None)
        if b"Ran 3 tests" not in tested.stderr or not tested.stderr.endswith(b"OK\n"):
            raise AssertionError("Project test runner did not report three successful tests")
        run("compile-project-bytecode", ["-m", "compileall", "-q", str(project)])
        package = work / "project.pyz"
        run("build-real-zipapp", ["-m", "zipapp", str(project), "-o", str(package)])
        run("execute-real-zipapp", [str(package)], expected=b"42\n")
        report["projectZipSha256"] = hashlib.sha256(package.read_bytes()).hexdigest()
        report["passed"] = True
    finally:
        (work / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(work)
    print(f"PASS {len(report['checks'])} portable host CLI checks; Android remains untested")


if __name__ == "__main__":
    main()
