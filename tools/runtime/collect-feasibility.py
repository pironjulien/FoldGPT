"""Read-only Fold feasibility evidence; absence of a device never counts as a pass."""
import argparse
import base64
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
PROPERTIES = (
    "ro.product.model", "ro.product.device", "ro.soc.model", "ro.soc.manufacturer",
    "ro.build.version.release", "ro.build.version.sdk", "ro.build.version.oneui",
    "ro.build.version.security_patch", "ro.boot.verifiedbootstate",
    "ro.boot.flash.locked", "ro.boot.warranty_bit", "ro.product.cpu.abilist",
)
KERNEL_FEATURES = (
    "CONFIG_USER_NS", "CONFIG_PID_NS", "CONFIG_NET_NS", "CONFIG_KVM",
    "CONFIG_SECCOMP", "CONFIG_SECCOMP_FILTER", "CONFIG_SECURITY_LANDLOCK",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="R3GL808JN4A")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    out = args.output.resolve()
    if not out.is_relative_to(ROOT / "work"):
        parser.error("Evidence must stay under the project's work directory")
    out.mkdir(parents=True, exist_ok=False)
    adb = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"
    report = {"schema": "foldgpt.feasibility-observation.v1",
              "at": datetime.now(timezone.utc).isoformat(),
              "status": "unavailable", "newExecutionTestPassed": False,
              "deviceMutated": False, "checks": {}, "calls": []}

    def shell(*argv):
        proc = subprocess.run([str(adb), "-s", args.serial, "shell", "-T", shlex.join(argv)],
                              capture_output=True, timeout=20)
        report["calls"].append({"argv": argv, "code": proc.returncode})
        if proc.returncode:
            raise RuntimeError("Read command failed: " + " ".join(argv))
        return proc.stdout

    def text(*argv):
        return shell(*argv).decode("utf-8", errors="replace").strip()

    def optional(key, fn):
        try:
            report["checks"][key] = {"status": "observed", "value": fn()}
        except Exception as exc:
            report["checks"][key] = {"status": "unavailable", "reason": str(exc)}

    def private(path):
        return base64.b64decode(shell("run-as", "app.foldgpt", "base64", path))

    def processes():
        app_uid = int(text("run-as", "app.foldgpt", "id", "-u"))
        rows = text("ps", "-A", "-o", "PID,PPID,UID,NAME").splitlines()
        values = {}
        for row in rows[1:]:
            cols = row.split(None, 3)
            if len(cols) != 4 or not all(c.isdigit() for c in cols[:3]):
                continue
            values[int(cols[0])] = {"pid": int(cols[0]), "ppid": int(cols[1]),
                                    "uid": int(cols[2]), "name": cols[3]}
        # Include same-UID detached/reparented children, not only name/parent matches.
        owned = {pid for pid, item in values.items() if item["uid"] == app_uid}
        result = []
        fields = {"Name", "Uid", "Gid", "TracerPid", "Seccomp", "CapEff", "Cpus_allowed_list",
                  "VmRSS", "VmSwap", "Threads", "PPid"}
        for pid in sorted(owned):
            item = dict(values[pid])
            try:
                item["startTicksBefore"] = process_start_ticks(pid)
            except (RuntimeError, ValueError, IndexError):
                item["observation"] = "identity_unavailable"
                result.append(item)
                continue
            for name in ("status", "cgroup", "cpuset"):
                try:
                    raw = text("run-as", "app.foldgpt", "cat", f"/proc/{pid}/{name}")
                    item[name] = ({k: v.strip() for line in raw.splitlines() if ":" in line
                                   for k, v in [line.split(":", 1)] if k in fields}
                                  if name == "status" else raw)
                except RuntimeError:
                    item[name] = {"unavailable": True}
            try:
                item["startTicksAfter"] = process_start_ticks(pid)
                uid_fields = item.get("status", {}).get("Uid", "").split()
                item["stableIdentity"] = (item["startTicksBefore"] == item["startTicksAfter"]
                                          and len(uid_fields) == 4
                                          and all(int(v) == app_uid for v in uid_fields))
            except (RuntimeError, ValueError, IndexError):
                item["stableIdentity"] = False
            item["observation"] = "stable_process_sample" if item["stableIdentity"] else "inconclusive_identity"
            result.append(item)
        return {"appUid": app_uid, "processes": result,
                "scope": "main-thread samples, not an atomic snapshot or foreground/background comparison"}

    def kernel():
        data = base64.b64decode(shell("base64", "/proc/config.gz"))
        raw = gzip.decompress(data).decode()
        flags = {}
        for key in KERNEL_FEATURES:
            match = re.search(r"^" + re.escape(key) + r"=(.*)$", raw, re.M)
            flags[key] = match[1] if match else ("not set" if f"# {key} is not set" in raw else "unknown")
        return {"configSha256": hashlib.sha256(data).hexdigest(), "features": flags}

    def process_start_ticks(pid):
        raw = text("run-as", "app.foldgpt", "cat", f"/proc/{pid}/stat")
        # comm can contain whitespace and parentheses; field22 follows the final ')'.
        return int(raw[raw.rfind(")") + 2:].split()[19])

    def native_state():
        state = json.loads(private("files/native-executor-status.json"))
        selected = {key: state.get(key) for key in ("schema", "state", "directNative", "workspace",
                                                    "officialLauncherReplaced", "peerUid")}
        owner = state.get("lastNativeSessionStatus") or {}
        selected["persistedOwnerStatus"] = {key: owner.get(key) for key in
                                            ("ready", "bootstrapPid", "quarantined",
                                             "ownerRetained", "cleanupComplete")}
        selected["liveReadinessVerified"] = False
        selected["scope"] = "persisted status only; PID presence does not authenticate the owner or prove readiness"
        pid = owner.get("bootstrapPid")
        if isinstance(pid, int) and pid > 1:
            try:
                selected["pidObservation"] = {"pid": pid, "startTicks": process_start_ticks(pid),
                                               "ownerIdentityAuthenticated": False}
            except (RuntimeError, ValueError, IndexError):
                selected["pidObservation"] = {"pid": pid, "identityUnavailable": True}
        return selected

    def config_failures():
        lines = private("files/runtime.log").decode(errors="replace").splitlines()
        found = []
        for i, line in enumerate(lines):
            if "project cwd is outside configuration discovery root" in line:
                method = re.search(r"\bmethod=([^ ]+)", line)
                conversation = re.search(r"\bconversationId=([^ ]+)", line)
                found.append({"line": i + 1, "method": method[1] if method else None,
                              "conversationId": conversation[1] if conversation else None})
        return {"error": "project cwd is outside configuration discovery root", "occurrences": found}

    try:
        devices = subprocess.run([str(adb), "devices"], capture_output=True, timeout=10, check=True)
        entries = [line.split() for line in devices.stdout.decode().splitlines()[1:] if line.strip()]
        device = next((x for x in entries if x[0] == args.serial), None)
        if device is None or len(device) < 2 or device[1] != "device":
            report["reason"] = "Fold is not connected and authorized in ADB"
            return 2
        report["bootBefore"] = text("cat", "/proc/sys/kernel/random/boot_id")
        optional("properties", lambda: {key: text("getprop", key) for key in PROPERTIES})
        optional("kernel", kernel)
        optional("memory", lambda: {k: v.strip() for line in text("cat", "/proc/meminfo").splitlines()
                                      if ":" in line for k, v in [line.split(":", 1)]
                                      if k in ("MemTotal", "MemAvailable", "SwapTotal", "SwapFree")})
        optional("memoryLimiter", lambda: text("am", "memory-limiter", "status"))
        optional("nativeOwner", native_state)
        optional("legacyConfigFailures", config_failures)
        optional("foldgptProcesses", processes)
        report["bootAfter"] = text("cat", "/proc/sys/kernel/random/boot_id")
        report["sameBoot"] = report["bootBefore"] == report["bootAfter"]
        report["status"] = "observed" if report["sameBoot"] else "boot_changed_stop"
        return 0 if report["sameBoot"] else 1
    except Exception as exc:
        report["reason"] = type(exc).__name__ + ": " + str(exc)
        return 1
    finally:
        (out / "observation.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"status": report["status"], "output": str(out / "observation.json"),
                          "newExecutionTestPassed": False, "reason": report.get("reason")}))


if __name__ == "__main__":
    sys.exit(main())
