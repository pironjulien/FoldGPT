#!/usr/bin/env python3
"""Explicit later ADB action: stage a generated fixture and optionally run it.

Run only after the coordinator authorizes device validation and installs the
debug APK containing CombinedPreparationProbeService. No APK/runtime install,
activation, root access, vault reads or live client operations are performed.
"""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

NAMES = {"fixture.properties", "base.tar.gz", "package.deb", "initialize_keyring.py",
         "supervise_keyring.py", "official_client_package.py", "install_official_client.py"}
INTEGRATION_NAMES = NAMES | {"integration.fgi"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--serial")
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--start", action="store_true")
    parser.add_argument("--validate-only", action="store_true", help="Verify every local input and print the bound launch inventory; never opens ADB")
    args = parser.parse_args()
    if args.validate_only and args.start:
        parser.error("--validate-only cannot start a device service")
    if not args.validate_only and not args.serial:
        parser.error("--serial is required for an actual ADB operation")
    plan = json.loads(args.plan.read_text(encoding="utf-8"))
    fixture, descriptor_hash = plan["fixture"], plan["descriptorSha256"]
    integration = plan.get("schema") == "foldgpt.combined-probe-staging.v2"
    names = INTEGRATION_NAMES if integration else NAMES
    if plan.get("schema") not in {"foldgpt.combined-probe-staging.v1", "foldgpt.combined-probe-staging.v2"} or not re.fullmatch("[0-9a-f]{32}", fixture):
        raise ValueError("Not a generated combined fixture plan")
    if not re.fullmatch("[0-9a-f]{64}", descriptor_hash):
        raise ValueError("Fixture descriptor digest missing")
    if integration and plan.get("coordinatorSchema") != "foldgpt.inactive-preparation.v3":
        raise ValueError("Integration fixture must select the v3 coordinator scope")
    remote = "cache/combined-input/" + fixture
    if plan["inputDirectory"] != remote or len(plan["files"]) != len(names):
        raise ValueError("Unexpected fixture input directory/set")
    observed = set()
    for item in plan["files"]:
        name = item["target"].removeprefix(remote + "/")
        if name not in names or name in observed or item["target"] != remote + "/" + name:
            raise ValueError("Unexpected or duplicate staging target")
        observed.add(name)
        path = Path(item["source"]).resolve(strict=True)
        with path.open("rb") as source:
            if path.stat().st_size != item["bytes"] or hashlib.file_digest(source, "sha256").hexdigest() != item["sha256"]:
                raise ValueError("Local input no longer matches its generated plan")
        if name == "fixture.properties" and item["sha256"] != descriptor_hash:
            raise ValueError("Descriptor and launch digest differ")
        if name == "fixture.properties":
            descriptor = path.read_text(encoding="ascii")
            expected_schema = "foldgpt.combined-preparation-fixture.v2" if integration else "foldgpt.combined-preparation-fixture.v1"
            if descriptor.splitlines().count("schema=" + expected_schema) != 1:
                raise ValueError("Staging and fixture descriptor scopes differ")
    if args.validate_only:
        print(json.dumps({"fixture": fixture, "validatedLocalInputs": len(observed), "adbOpened": False,
                          "coordinatorSchema": "foldgpt.inactive-preparation.v3" if integration else "foldgpt.inactive-preparation.v2",
                          "startArguments": ["shell", "am", "start-foreground-service", "-n",
                                             "app.foldgpt/app.foldgpt.install.CombinedPreparationProbeService",
                                             "--es", "fixture", fixture, "--es", "descriptorSha256", descriptor_hash],
                          "report": "files/.combined-probes/" + fixture + "/report.json"}, indent=2))
        return
    adb = [args.adb, "-s", args.serial]

    def shell(script):
        return subprocess.run(adb + ["shell", "run-as app.foldgpt sh -c " + shlex.quote(script)],
                              check=True, capture_output=True, text=True).stdout.strip()

    shell("set -eu; umask 077; "
          "if [ ! -e cache/combined-input ]; then mkdir cache/combined-input; fi; "
          "[ -d cache/combined-input ] && [ ! -L cache/combined-input ]; "
          f"if [ ! -e {remote} ]; then mkdir {remote}; fi; "
          f"[ -d {remote} ] && [ ! -L {remote} ]")
    for item in plan["files"]:
        target, expected = item["target"], item["sha256"]
        current = shell(f"set -eu; [ ! -L {target} ]; if [ -f {target} ]; then sha256sum {target}; fi")
        if current:
            if current.split()[0] != expected:
                raise ValueError("Existing device input differs; preserve fixture for inspection")
            continue
        partial = target + ".part"
        script = (f"set -eu; umask 077; [ ! -L {partial} ]; "
                  f"if [ -e {partial} ]; then [ -f {partial} ]; rm {partial}; fi; "
                  f"set -C; cat > {partial}")
        # Keep large packages streamed and the encoded temporary file beside
        # its project plan. ASCII transport avoids Windows adb CRLF changes.
        with Path(item["source"]).open("rb") as source, tempfile.TemporaryFile(dir=args.plan.resolve().parent) as encoded:
            base64.encode(source, encoded)
            encoded.seek(0)
            subprocess.run(adb + ["shell", "-T", "base64 -d | run-as app.foldgpt sh -c " + shlex.quote(script)],
                           stdin=encoded, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        copied = shell(f"sha256sum {partial}").split()[0]
        if copied != expected:
            raise ValueError("Device copy digest differs; partial retained")
        shell(f"set -eu; [ ! -e {target} ] && [ ! -L {target} ]; mv {partial} {target}; sync")
    if args.start:
        # Construct the command from validated identity, never trust command text
        # embedded in the local staging-plan document.
        subprocess.run(adb + ["shell", "am", "start-foreground-service", "-n",
            "app.foldgpt/app.foldgpt.install.CombinedPreparationProbeService", "--es", "fixture", fixture,
            "--es", "descriptorSha256", descriptor_hash], check=True)
    print(json.dumps({"fixture": fixture, "started": args.start,
                      "report": "files/.combined-probes/" + fixture + "/report.json"}, indent=2))


if __name__ == "__main__":
    main()
