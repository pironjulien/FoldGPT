"""Fixed Android Bionic/PRoot composite conformance; no Desktop or model request."""
import argparse
import json
import os
from pathlib import Path
import runpy
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from tools.executor.native_files_rpc_fixture import file_hash, observation, require


def main():
    def terminate(_number, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("Android composite diagnostic requested cleanup")
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runner", "fixture", "files-helper", "handle-helper", "bridge", "evidence", "android-home",
                 "native-directory", "guest-runtime", "proot-compat"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--address-space-bytes", type=int, required=True)
    args = parser.parse_args()
    require(sys.platform == "android" and args.uid == os.getuid() and args.uid > 0,
        "Composite conformance requires real Android Python and its application UID")
    evidence = args.evidence.resolve(strict=True)
    require(evidence.stat().st_uid == args.uid and not evidence.stat().st_mode & 0o077,
        "Composite evidence is not app-private")
    before = observation(android_uid=args.uid)
    (evidence / "android-context-before.json").write_text(json.dumps(before, indent=2) + "\n")
    parent = evidence / "cases"; parent.mkdir(mode=0o700)
    suite = Path(__file__).with_name("test_native_executor_transport.py")
    original = sys.argv
    try:
        sys.argv = [str(suite), "--parent", str(parent), "--retain-cases", "--android-uid", str(args.uid),
            "--address-space-bytes", str(args.address_space_bytes), "--evidence", str(evidence / "composite-tests.json")]
        for name in ("runner", "fixture", "files-helper", "handle-helper", "bridge", "android-home",
                     "native-directory", "guest-runtime", "proot-compat"):
            sys.argv.extend(["--" + name, str(getattr(args, name.replace("-", "_")).resolve(strict=True))])
        try:
            runpy.run_path(str(suite), run_name="__main__")
        except SystemExit as result:
            require(result.code == 0, "The actual Android composite transport suite failed")
    finally:
        sys.argv = original
    matrix = json.loads((evidence / "composite-tests.json").read_bytes())
    require(matrix.get("passed") is True and matrix.get("tests") == 9
        and matrix.get("uid") == args.uid and len(matrix.get("observations", [])) == 9,
        "Composite suite evidence is incomplete")
    report = {"schema": "foldgpt.native-executor-android.v1", "status": "PASS", "uid": args.uid,
        "testsRun": 9, "nativeProcessProfile": "managed-process-v2", "retainedCases": 9,
        "suiteSha256": file_hash(suite), "matrixSha256": file_hash(evidence / "composite-tests.json"),
        "observationBefore": before, "observationAfter": observation(android_uid=args.uid),
        "addressSpaceBytes": args.address_space_bytes,
        "programsSha256": {name: file_hash(getattr(args, name)) for name in
            ("runner", "fixture", "files_helper", "handle_helper", "bridge")},
        "scope": "Actual stdio/GNU PRoot bridge/native Bionic composite diagnostic; no Desktop environment or model task"}
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "testsRun": 9, "retainedCases": 9}), flush=True)


if __name__ == "__main__":
    main()
