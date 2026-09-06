"""Validate the parent's actual NativeRun transport against the real backend."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from native_client import NativeRun


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    args = parser.parse_args()
    if os.geteuid() == 0:
        raise SystemExit("Non-root host required")
    spec = importlib.util.spec_from_file_location("runner_fixture", HERE / "native-runner-test.py")
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    with tempfile.TemporaryDirectory(prefix="foldgpt-native-client-live-") as temporary:
        root = Path(temporary)
        manifest = {"schema": "foldgpt.native-runner.v1", "policy": "landlock-basic-data-v1", "metadata": "visible",
                    "network": "deny", "ipc": "private-pipes-only", "workspace": str(root), "cwd": str(root),
                    "executable": str(Path("/bin/sh").resolve()), "argv": ["/bin/sh", "-c", "printf real-client > result.txt; printf hello; printf warning >&2"],
                    "env": {"PATH": "/usr/bin:/bin", "LANG": "C"},
                    "grants": [{"kind": "directory", "path": str(root), "access": ["read", "write"]}, *fixture.runtime_grants("/bin/sh")],
                    "limits": {"wallMs": 2000, "outputBytes": 1048576, "addressSpaceBytes": 268435456, "fileBytes": 1048576, "openFiles": 64, "uidProcesses": 64}}
        captured = {"stdout": bytearray(), "stderr": bytearray()}
        with NativeRun(args.binary.resolve(), manifest) as run:
            result = run.wait(lambda event: captured[event.stream].extend(event.data))
        assert result["exitCode"] == 0 and result["cleanupComplete"]
        assert captured == {"stdout": b"hello", "stderr": b"warning"}
        assert (root / "result.txt").read_bytes() == b"real-client"
        print("PASS: actual NativeRun client + native backend + real shell/file and independent output counts")
        for name, command in (("exit7", "exit 7"), ("timeout", "while :; do :; done"), ("signal", "kill -TERM $$")):
            manifest["argv"][-1] = command
            with NativeRun(args.binary.resolve(), manifest) as run:
                result = run.wait()
            if name == "exit7": assert result["outcome"] == "exited" and result["exitCode"] == 7
            elif name == "timeout": assert result["outcome"] == "timeout" and result["cleanupComplete"]
            else: assert result["outcome"] == "exited" and result["signal"] == 15
            print(f"PASS: actual client validates {name} result")


if __name__ == "__main__":
    main()
