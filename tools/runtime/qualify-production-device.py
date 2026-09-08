"""Drive real Android PREPARE and the real GNU/Bionic client; never replay work.

The APK must already be installed and independently verified. Native workers
run only in the Android run-as owner; PRoot runs the controller client alone.
"""
import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import shlex
import subprocess
import tarfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
DATA = "/data/user/0/app.foldgpt"


def successful_cleanup(value, pid):
    """Require both actual receipts for the selected bootstrap generation."""
    if (not isinstance(value, dict) or value.get("state") != "closed"
            or type(pid) is not int or pid <= 0):
        return False
    for key in ("lastNativeSessionStatus", "lastRemoteStatus"):
        receipt = value.get(key)
        if not isinstance(receipt, dict):
            return False
        if not (receipt.get("bootstrapPid") == pid and receipt.get("waitStatus") == 0
                and receipt.get("bootstrapReaped") is True and receipt.get("cleanupComplete") is True
                and receipt.get("ownerRetained") is False
                and receipt.get("setupError") is None and receipt.get("cleanupError") is None
                and all(receipt.get(flag) is False for flag in (
                    "transportFailed", "quarantined", "refusedBeforeFork"))):
            return False
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apk-sha256", required=True)
    parser.add_argument("--qualification", choices=("python", "host-v2", "ordinary-uid"), default="python")
    parser.add_argument("--controller-delay", type=float, default=0,
                        help="Deliberately delay the actual controller to qualify slow desktop startup")
    parser.add_argument("--verify-restart", action="store_true",
                        help="After ordinary Python and clean STOP, require fresh Java admission and idle STOP")
    args = parser.parse_args()
    if not 0 <= args.controller_delay <= 60:
        parser.error("Controller delay must be between 0 and 60 seconds")
    if args.verify_restart and args.qualification != "ordinary-uid":
        parser.error("--verify-restart requires --qualification ordinary-uid")
    trial = uuid.uuid4().hex[:8]
    directory = {"python": "native-production-device-20260908",
        "host-v2": "native-host-production-device-20260908",
        "ordinary-uid": "native-ordinary-production-device-20260908"}[args.qualification]
    output = ROOT / "downloads" / directory / trial
    output.mkdir(parents=True, exist_ok=False)
    prefix = [str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"), "-s", "R3GL808JN4A"]
    commands, statuses = [], []
    result = {"passed": False, "qualification": args.qualification,
              "scope": "Actual Java/Shizuku/run-as owner and GNU client; app-server and UI not tested"}
    prepared = False
    process = None

    def cleanup_verified(value):
        pid = (result.get("startup", {}).get("peer") or {}).get("pid")
        return successful_cleanup(value, pid)

    def run(argv, data=None, required=True, timeout=30):
        # Shell v2 forwards stdin EOF and the remote exit status. exec-in can
        # return while the app-UID tar is still alive, before PREPARE begins.
        # Windows adb can normalize CRLF on stdin even without a PTY. Keep
        # binary archives ASCII in transit, then verify every extracted hash.
        command = shlex.join(argv)
        if data is not None:
            command = "base64 -d | " + command
            data = base64.b64encode(data)
        completed = subprocess.run(prefix + ["shell", "-T", command],
                                   input=data, capture_output=True, timeout=timeout)
        record = {"argv": argv, "code": completed.returncode,
                  "stdout": completed.stdout.decode("utf-8", "replace"),
                  "stderr": completed.stderr.decode("utf-8", "replace")}
        commands.append(record)
        if required:
            completed.check_returncode()
        return record

    def text(argv):
        return run(argv)["stdout"].strip()

    def status():
        record = run(["run-as", "app.foldgpt", "cat", "files/native-executor-status.json"], required=False)
        if record["code"]:
            return None
        value = json.loads(record["stdout"])
        if not statuses or statuses[-1] != value:
            statuses.append(value)
            (output / "statuses.json").write_text(json.dumps(statuses, indent=2) + "\n")
        return value

    def action(name):
        return text(["am", "start", "-W", "-n", "app.foldgpt/.NativePreparationActivity",
                     "-a", "app.foldgpt.action." + name + "_NATIVE_EXECUTOR"])

    def verify_restart():
        restart = result["restart"] = {"passed": False, "clientConnected": False}
        previous = status()
        if not cleanup_verified(previous):
            raise ValueError("First generation is not cleanly closed before restart")
        restart["beforeStatus"] = previous
        startup = None
        ready = None
        try:
            restart["prepareResponse"] = action("PREPARE")
            deadline = time.monotonic() + 80
            while time.monotonic() < deadline:
                current = status()
                if current != previous and current is not None:
                    if current.get("state") == "ready":
                        ready = restart["readyStatus"] = current
                        break
                    if current.get("state") in ("unavailable", "closed"):
                        raise RuntimeError("Native readmission failed: " + json.dumps(current))
                time.sleep(0.2)
            if ready is None:
                raise TimeoutError("No fresh native readiness after standard Python")
            startup = json.loads(text(["run-as", "app.foldgpt", "cat", ready["startupManifest"]]))
            restart["startup"] = startup
            (output / "restart-startup.json").write_text(json.dumps(startup, indent=2) + "\n")
            if startup["socketPath"] == result["startup"]["socketPath"]:
                raise ValueError("Restart reused the previous acquisition endpoint")
            admission = restart["admission"] = (ready.get("lastRemoteStatus") or {}).get("admission")
            if not (isinstance(admission, dict) and admission.get("admitted") is True
                    and admission.get("stage") == "complete" and admission.get("error") is None):
                raise ValueError("Fresh Java runtime admission receipt is absent")
        except BaseException as error:
            restart["error"] = type(error).__name__ + ": " + str(error)
            raise
        finally:
            restart["stopResponse"] = action("STOP")
            deadline = time.monotonic() + 30
            pid = (startup or {}).get("peer", {}).get("pid")
            while time.monotonic() < deadline:
                current = status()
                if current is not None:
                    restart["finalStatus"] = current
                if successful_cleanup(current, pid):
                    restart["cleanupVerified"] = True
                    break
                if pid is None and current is not None and current.get("state") in ("closed", "unavailable"):
                    break
                time.sleep(0.2)
            restart["bootUnchanged"] = text(["cat", "/proc/sys/kernel/random/boot_id"]) == boot
            if startup is not None:
                paths = ["/proc/" + str(pid), startup["socketPath"], ready["startupManifest"],
                         DATA + "/app_foldgpt_exec/process-session.json"]
                absences = restart["resourceAbsence"] = []
                for path in paths:
                    response = run(["run-as", "app.foldgpt", "ls", "-ld", path], required=False)
                    absences.append({"path": path, "absent": response["code"] != 0
                                     and "No such file" in response["stderr"]})
                restart["resourcesAbsent"] = all(row["absent"] for row in absences)
        restart["passed"] = bool(restart.get("cleanupVerified") and restart.get("resourcesAbsent")
                                 and restart.get("bootUnchanged"))
        return restart["passed"]

    try:
        boot = text(["cat", "/proc/sys/kernel/random/boot_id"])
        package_path = text(["pm", "path", "app.foldgpt"])
        if not package_path.startswith("package:/data/app/") or len(package_path.splitlines()) != 1:
            raise ValueError("Unexpected installed FoldGPT APK")
        apk = package_path.removeprefix("package:")
        if text(["sha256sum", apk]).split()[0] != args.apk_sha256:
            raise ValueError("Installed production APK hash differs")
        native = str(Path(apk).parent).replace("\\", "/") + "/lib/arm64"
        uid_text = text(["run-as", "app.foldgpt", "id", "-u"])
        uid = int(uid_text)
        before = status()
        if before is not None and before.get("state") not in ("closed", "unavailable"):
            raise ValueError("Existing native session must be closed before qualification")
        selected = text(["run-as", "app.foldgpt", "cat", "files/debian/etc/foldgpt-user"])
        passwd = text(["run-as", "app.foldgpt", "cat", "files/debian/etc/passwd"])
        accounts = [line.split(":") for line in passwd.splitlines() if line.split(":")[0] == selected]
        if len(accounts) != 1 or len(accounts[0]) != 7:
            raise ValueError("Ambiguous actual GNU account")
        account = accounts[0]
        base = DATA + "/files/pc-" + trial
        text(["run-as", "app.foldgpt", "mkdir", "-m", "700", base])
        # PREPARE does not run the desktop's alias refresh. Bind the test
        # controller to this installation without mutating its normal alias.
        text(["run-as", "app.foldgpt", "ln", "-s", native + "/libtalloc.so", base + "/libtalloc.so.2"])
        if text(["run-as", "app.foldgpt", "readlink", "-f", base + "/libtalloc.so.2"]) != native + "/libtalloc.so":
            raise ValueError("Controller talloc alias differs from the installed APK")
        for directory in (DATA + "/cache/x11", DATA + "/cache/shm"):
            text(["run-as", "app.foldgpt", "test", "-d", directory])
        client_source = {"python": "qualify_native_production.py", "host-v2": "qualify_production_host_v2.py",
            "ordinary-uid": "qualify_production_ordinary_uid.py"}[args.qualification]
        source = (ROOT / "tools/executor" / client_source).read_bytes()
        client_inputs = {"client.py": source,
            "native_path_uri.py": (ROOT / "tools/executor/native_path_uri.py").read_bytes()}
        if args.qualification == "ordinary-uid":
            client_inputs["qualify_production_host_v2.py"] = (
                ROOT / "tools/executor/qualify_production_host_v2.py").read_bytes()
        tar = io.BytesIO()
        with tarfile.open(fileobj=tar, mode="w", format=tarfile.GNU_FORMAT) as archive:
            for name, content in client_inputs.items():
                entry = tarfile.TarInfo(name)
                entry.size, entry.uid, entry.gid, entry.mode = len(content), uid, uid, 0o600
                archive.addfile(entry, io.BytesIO(content))
        run(["run-as", "app.foldgpt", "tar", "-xf", "-", "-C", base], tar.getvalue())
        for name, content in client_inputs.items():
            if text(["run-as", "app.foldgpt", "sha256sum", base + "/" + name]).split()[0] != hashlib.sha256(content).hexdigest():
                raise ValueError("Transferred GNU client input differs: " + name)
            (output / name).write_bytes(content)
        # Start only after the entire independent client is ready on device.
        prepared = True
        result["prepareResponse"] = action("PREPARE")
        deadline = time.monotonic() + 80
        ready = None
        while time.monotonic() < deadline:
            current = status()
            if current != before and current is not None:
                if current.get("state") == "ready":
                    ready = current
                    break
                if current.get("state") in ("unavailable", "closed"):
                    raise RuntimeError("Native preparation failed: " + json.dumps(current))
            time.sleep(0.2)
        if ready is None:
            raise TimeoutError("No real native readiness within the collection deadline")
        manifest_path = ready["startupManifest"]
        manifest = json.loads(text(["run-as", "app.foldgpt", "cat", manifest_path]))
        result["startup"] = manifest
        (output / "startup.json").write_text(json.dumps(manifest, indent=2) + "\n")
        if args.controller_delay:
            began = time.monotonic()
            time.sleep(args.controller_delay)
            result["controllerDelaySeconds"] = time.monotonic() - began
            result["ownerPresentAfterDelay"] = text(["test", "-d", "/proc/" + str(manifest["peer"]["pid"])]) == ""
        temp = DATA + "/cache/x11"
        controller = ["run-as", "app.foldgpt", "/system/bin/env",
            "LD_LIBRARY_PATH=" + base + ":" + DATA + "/files/native:" + native,
            "PROOT_LOADER=" + native + "/libproot-loader.so", "PROOT_LOADER_32=" + native + "/libproot-loader32.so",
            "PROOT_TMP_DIR=" + temp, "TMPDIR=" + temp, "/system/bin/sh", "-c", 'exec "$@"', "foldgpt-client",
            native + "/libproot.so", "--kill-on-exit", "--link2symlink", "--sysvipc",
            "-r", DATA + "/files/debian", "-i", account[2] + ":" + account[3], "-w", account[5]]
        for bind in ("/dev", "/proc", "/sys", "/system", "/apex", temp + ":/tmp", DATA + "/cache/shm:/dev/shm"):
            controller.extend(["-b", bind])
        shared = [ready["workspace"], DATA + "/app_foldgpt_exec",
                  DATA + "/files/native-runtime-v1/python", native, base]
        for path in shared:
            controller.extend(["-b", path + ":" + path])
        controller.extend(["/usr/bin/env", "-i", "HOME=" + account[5], "USER=" + selected, "LOGNAME=" + selected,
            "LANG=C.UTF-8", "PATH=/usr/local/bin:/usr/bin:/bin", "/usr/bin/python3", "-I", "-S", "-B", "-u",
            base + "/client.py", manifest_path])
        stdout_file, stderr_file = output / "client.stdout", output / "client.stderr"
        with stdout_file.open("wb") as stdout, stderr_file.open("wb") as stderr:
            process = subprocess.Popen(prefix + ["shell", "-T", shlex.join(controller)], stdout=stdout, stderr=stderr)
            returncode = process.wait(timeout=130)
        commands.append({"argv": controller, "code": returncode, "stdoutFile": stdout_file.name, "stderrFile": stderr_file.name})
        report = json.loads(stdout_file.read_text().splitlines()[-1])
        result["client"] = report
        if returncode != 0 or report.get("passed") is not True:
            raise RuntimeError("Production client failed; preserve exact report")
        result["clientPassed"] = True
    except BaseException as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        if prepared:
            try:
                result["beforeStopStatus"] = status()
                run(["logcat", "-d", "-v", "threadtime", "-s", "FoldGPT-executor", "FoldGPT"], required=False)
                result["stopResponse"] = action("STOP")
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    current = status()
                    if current is not None:
                        result["finalStatus"] = current
                    if current is not None and current.get("state") in ("closed", "unavailable") and cleanup_verified(current):
                        break
                    time.sleep(0.2)
                result["bootUnchanged"] = text(["cat", "/proc/sys/kernel/random/boot_id"]) == boot
                if "startup" in result:
                    pid = result["startup"]["peer"]["pid"]
                    absent = run(["ls", "-d", "/proc/" + str(pid)], required=False)
                    result["nativeOwnerAbsent"] = absent["code"] != 0 and "No such file" in absent["stderr"]
                final = result.get("finalStatus", {})
                session = final.get("lastNativeSessionStatus") or {}
                result["cleanupVerified"] = cleanup_verified(final)
                result["passed"] = bool(result.get("clientPassed") and result.get("bootUnchanged")
                    and result.get("nativeOwnerAbsent") and result["cleanupVerified"]
                    and final.get("state") == "closed" and session.get("waitStatus") == 0
                    and all((final.get(status_key) or {}).get("setupError") is None
                        and all((final.get(status_key) or {}).get(key) is False
                            for key in ("transportFailed", "quarantined", "refusedBeforeFork"))
                        for status_key in ("lastNativeSessionStatus", "lastRemoteStatus")))
                if process is not None and process.poll() is None:
                    result["controllerReturncodeAfterStop"] = process.wait(timeout=15)
            except BaseException as error:
                result["passed"] = False
                result["cleanupCollectionError"] = type(error).__name__ + ": " + str(error)
        if args.verify_restart and result.get("passed"):
            result["firstCyclePassed"] = True
            result["passed"] = False
            try:
                cache = (result.get("client") or {}).get("standardPythonCache") or {}
                if cache.get("cacheOutsideRuntime") is not True:
                    raise ValueError("Standard Python did not prove real caches outside its runtime")
                result["passed"] = verify_restart()
            except BaseException as error:
                result["restartError"] = type(error).__name__ + ": " + str(error)
        run(["logcat", "-d", "-v", "threadtime", "-s", "FoldGPT-executor", "FoldGPT"], required=False)
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
        (output / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), **result}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
