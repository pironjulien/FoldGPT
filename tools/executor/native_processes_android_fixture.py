"""Run the real native lifecycle suite in its fixed Android debug context.

This is backend conformance, not a model request or a Desktop-routing proof.
The service supplies APK-owned sources/programs and a new private directory.
"""
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
        raise KeyboardInterrupt("Android lifecycle diagnostic requested cleanup")

    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--files-helper", type=Path, required=True)
    parser.add_argument("--evidence", type=Path, required=True)
    parser.add_argument("--uid", type=int, required=True)
    parser.add_argument("--address-space-bytes", type=int, required=True)
    args = parser.parse_args()
    evidence = args.evidence.resolve(strict=True)
    require(sys.platform == "android" and args.uid == os.getuid() and args.uid > 0,
            "Lifecycle conformance requires native Android Python and the actual app UID")
    info = evidence.stat()
    require(info.st_uid == args.uid and info.st_mode & 0o077 == 0,
            "Lifecycle evidence directory is not app-private")
    before = observation(android_uid=args.uid)
    (evidence / "android-context-before.json").write_text(json.dumps(before, indent=2) + "\n")
    parent = evidence / "cases"
    parent.mkdir(mode=0o700)
    suite = Path(__file__).with_name("test_native_processes_live.py")
    original_argv = sys.argv
    try:
        sys.argv = [str(suite), "--runner", str(args.runner.resolve(strict=True)),
                    "--fixture", str(args.fixture.resolve(strict=True)),
                    "--files-helper", str(args.files_helper.resolve(strict=True)), "--parent", str(parent),
                    "--evidence", str(evidence / "lifecycle-tests.json"),
                    "--address-space-bytes", str(args.address_space_bytes)]
        try:
            runpy.run_path(str(suite), run_name="__main__")
        except SystemExit as result:
            require(result.code == 0, "The actual native lifecycle backend suite failed")
    finally:
        sys.argv = original_argv
    matrix = json.loads((evidence / "lifecycle-tests.json").read_bytes())
    require(matrix.get("schema") == "foldgpt.native-process-lifecycle.v1"
            and matrix.get("successful") is True and matrix.get("uid") == args.uid
            and matrix.get("observations"), "Lifecycle suite evidence is incomplete")
    require(not list(parent.iterdir()), "Lifecycle suite left private case directories")
    report = {"schema": "foldgpt.native-processes-android.v1", "status": "PASS",
              "uid": args.uid, "observations": len(matrix["observations"]),
              "runnerSha256": file_hash(args.runner), "fixtureSha256": file_hash(args.fixture),
              "filesHelperSha256": file_hash(args.files_helper),
              "suiteSha256": file_hash(suite),
              "lifecycleTestsSha256": file_hash(evidence / "lifecycle-tests.json"),
              "observationBefore": before, "observationAfter": observation(android_uid=args.uid),
              "addressSpaceBytes": args.address_space_bytes,
              "scope": "Actual static native process lifecycle backend; no guest transport or normal model/Desktop route"}
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "observations": report["observations"]}), flush=True)


if __name__ == "__main__":
    main()
