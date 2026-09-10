"""Measure actual Bionic/GNU shared files on the Fold, without a supervisor.

Both launchers use ADB/run-as. The GNU controller uses FoldRuntimeService's real
PRoot flags and exact bind. This does not certify Shizuku or the production UI.
"""
import base64
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
    output = ROOT / "downloads/shared-path-device-20260908" / nonce
    output.mkdir(parents=True, exist_ok=False)
    base = "/data/user/0/app.foldgpt/files/sp-" + nonce
    workspace = base + "/workspace"
    data_root = "/data/user/0/app.foldgpt"
    qualified = json.loads((ROOT / "downloads/runas-broker-v2/device-reports/run_broker_v2.json").read_text())
    uid = qualified["installation"]["target"]["uid"]
    libraries = qualified["installation"]["target"]["nativeLibraryDir"]
    python = qualified["installation"]["qualification"]["nativeLibraryDir"] + "/libfoldgpt_python_cli.so"
    prefix = [str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"), "-s", "<device-serial>"]
    calls = []

    def command(args, data=None):
        script = shlex.join(args)
        if data is not None:
            script = "base64 -d | " + script
        return prefix + ["shell", "-T", script]

    def run(args, data=None):
        completed = subprocess.run(command(args, data),
                                   input=base64.b64encode(data) if data is not None else None,
                                   capture_output=True, timeout=30)
        calls.append({"argv": args, "code": completed.returncode,
                      "stdout": completed.stdout.decode("utf-8", "replace"),
                      "stderr": completed.stderr.decode("utf-8", "replace")})
        completed.check_returncode()
        return completed.stdout.decode().strip()

    result = {"passed": False, "workspace": workspace, "uid": uid,
              "scope": "Real Bionic/GNU PRoot filesystem identities, bytes, rename and advisory locks; ADB/run-as launch only"}
    try:
        boot = run(["cat", "/proc/sys/kernel/random/boot_id"])
        if run(["sha256sum", python]).split()[0] != qualified["installation"]["nativeLibraries"]["libfoldgpt_python_cli.so"]:
            raise ValueError("Bionic Python input differs")
        user = run(["run-as", "app.foldgpt", "cat", "files/debian/etc/foldgpt-user"])
        passwd = run(["run-as", "app.foldgpt", "cat", "files/debian/etc/passwd"])
        account = [line.split(":") for line in passwd.splitlines() if line.split(":")[0] == user]
        if len(account) != 1 or len(account[0]) != 7:
            raise ValueError("Ambiguous real GNU identity")
        guest_uid, guest_gid, guest_home = int(account[0][2]), int(account[0][3]), account[0][5]
        source = (ROOT / "tools/runtime/measure-shared-paths.py").read_bytes()
        run(["run-as", "app.foldgpt", "mkdir", "-m", "700", base])
        run(["run-as", "app.foldgpt", "mkdir", "-m", "700", workspace])
        package = io.BytesIO()
        with tarfile.open(fileobj=package, mode="w", format=tarfile.GNU_FORMAT) as archive:
            info = tarfile.TarInfo("measure.py")
            info.size, info.mode, info.uid, info.gid = len(source), 0o600, uid, uid
            archive.addfile(info, io.BytesIO(source))
        run(["run-as", "app.foldgpt", "tar", "-xf", "-", "-C", base], package.getvalue())
        if run(["run-as", "app.foldgpt", "sha256sum", base + "/measure.py"]).split()[0] != hashlib.sha256(source).hexdigest():
            raise ValueError("Transferred instrument differs")
        (output / "measure.py").write_bytes(source)
        arguments = ["--workspace", workspace, "--kernel-uid", str(uid), "--timeout", "30"]
        native_args = ["run-as", "app.foldgpt", python, "-I", "-S", "-B", "-u", base + "/measure.py", "native", *arguments]
        temp, shm = data_root + "/cache/x11", data_root + "/cache/shm"
        controller_args = ["run-as", "app.foldgpt", "/system/bin/env",
            "LD_LIBRARY_PATH=" + data_root + "/files/native:" + libraries,
            "PROOT_LOADER=" + libraries + "/libproot-loader.so",
            "PROOT_LOADER_32=" + libraries + "/libproot-loader32.so", "PROOT_TMP_DIR=" + temp, "TMPDIR=" + temp,
            "/system/bin/sh", "-c", 'exec "$@"', "foldgpt-measure", libraries + "/libproot.so",
            "--kill-on-exit", "--link2symlink", "--sysvipc", "-r", data_root + "/files/debian",
            "-i", f"{guest_uid}:{guest_gid}", "-w", guest_home]
        for bind in ("/dev", "/proc", "/sys", "/system", "/apex", temp + ":/tmp", shm + ":/dev/shm",
                     base + ":" + base):
            controller_args.extend(["-b", bind])
        controller_args.extend(["/usr/bin/env", "-i", "HOME=" + guest_home, "USER=" + user,
            "LOGNAME=" + user, "LANG=C.UTF-8", "PATH=/usr/local/bin:/usr/bin:/bin", "/usr/bin/python3",
            "-I", "-S", "-B", "-u", base + "/measure.py", "controller", *arguments])
        processes = []
        for role, args in (("native", native_args), ("controller", controller_args)):
            stdout = (output / (role + ".stdout")).open("wb")
            stderr = (output / (role + ".stderr")).open("wb")
            process = subprocess.Popen(command(args), stdout=stdout, stderr=stderr)
            processes.append((role, args, process, stdout, stderr))
        records = {}
        for role, args, process, stdout, stderr in processes:
            code = process.wait(timeout=50)
            stdout.close(); stderr.close()
            calls.append({"argv": args, "code": code, "stdoutFile": role + ".stdout", "stderrFile": role + ".stderr"})
            text = (output / (role + ".stdout")).read_text()
            if code != 0:
                raise RuntimeError("Measurement failed: " + role + "; inspect preserved streams")
            records[role] = json.loads(text.splitlines()[-1])
        if any(record["status"] != "passed" for record in records.values()):
            raise ValueError("Measurement did not pass")
        if run(["cat", "/proc/sys/kernel/random/boot_id"]) != boot:
            raise ValueError("Boot changed during measurement")
        result.update(passed=True, bootId=boot, bootUnchanged=True, records=records,
                      sourceSha256=hashlib.sha256(source).hexdigest())
    finally:
        (output / "commands.json").write_text(json.dumps(calls, indent=2) + "\n")
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), "passed": result["passed"], "scope": result["scope"]}))


if __name__ == "__main__":
    main()
