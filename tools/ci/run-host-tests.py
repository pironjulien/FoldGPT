"""Run the explicit Linux host regression suites, refusing empty collections.

Device qualification and tests requiring separately compiled native fixtures
have their own documented runners. This command does not imply device support.
Each suite runs in a fresh process because some legacy scripts use local imports.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SUITES = (
    "tests/test_provision_keyring.py",
    "tests/test_managed_policy.py",
    "tests/test_gpu_archive.py",
    "tests/test_foldgpt_keyring.py",
    "tests/test_foldgpt_ime.py",
    "tools/browser/test_foldgpt_open.py",
    "tools/context/test_foldgpt_agent_context.py",
    "tools/executor/test_exec_server.py",
    "tools/executor/test_policy_intent.py",
    "tools/executor/test_native_environment.py",
    "tools/executor/test_native_runtime_startup.py",
    "tools/install/test_official_client_package.py",
    "tools/install/test_install_official_client.py",
    "tools/install/test_guest_bundle.py",
    "tools/install/test_inactive_integration_bundle.py",
    "tools/install/test_build_rootfs.py",
    "tools/install/test_verify_rootfs.py",
    "tools/runtime/test_android_memory.py",
    "tools/runtime/test_production_cleanup_receipts.py",
    "tools/runtime/test_qualification_identity.py",
    "tools/runtime/test_runtime_qualification_collector.py",
    "tools/runtime/test_runtime_qualification_staging.py",
    "tools/runtime/test_ripgrep_qualification_staging.py",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=SUITES)
    args = parser.parse_args()
    os.chdir(ROOT)
    if args.suite:
        path = ROOT / args.suite
        sys.path[:0] = [str(ROOT), str(path.parent)]
        suite = unittest.defaultTestLoader.discover(str(path.parent), pattern=path.name)
        count = suite.countTestCases()
        if not count:
            raise RuntimeError(f"No tests collected: {args.suite}")
        print(f"Collected {count} tests: {args.suite}", flush=True)
        return 0 if unittest.TextTestRunner(verbosity=1).run(suite).wasSuccessful() else 1
    failures = []
    for suite in SUITES:
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--suite", suite])
        if result.returncode:
            failures.append(suite)
    if failures:
        print("Failed suites:\n" + "\n".join(failures), file=sys.stderr)
        return 1
    print(f"All {len(SUITES)} Linux host regression suites passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
