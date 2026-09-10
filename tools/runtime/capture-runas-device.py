"""Read-only device/package evidence around the fixed run-as qualification."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

PROJECT = Path(__file__).resolve().parents[2]
PACKAGES = ("app.foldgpt", "com.openai.chatgpt", "app.foldgpt.runasqualification.v1")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(PROJECT)
    output.mkdir(parents=True, exist_ok=False)
    adb = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"
    prefix = [str(adb), "-s", "<device-serial>", "shell"]
    commands = []

    def call(*argv):
        result = subprocess.run(prefix + list(argv), capture_output=True, timeout=30)
        commands.append({"argv": list(argv), "code": result.returncode,
                         "stdout": result.stdout.decode("utf-8", "replace"),
                         "stderr": result.stderr.decode("utf-8", "replace")})
        if result.returncode:
            raise RuntimeError(f"Read-only device collection failed: {argv!r}")
        return result.stdout.decode("utf-8").strip()

    data = {"schema": "foldgpt.runas-device-snapshot.v1", "readOnly": True,
            "serial": "<device-serial>"}
    try:
        data["bootId"] = call("cat", "/proc/sys/kernel/random/boot_id")
        data["stayAwake"] = call("settings", "get", "global", "stay_on_while_plugged_in")
        data["properties"] = {name: call("getprop", name) for name in (
            "ro.boot.verifiedbootstate", "ro.boot.flash.locked", "ro.boot.vbmeta.device_state",
            "ro.boot.warranty_bit", "ro.product.model", "ro.build.fingerprint")}
        packages = {}
        for name in PACKAGES:
            installed = call("pm", "list", "packages", name).splitlines()
            if "package:" + name not in installed:
                packages[name] = []
                continue
            paths = call("pm", "path", name).splitlines()
            apks = []
            for line in paths:
                if not line.startswith("package:"):
                    raise ValueError("Unexpected package-path response")
                path = line.removeprefix("package:")
                if not re.fullmatch(r"/data/app/[A-Za-z0-9_~./+=-]+\.apk", path):
                    raise ValueError("Unexpected installed APK path")
                digest = call("sha256sum", path).split()[0]
                if re.fullmatch("[a-f0-9]{64}", digest) is None:
                    raise ValueError("Invalid APK digest")
                apks.append({"path": path, "sha256": digest})
            packages[name] = apks
        data["packages"] = packages
        data["completed"] = True
    finally:
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        (output / "snapshot.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "bootId": data["bootId"],
                      "packages": {name: len(apks) for name, apks in packages.items()}}))


if __name__ == "__main__":
    main()
