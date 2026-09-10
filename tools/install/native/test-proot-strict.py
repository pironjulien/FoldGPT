"""Execute real unprivileged Linux processes against baseline and opt-in PRoot."""
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import struct
import subprocess
import sys
import time


work = Path(sys.argv[1]).resolve()
if os.getuid() == 0:
    raise SystemExit("This test must run as a real nonroot user")
guest = str(work / "guest")
fixture = work / "fixture"
fixture.mkdir()
for name in ("source", "target"):
    (fixture / name).mkdir()
    (fixture / name / "marker").write_text(name + "\n", encoding="utf-8")
records = []
spec = importlib.util.spec_from_file_location("sigterm_checks", work / "recipe/test-proot-sigterm.py")
lifecycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lifecycle)
lifecycle_records = []


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(label, command, acceleration, policy=None):
    env = {"PATH": "/usr/bin:/bin", "HOME": str(work), "LC_ALL": "C", "TZ": "UTC", "TMPDIR": str(work)}
    if not acceleration:
        env["PROOT_NO_SECCOMP"] = "1"
    if policy:
        command = [guest, "launch", policy, *command]
    process = subprocess.Popen(command, cwd=work, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
    try:
        stdout, stderr = process.communicate(timeout=45)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate()
        raise RuntimeError(f"timeout in {label}: {stdout!r} {stderr!r}")
    record = {"label": label, "command": command, "environment": env,
              "acceleration": acceleration, "inherited_policy": policy, "returncode": process.returncode,
              "stdout_hex": stdout.hex(), "stderr": stderr.decode("utf-8", "replace")}
    records.append(record)
    (work / "observations.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    return process.returncode, stdout, record


def proot(mode, arguments):
    variant = "baseline" if mode == "baseline" else "patched"
    prefix = [str(work / variant / "src/proot"), "--kill-on-exit", "-r", "/"]
    if mode == "strict":
        prefix.append("--strict-sandbox")
    return prefix + arguments


def call(mode, name, acceleration, policy=None, through_fork=False):
    command = [guest, "call", name, str(fixture)]
    if through_fork:
        command = [guest, "fork-exec", *command]
    return run(f"{mode}/{name}/fork={through_fork}", proot(mode, command), acceleration, policy)


def fields(output):
    return {key: int(value) for key, value in re.findall(rb"([a-z_]+)=(-?\d+)", output)}


def successful(record):
    require(record[0] == 0, f"unexpected process exit: {record[2]}")
    return fields(record[1])


def check_result(record, result, error):
    values = successful(record)
    require(values.get(b"result") == result and values.get(b"errno") == error, f"wrong kernel result: {record[2]}")


def check_signal(record, syscall):
    require(record[0] == 77 and len(record[1]) == 12, f"missing real SIGSYS: {record[2]}")
    require(struct.unpack("=iii", record[1]) == (signal.SIGSYS, 1, syscall), f"wrong SIGSYS siginfo: {record[2]}")


def cancellation(acceleration, mode, kill_on_exit=True):
    directory = work / f"lifecycle-{acceleration}-{mode}-{kill_on_exit}"
    directory.mkdir(mode=0o700)
    command = proot("strict", ["-w", str(directory), str(work / "sigterm-guest"), mode, str(directory)])
    if not kill_on_exit:
        command.remove("--kill-on-exit")
    env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": str(directory)}
    if not acceleration:
        env["PROOT_NO_SECCOMP"] = "1"
    with (directory / "runtime.log").open("wb") as log:
        process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
        before = {}
        try:
            lifecycle.wait_until(lambda: (directory / "ready").exists(), "strict native tree did not start")
            if mode != "exit":
                lifecycle.wait_until(lambda: len(lifecycle.records(directory)) >= 4, "strict descendants missing")
                roles = lifecycle.records(directory)
                for pid, role in roles.items():
                    info = lifecycle.proc_info(pid)
                    require(info is not None, "strict guest's real PID is absent")
                    require(role["termBlocked"] == 0, "guest inherited launch signal mask")
                    before[pid] = info
                require(any(role["role"] == "detached-grandchild" and before[pid]["session"] == pid for pid, role in roles.items()),
                        "strict descendant did not leave the session")
                process.send_signal(signal.SIGTERM)
                if not kill_on_exit:
                    time.sleep(0.1)
                    require(process.poll() is None, "strict changed SIGTERM behavior without --kill-on-exit")
                    process.send_signal(signal.SIGQUIT)
            process.wait(timeout=8)
            lifecycle.no_remaining(process, before)
            if mode == "exit":
                require(process.returncode == 23, "strict lost real main exit code")
            sizes = {path.name: path.stat().st_size for path in directory.glob("beat-*")}
            time.sleep(0.1)
            require(sizes == {path.name: path.stat().st_size for path in directory.glob("beat-*")}, "strict descendants still writing")
            lifecycle_records.append({"command": command, "environment": env, "returncode": process.returncode,
                                      "before": before, "roles": lifecycle.records(directory), "pass": True})
            (work / "lifecycle.json").write_text(json.dumps(lifecycle_records, indent=2) + "\n", encoding="utf-8")
        finally:
            lifecycle.cleanup(process)


syscalls = {"unshare": 272, "setns": 308, "mount": 165, "umount": 166,
            "pivot": 155, "clone": 56, "clone3": 435, "setgroups": 116, "get-nnp": 157}
try:
    require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0, "real subreaper setup failed")
    for acceleration in (False, True):
        # A real inherited BPF denial is distinguishable from the kernel's usual
        # EPERM. Strict must preserve EACCES; legacy control exposes the old lie.
        for name, number in syscalls.items():
            baseline = call("baseline", name, acceleration, "errno")
            legacy = call("legacy", name, acceleration, "errno")
            require(baseline[:2] == legacy[:2], f"legacy changed for {name}")
            strict = call("strict", name, acceleration, "errno")
            check_result(strict, -1, errno.EACCES)
            check_result(call("strict", name, acceleration, "errno", True), -1, errno.EACCES)
            if name == "clone3":
                if not acceleration:
                    require(successful(baseline).get(b"flags_unchanged") == 0, "control did not expose legacy clone3 mutation")
                require(successful(strict).get(b"flags_unchanged") == 1, "strict modified caller's clone3 buffer")
            # With RET_TRACE acceleration an inherited RET_ERRNO wins before
            # syscall entry can be translated. The no-acceleration control is
            # the path used with USER_NOTIF and exposes the existing simulation.
            if not acceleration and name in {"unshare", "setns", "mount", "umount", "pivot", "get-nnp"}:
                check_result(baseline, 0, 0)
            if not acceleration and name == "clone":
                check_result(baseline, 1, 0)
            trapped = call("strict", name, acceleration, "trap")
            check_signal(trapped, number)
        # Real successful or failed no-op namespace operation, without any filter.
        direct = run("native/unshare-zero", [guest, "call", "unshare-zero", str(fixture)], acceleration)
        strict = call("strict", "unshare-zero", acceleration)
        require(direct[:2] == strict[:2], "strict changed actual unshare(0) result")

        for policy in (None, "nnp"):
            for mode in ("baseline", "legacy", "strict"):
                for operation in ("nnp", "nnp-set"):
                    result = run(f"{mode}/{operation}", proot(mode, [guest, operation]), acceleration, policy)
                    data = successful(result)
                    if mode == "strict" or operation == "nnp-set":
                        require(data[b"result"] == data[b"actual"], f"NNP is not actual /proc state: {result[2]}")
                    else:
                        require(data[b"result"] == 0, f"legacy NNP behavior changed: {result[2]}")
            inherited = run("strict/fork-exec-nnp", proot("strict", [guest, "fork-exec", guest, "nnp"]), acceleration, policy)
            data = successful(inherited)
            require(data[b"result"] == data[b"actual"], "NNP truth lost after fork/exec")
        check_result(call("strict", "invalid-nnp", acceleration), -1, errno.EINVAL)
        check_result(call("strict", "dumpable", acceleration), -1, errno.EOPNOTSUPP)
        check_result(call("strict", "robust", acceleration), -1, errno.ENOSYS)
        check_result(call("strict", "openat2", acceleration), 0, 0)
        check_result(call("strict", "openat2-resolve", acceleration), -1, errno.EOPNOTSUPP)

        for style in ("open", "openat", "numeric"):
            for name in ("uid_map", "gid_map", "setgroups"):
                for operation in ("read", "write"):
                    arguments = [guest, "maps", style, operation, name]
                    direct = run(f"native/{style}/{operation}/{name}", arguments, acceleration)
                    strict = run(f"strict/{style}/{operation}/{name}", proot("strict", arguments), acceleration)
                    require(direct[:2] == strict[:2], f"proc mapping virtualized: {strict[2]}")
                    if operation == "write":
                        require(successful(strict)[b"result"] == -1, "invalid map write unexpectedly succeeded")
                    else:
                        require(successful(strict)[b"result"] > 0, "proc mapping read did not return actual data")
                    baseline = run(f"baseline/{style}/{operation}/{name}", proot("baseline", arguments), acceleration)
                    legacy = run(f"legacy/{style}/{operation}/{name}", proot("legacy", arguments), acceleration)
                    require(baseline[:2] == legacy[:2], "legacy proc mapping behavior changed")
                    check_result(baseline, 0 if operation == "read" else 8, 0)

        # A real GNU C build with a bind, cwd translation, Bash pipeline,
        # source edit, executable creation, pthread and propagated exit status.
        project = work / ("project-fast" if acceleration else "project-traced")
        project.mkdir()
        (project / "program.c").write_text('''#include <pthread.h>
#include <stdio.h>
static void *worker(void *p) { *(int *)p = 21; return 0; }
int main(void) { pthread_t thread; int value = 0;
if (pthread_create(&thread, 0, worker, &value) || pthread_join(thread, 0)) return 2;
printf("native-gnu-v1 %d\\n", value); return value == 21 ? 0 : 3; }
''', encoding="utf-8")
        script = '''set -euo pipefail
test "$PWD" = /foldgpt-strict-work
sed -i s/native-gnu-v1/native-gnu-v2/ program.c
cc -Wall -Wextra -Werror -pthread program.c -o program
./program | tee result.txt
test "$(cat result.txt)" = 'native-gnu-v2 21'
'''
        compiled = run("strict/gnu-compile", proot("strict", ["-b", f"{project}:/foldgpt-strict-work", "-w", "/foldgpt-strict-work", "/bin/bash", "-c", script]), acceleration)
        successful(compiled)
        require(compiled[1] == b"native-gnu-v2 21\n", "GNU executable returned wrong output")
        require((project / "program").read_bytes()[:4] == b"\x7fELF", "compiler did not create an ELF")
        require("native-gnu-v2" in (project / "program.c").read_text(encoding="utf-8"), "Bash did not edit source")
        nonzero = run("strict/exit23", proot("strict", ["/bin/bash", "-c", "exit 23"]), acceleration)
        require(nonzero[0] == 23, "lost real command exit status")
        for mode in ("wait", "storm", "exit"):
            cancellation(acceleration, mode)
        cancellation(acceleration, "wait", kill_on_exit=False)

    for option in ("-0", "-i", "-S"):
        fake = [option] + (["0:0"] if option == "-i" else ["/"] if option == "-S" else [])
        for order in (["--strict-sandbox", *fake], [*fake, "--strict-sandbox"]):
            result = run("strict/reject-fake-id", [str(work / "patched/src/proot"), *order, "/bin/true"], False)
            require(result[0] != 0 and "incompatible" in result[2]["stderr"], "fake-id was accepted in strict mode")
    for name in ("source", "target"):
        require((fixture / name / "marker").read_text(encoding="utf-8") == name + "\n", "mount probes changed host data")
    report = {"status": "PASS", "uid": os.getuid(), "observations": len(records), "lifecycle_cases": len(lifecycle_records),
              "scope": "real nonroot Linux x86_64 syscalls and GNU builds; no Android execution",
              "files": {str(path.relative_to(work)): hashlib.sha256(path.read_bytes()).hexdigest()
                        for path in [work / "source.tar", work / "guest", work / "sigterm-guest", work / "baseline/src/proot", work / "patched/src/proot", work / "recipe/proot-strict-sandbox.patch"]}}
    (work / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"PASS: {len(records)} native observations and {len(lifecycle_records)} lifecycle cases under uid {os.getuid()}; strict/legacy, errno/SIGSYS, proc mappings, NNP, forks/execs and GNU compiler.")
except BaseException as error:
    (work / "failure.txt").write_text(str(error) + "\n", encoding="utf-8")
    raise
