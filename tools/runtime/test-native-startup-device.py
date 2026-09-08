"""Run startup file/socket tests with real Bionic Python, never a supervisor.

This independently tests POSIX publication on the Fold through ADB/run-as. It
does not qualify the Shizuku production launcher or the ordinary application UI.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import uuid

ROOT = Path(__file__).resolve().parents[2]


def main():
    nonce = uuid.uuid4().hex[:8]
    output = ROOT / "downloads/native-startup-device-20260908" / nonce
    output.mkdir(parents=True, exist_ok=False)
    workspace = "/data/user/0/app.foldgpt/files/nt-" + nonce
    qualified = json.loads((ROOT / "downloads/runas-broker-v2/device-reports/run_broker_v2.json").read_text())
    target = qualified["installation"]["target"]
    runtime = qualified["installation"]["qualification"]["nativeLibraryDir"]
    executable = runtime + "/libfoldgpt_python_cli.so"
    uid = target["uid"]
    adb = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"
    prefix = [str(adb), "-s", "R3GL808JN4A"]
    calls = []

    def call(args, data=None, timeout=30):
        mode = "exec-in" if data is not None else "shell"
        completed = subprocess.run(prefix + [mode, shlex.join(args)], input=data,
                                   capture_output=True, timeout=timeout)
        calls.append({"argv": args, "code": completed.returncode,
                      "stdout": completed.stdout.decode("utf-8", "replace"),
                      "stderr": completed.stderr.decode("utf-8", "replace")})
        completed.check_returncode()
        return completed.stdout

    result = {"scope": "Real Bionic startup file/socket tests via ADB/run-as; no supervisor or UI",
              "deviceDirectory": workspace, "uid": uid, "passed": False}
    try:
        boot = call(["cat", "/proc/sys/kernel/random/boot_id"]).decode().strip()
        if boot != "348d453e-f4e5-40e0-8ef0-030f4d5e38af":
            raise ValueError("Boot differs from the qualified runtime")
        actual = call(["sha256sum", executable]).decode().split()[0]
        if actual != qualified["installation"]["nativeLibraries"]["libfoldgpt_python_cli.so"]:
            raise ValueError("Installed qualified Bionic Python differs")
        call(["run-as", "app.foldgpt", "mkdir", "-m", "700", workspace])
        payload = {"tools/__init__.py": b"", "tools/executor/__init__.py": b""}
        for name in ("native_runtime_startup.py", "test_native_runtime_startup.py"):
            payload["tools/executor/" + name] = (ROOT / "tools/executor" / name).read_bytes()
        if b"FOLDGPT_TEST_TMPDIR" not in payload["tools/executor/test_native_runtime_startup.py"]:
            raise ValueError("Test must use its actual private temporary directory")
        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w", format=tarfile.GNU_FORMAT) as package:
            for folder in ("tools", "tools/executor"):
                info = tarfile.TarInfo(folder)
                info.type, info.mode, info.uid, info.gid = tarfile.DIRTYPE, 0o700, uid, uid
                package.addfile(info)
            for name, data in payload.items():
                info = tarfile.TarInfo(name)
                info.mode, info.uid, info.gid, info.size = 0o600, uid, uid, len(data)
                package.addfile(info, io.BytesIO(data))
        (output / "sources.tar").write_bytes(archive.getvalue())
        call(["run-as", "app.foldgpt", "tar", "-xf", "-", "-C", workspace], archive.getvalue())
        records = []
        for name, data in payload.items():
            digest = hashlib.sha256(data).hexdigest()
            if call(["run-as", "app.foldgpt", "sha256sum", workspace + "/" + name]).decode().split()[0] != digest:
                raise ValueError("Transferred source differs")
            records.append({"path": name, "bytes": len(data), "sha256": digest})
        program = (
            "import os,sys,json,unittest;os.environ['FOLDGPT_TEST_TMPDIR']=sys.argv[1];sys.path.insert(0,sys.argv[1]);"
            "from tools.executor import test_native_runtime_startup as tests;"
            "suite=unittest.defaultTestLoader.loadTestsFromModule(tests);"
            "result=unittest.TextTestRunner(verbosity=2).run(suite);"
            "print(json.dumps(dict(pid=os.getpid(),uid=os.getuid(),gid=os.getgid(),"
            "platform=sys.platform,tests=result.testsRun,failures=len(result.failures),"
            "errors=len(result.errors),skipped=len(result.skipped),passed=result.wasSuccessful())));"
            "sys.exit(0 if result.wasSuccessful() else 1)"
        )
        completed = call(["run-as", "app.foldgpt", executable, "-I", "-S", "-B", "-u",
                          "-c", program, workspace], timeout=60)
        evidence = json.loads(completed.decode().splitlines()[-1])
        if (evidence["uid"] != uid or evidence["gid"] != uid or evidence["platform"] != "android"
                or evidence["passed"] is not True or evidence["tests"] == 0 or evidence["skipped"] != 0):
            raise ValueError("Native test execution differs")
        if call(["cat", "/proc/sys/kernel/random/boot_id"]).decode().strip() != boot:
            raise ValueError("Boot changed during startup tests")
        result.update(passed=True, tests=evidence, sources=records, bootId=boot, bootUnchanged=True)
    finally:
        (output / "commands.json").write_text(json.dumps(calls, indent=2) + "\n")
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), **result}))


if __name__ == "__main__":
    main()
