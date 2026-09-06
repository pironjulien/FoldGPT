"""Stage the fixed instructions-only official CLI proof over authorized ADB."""
import argparse
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import uuid

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
parser.add_argument("--agents-sha256", required=True)
parser.add_argument("--model", required=True)
args = parser.parse_args()
repo = Path(__file__).resolve().parents[2]
data = (repo / "tools/context/verify_official_context.py").read_bytes().replace(b"\r\n", b"\n")
digest = hashlib.sha256(data).hexdigest()
name = "context-proof-" + uuid.uuid4().hex + ".py"
target = "cache/x11/" + name
script = ("set -eu\numask 077\ntest -d cache/x11\ntest ! -L cache/x11\nset -C\ncat > " + shlex.quote(target)
          + "\ntest \"$(sha256sum " + shlex.quote(target) + " | cut -d ' ' -f 1)\" = " + digest + "\n")
subprocess.run(["adb", "-s", args.serial, "shell", "-T", "run-as app.foldgpt /system/bin/sh -c " + shlex.quote(script)],
               input=data, check=True, timeout=30)
evidence = repo / "downloads/context" / name[:-3]
evidence.mkdir(parents=True)
(evidence / "verify_official_context.py").write_bytes(data)
command = [sys.executable, str(repo / "tools/device-shell.py"), "--serial", args.serial,
           "/usr/bin/python3", "-B", "/tmp/" + name, "--agents-sha256", args.agents_sha256, "--model", args.model]
result = subprocess.run(command, capture_output=True, timeout=240)
(evidence / "stdout.json").write_bytes(result.stdout)
(evidence / "wrapper-stderr.txt").write_bytes(result.stderr)
report = json.loads(result.stdout)
report["hostEvidence"] = str(evidence)
report["executedProofSha256"] = digest
print(json.dumps(report, ensure_ascii=True, indent=2))
raise SystemExit(result.returncode)
