"""Collect a read-only, identity-bound baseline before/after device qualification.

Does not launch, stop, unlock, pair, install, change Android settings or read
conversations. This snapshot never issues a stability or payment certification.
"""
import argparse
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shlex
import subprocess


spec = importlib.util.spec_from_file_location(
    "memory_inspector", Path(__file__).with_name("inspect-android-memory.py"))
memory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(memory)

PROPERTIES = (
    "ro.product.model", "ro.build.fingerprint", "ro.build.version.release",
    "ro.build.version.sdk", "ro.build.version.oneui", "ro.boot.warranty_bit",
    "ro.warranty_bit", "ro.boot.flash.locked", "ro.boot.vbmeta.device_state",
    "ro.boot.verifiedbootstate",
)


def checked_text(result, label):
    if result["code"] != 0 or not result["text"].strip():
        raise ValueError(label + " unavailable")
    return result["text"].strip()


def effective_phantom_limit(result):
    if result["code"] != 0:
        return None
    values = re.findall(r"^\s*max_phantom_processes\s*=\s*(\d+)\s*$",
                        result["text"], re.M | re.I)
    return int(values[0]) if len(values) == 1 else None


def collect(read, expected_model, expected_serial):
    # Never mistake an unrelated LAN Android device for the development Fold.
    model = checked_text(read("getprop", "ro.product.model"), "Model")
    serial = checked_text(read("getprop", "ro.serialno"), "Hardware serial")
    if (model, serial) != (expected_model, expected_serial):
        raise ValueError("Connected device identity differs from the explicit target")
    boot = checked_text(read("cat", "/proc/sys/kernel/random/boot_id"), "Boot identity")
    result = {
        "schema": "foldgpt.device-baseline.v1",
        "observedAt": datetime.now(timezone.utc).isoformat(),
        "model": model, "bootBefore": boot,
        "scope": "Read-only sequential baseline; no session, stability or payment qualification",
        "properties": {}, "unavailable": [],
    }
    for name in PROPERTIES:
        observation = read("getprop", name)
        value = observation["text"].strip() if observation["code"] == 0 else ""
        result["properties"][name] = value or None
        if not value:
            result["unavailable"].append(name)
    uid_text = checked_text(read("run-as", "app.foldgpt", "id", "-u"), "Application UID")
    if not uid_text.isdecimal():
        raise ValueError("Application UID is not numeric")
    uid = int(uid_text)
    result["uid"] = uid
    before = memory.uid_processes(read("ps", "-A", "-o", "UID,PID,PPID,NAME"), uid)
    # Store only FoldGPT names and IDs, not other apps or process arguments.
    result["uidProcesses"] = before
    result["observedUidProcessCount"] = len(before)
    settings = read("dumpsys", "activity", "settings")
    result["effectiveGlobalPhantomLimit"] = effective_phantom_limit(settings)
    result["globalPhantomProcessCount"] = None
    result["processScope"] = (
        "Visible UID processes are not Android's global monitored-child population. "
        "Hidden processes and collection races can make this an incomplete count. "
        "No free-slot budget is inferred from the UID count.")
    if result["effectiveGlobalPhantomLimit"] is None:
        result["unavailable"].append("effectiveGlobalPhantomLimit")
    package = read("dumpsys", "package", "app.foldgpt")
    for label, pattern in (("versionCode", r"\bversionCode=(\d+)\b"),
                           ("versionName", r"\bversionName=([^\s]+)")):
        matches = set(re.findall(pattern, package["text"])) if package["code"] == 0 else set()
        result[label] = next(iter(matches)) if len(matches) == 1 else None
        if result[label] is None:
            result["unavailable"].append(label)
    after = memory.uid_processes(read("ps", "-A", "-o", "UID,PID,PPID,NAME"), uid)
    result["sameVisiblePidSetAtBoundaries"] = {p["pid"] for p in before} == {p["pid"] for p in after}
    result["bootAfter"] = checked_text(read("cat", "/proc/sys/kernel/random/boot_id"), "Final boot identity")
    if result["bootAfter"] != boot:
        raise ValueError("Device rebooted during baseline collection")
    result["completedAt"] = datetime.now(timezone.utc).isoformat()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--serial", required=True, help="Explicit authorized ADB transport")
    parser.add_argument("--expected-device-serial", required=True, help="Known hardware serial, including with Wi-Fi ADB")
    parser.add_argument("--expected-model", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output must be new")

    def read(*parts):
        try:
            process = subprocess.run([args.adb, "-s", args.serial, "shell", "-T", shlex.join(parts)],
                                     capture_output=True, timeout=15)
            return {"code": process.returncode, "text": process.stdout.decode(errors="replace")}
        except (OSError, subprocess.TimeoutExpired):
            return {"code": None, "text": ""}

    report = collect(read, args.expected_model, args.expected_device_serial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(report, output, indent=2)
        output.write("\n")
    print(json.dumps({"output": str(args.output), "observedUidProcessCount": report["observedUidProcessCount"],
                      "effectiveGlobalPhantomLimit": report["effectiveGlobalPhantomLimit"],
                      "qualification": "not-performed"}))


if __name__ == "__main__":
    main()
