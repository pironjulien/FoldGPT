"""Fixed Android GNU backend calls; no account, model or normal UI routing."""
import argparse
import json
import os
from pathlib import Path
import runpy
import signal
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from tools.executor.native_files_rpc_fixture import file_hash, observation, require
from gnu_runtime_address import runtime_address_admission


def main():
    def terminate(_number, _frame):
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise KeyboardInterrupt("Android GNU diagnostic requested cleanup")
    signal.signal(signal.SIGTERM, terminate)
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("runner", "files-helper", "proot", "loader", "loader32", "rootfs", "evidence"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--uid", type=int, required=True)
    address = parser.add_mutually_exclusive_group(required=True)
    address.add_argument("--address-space-bytes", type=int)
    address.add_argument("--android-runtime-address-budget", action="store_true")
    args = parser.parse_args()
    require(sys.platform == "android" and args.uid == os.getuid() and args.uid > 0,
        "GNU backend diagnostic requires the real Android interpreter and app UID")
    evidence = args.evidence.resolve(strict=True)
    address_admission = runtime_address_admission(args.proot) if args.android_runtime_address_budget else None
    if address_admission is not None:
        args.address_space_bytes = address_admission['addressSpaceBytes']
    before = observation(android_uid=args.uid)
    (evidence / "android-context-before.json").write_text(json.dumps(before, indent=2) + "\n")
    parent = evidence / "cases"
    parent.mkdir(mode=0o700)
    suite = Path(__file__).with_name("test_gnu_process_adapter.py")
    original = sys.argv
    try:
        sys.argv = [str(suite), "--parent", str(parent), "--evidence", str(evidence / "gnu-tests.json"),
            "--address-space-bytes", str(args.address_space_bytes)]
        for name in ("runner", "files-helper", "proot", "loader", "loader32", "rootfs"):
            sys.argv.extend(["--" + name, str(getattr(args, name.replace("-", "_")).resolve(strict=True))])
        sys.path.insert(0, str(suite.parent))
        try:
            runpy.run_path(str(suite), run_name="__main__")
        except SystemExit as result:
            require(result.code in (0, None), "Actual Android GNU suite failed")
        finally:
            sys.path.pop(0)
    finally:
        sys.argv = original
    matrix = json.loads((evidence / "gnu-tests.json").read_bytes())
    require(matrix.get("status") == "PASS" and matrix.get("uid") == args.uid,
        "GNU suite has no completed success report")
    report = {"schema": "foldgpt.gnu-managed-android.v1", "status": "PASS", "uid": args.uid,
        "suiteSha256": file_hash(suite), "matrixSha256": file_hash(evidence / "gnu-tests.json"),
        "observationBefore": before, "observationAfter": observation(android_uid=args.uid),
        "addressSpaceBytes": args.address_space_bytes,
        "addressAdmission": address_admission,
        "programsSha256": {name: file_hash(getattr(args, name)) for name in
            ("runner", "files_helper", "proot", "loader", "loader32")},
        "scope": "Actual native GNU backend diagnostic; no normal model or Desktop routing"}
    (evidence / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"status": "PASS", "observations": len(matrix.get("observations", []))}), flush=True)


if __name__ == "__main__":
    main()
