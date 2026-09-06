"""Check development/production separation in an actual built APK, offline.

This checks packaged contents, not signing, provenance, device behavior or
release qualification. Never install the unsigned release-check artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

RUNTIME = {"libXlorie.so", "libandroid-shmem.so", "libfoldgpt-install.so",
           "libproot-loader.so", "libproot-loader32.so", "libproot.so", "libtalloc.so"}
DEBUG_CLASSES = (b"RootfsProbeService", b"ProotStorageProbeService", b"NativeRunnerProbeService", b"GuestAccountProbeService", b"InactivePreparationProbeService",
                 b"NativeFilesRpcProbeService",
                 b"NativePrivateExecProbeService",
                 b"NativeManagedProcessProbeService", b"NativeProbeFiles",
                 b"NativeHttpsAcquisitionProbeService",
                 b"NativeProcessRpcProbeService",
                 b"CombinedPreparationProbeService", b"CombinedPreparationFixture",
                 b"CodexProbeService", b"LandlockProbeReceiver")


def verify(apk, debug):
    with apk.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate APK entries")
            libraries = {name for name in names if name.startswith("lib/") and not name.endswith("/")}
            required = {"lib/arm64-v8a/" + name for name in RUNTIME}
            if not required.issubset(libraries) or (not debug and libraries != required):
                raise ValueError("APK native runtime differs: " + str(sorted(libraries ^ required)))
            dex = b"".join(archive.read(name) for name in names if name.endswith(".dex"))
            for descriptor in DEBUG_CLASSES:
                if (descriptor in dex) != debug:
                    raise ValueError("Wrong diagnostic class separation: " + descriptor.decode())
            file_rpc_assets = {name for name in names if name.startswith("assets/native-files-rpc/") and not name.endswith("/")}
            expected_assets = {"assets/native-files-rpc/" + name for name in (
                "tools/executor/exec_server.py", "tools/executor/native_files.py",
                "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
                "tools/executor/native_files_server.py", "tools/executor/native_files_rpc_fixture.py")}
            if file_rpc_assets != (expected_assets if debug else set()):
                raise ValueError("Wrong native file RPC source asset separation")
            private_assets = {name for name in names if name.startswith("assets/private-exec-probe/") and not name.endswith("/")}
            expected_private = {"assets/private-exec-probe/" + name for name in (
                "tools/executor/exec_server.py", "tools/executor/native_files.py",
                "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
                "tools/executor/native_files_rpc_fixture.py", "tools/executor/private_exec_broker.py",
                "tools/executor/native_file_streams.py",
                "tools/executor/private_exec_fixture.py")}
            if private_assets != (expected_private if debug else set()):
                raise ValueError("Wrong private executor probe asset separation")
            if ("lib/arm64-v8a/libfoldgpt-exec-bridge.so" in libraries) != debug:
                raise ValueError("Wrong GNU bridge diagnostic separation")
            if ("lib/arm64-v8a/libfoldgpt_file_handle.so" in libraries) != debug:
                raise ValueError("Wrong native streaming helper diagnostic separation")
            managed_assets = {name for name in names if name.startswith('assets/managed-process-probe/') and not name.endswith('/')}
            expected_managed = {'assets/managed-process-probe/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
                'tools/executor/native-managed-test.py', 'tools/executor/native_managed_android_fixture.py')}
            if managed_assets != (expected_managed if debug else set()):
                raise ValueError('Wrong native managed process probe asset separation')
            for name in ('libfoldgpt-native-managed-runner.so', 'libfoldgpt-native-managed-fixture.so'):
                if ('lib/arm64-v8a/' + name in libraries) != debug:
                    raise ValueError('Wrong managed process diagnostic native separation')
            process_assets = {name for name in names if name.startswith('assets/process-rpc-probe/') and not name.endswith('/')}
            expected_process = {'assets/process-rpc-probe/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
                'tools/executor/native_processes.py', 'tools/executor/test_native_processes_live.py',
                'tools/executor/native_processes_android_fixture.py')}
            if process_assets != (expected_process if debug else set()):
                raise ValueError('Wrong native process lifecycle probe asset separation')
            for name in ('libfoldgpt-native-process-runner.so', 'libfoldgpt-native-process-fixture.so'):
                if ('lib/arm64-v8a/' + name in libraries) != debug:
                    raise ValueError('Wrong native process lifecycle diagnostic separation')
            android_python = {name for name in names if name.startswith("assets/native-python/") and not name.endswith("/")}
            python_notices = {name for name in names if name.startswith("assets/native-python-notices/") and not name.endswith("/")}
            python_libs = {"lib/arm64-v8a/" + name for name in (
                "libfoldgpt_python.so", "libpython3.14.so", "libcrypto_python.so", "libssl_python.so", "libsqlite3_python.so")}
            if debug:
                if (not python_libs.issubset(libraries)
                        or "assets/native-python-notices/sources.json" not in python_notices
                        or "assets/native-python/lib/python3.14/os.py" not in android_python
                        or "assets/native-python/lib/python3.14/lib-dynload/_asyncio.cpython-314-aarch64-linux-android.so" not in android_python):
                    raise ValueError("Native Android Python diagnostic inputs are incomplete")
            elif android_python or python_notices or libraries & python_libs:
                raise ValueError("Native Android Python diagnostic leaked into release")
    return {"apk_sha256": digest, "variant": "debug" if debug else "release",
            "native_libraries": len(libraries), "diagnostic_separation": "PASS",
            "limit": "Package contents only, not a binary release qualification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    print(json.dumps(verify(args.apk, args.debug), indent=2))
