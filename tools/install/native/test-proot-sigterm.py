#!/usr/bin/env python3
"""Real nonroot PRoot cancellation regression, including independent /proc checks."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time


def require(ok, message):
    if not ok:
        raise AssertionError(message)


def wait_until(predicate, message, timeout=8):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(message)


def proc_info(pid):
    try:
        value = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
        return {"state": value[0], "parent": int(value[1]), "session": int(value[3]),
                "start": int(value[19])}
    except FileNotFoundError:
        return None


def direct_children():
    return [int(value) for value in Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()]


def reap():
    while True:
        try:
            if os.waitpid(-1, os.WNOHANG)[0] == 0:
                return
        except ChildProcessError:
            return


def cleanup(process):
    # Error-path cleanup owns these direct/adopted fixture descendants only.
    # The tracer is always asked to reap through SIGQUIT, never SIGKILL.
    if process.poll() is None:
        process.send_signal(signal.SIGQUIT)
        try:
            process.wait(timeout=8)
        except subprocess.TimeoutExpired:
            pass
    for pid in direct_children():
        if pid != process.pid:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    wait_until(lambda: (reap(), not direct_children())[1], "fixture cleanup left descendants")


def records(directory):
    result = {}
    for path in directory.glob("pid-*"):
        fields = path.read_text().split()
        if len(fields) != 5:
            continue
        role, pid, parent, session, blocked = fields
        result[int(pid)] = {"role": role, "reportedParent": int(parent),
                            "reportedSession": int(session), "termBlocked": int(blocked)}
    return result


def no_remaining(process, before):
    require(process.poll() is not None, "tracer is still running")
    def complete():
        reap()
        if direct_children():
            return False
        for pid, value in before.items():
            current = proc_info(pid)
            if current is not None and current["start"] == value["start"]:
                return False
        return True
    wait_until(complete, "tracer exited while a fixture descendant survived")


def main():
    require(sys.platform == "linux" and os.getuid() != 0, "requires actual nonroot Linux execution")
    require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0, "subreaper setup failed")
    work = Path(sys.argv[1]).resolve(strict=True)
    evidence = {"uid": os.getuid(), "kernel": os.uname().release, "tests": []}
    number = 0

    def run(variant, *, option=True, sig=signal.SIGTERM, ignored=False, mode="wait", no_seccomp=False, early=False):
        nonlocal number
        number += 1
        name = f"{number:02d}-{variant}-{mode}-{sig.name}" + ("-early" if early else "")
        directory = work / name
        directory.mkdir(mode=0o700)
        env = {"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TMPDIR": str(directory)}
        if no_seccomp:
            env["PROOT_NO_SECCOMP"] = "1"
        if early:
            env.update(LD_PRELOAD=str(work / "fork-signal.so"),
                       FOLDGPT_TEST_FORK_RECORD=str(directory / "fork-child"))
        command = [str(work / variant / "src/proot")]
        if option:
            command.append("--kill-on-exit")
        command += ["-r", "/", "-w", str(directory), str(work / "guest"), mode, str(directory)]
        with (directory / "runtime.log").open("wb") as log:
            process = subprocess.Popen(command, env=env, stdout=log, stderr=subprocess.STDOUT)
            before = {}
            try:
                if early:
                    wait_until(lambda: (directory / "fork-child").exists(), "first fork not observed")
                    pid = int((directory / "fork-child").read_text())
                    observed = proc_info(pid)
                    if observed:
                        before[pid] = observed
                    process.wait(timeout=8)
                    no_remaining(process, before)
                    require(process.returncode not in (0, -signal.SIGTERM),
                            "early cancellation bypassed the patched cleanup handler")
                    require("signal 15 received" in (directory / "runtime.log").read_text(),
                            "early SIGTERM was not handled by the tracer")
                    require(not (directory / "ready").exists(), "cancelled launch reached guest work")
                else:
                    wait_until(lambda: (directory / "ready").exists(), "native guest tree not ready")
                    if mode != "exit":
                        wait_until(lambda: len(records(directory)) >= 4, "guest role records missing")
                        roles = records(directory)
                        for pid, role in roles.items():
                            info = proc_info(pid)
                            require(info is not None, "reported native process does not exist")
                            require(role["termBlocked"] == 0, "launch masking leaked into the guest")
                            require(info["session"] == role["reportedSession"], "session report mismatch")
                            before[pid] = info
                        require(any(value["role"] == "detached-grandchild" and
                                    value["reportedSession"] == pid for pid, value in roles.items()),
                                "detached grandchild was not actually a session leader")
                        started = time.monotonic()
                        process.send_signal(sig)
                        if ignored:
                            time.sleep(0.2)
                            require(process.poll() is None, "upstream SIGTERM ignore behavior changed")
                            first = {path.name: path.stat().st_size for path in directory.glob("beat-*")}
                            time.sleep(0.2)
                            require(first and all((directory / name).stat().st_size > size for name, size in first.items()),
                                    "ignored-signal descendants stopped running")
                            process.send_signal(signal.SIGQUIT)
                        process.wait(timeout=8)
                        no_remaining(process, before)
                        elapsed = time.monotonic() - started
                    else:
                        process.wait(timeout=8)
                        require(process.returncode == 23, "normal main-command exit status changed")
                        no_remaining(process, before)
                        elapsed = None
                    # Independently prove no descendant continues modifying its output.
                    sizes = {path.name: path.stat().st_size for path in directory.glob("beat-*")}
                    time.sleep(0.1)
                    require(sizes == {path.name: path.stat().st_size for path in directory.glob("beat-*")},
                            "guest writes continued after tracer completion")
                item = {"name": name, "killOnExit": option, "seccompDisabled": no_seccomp,
                        "expectedTermIgnored": ignored, "exitCode": process.returncode,
                        "observedPids": before, "roles": records(directory), "pass": True}
                if not early:
                    item["secondsThroughReap"] = elapsed
                evidence["tests"].append(item)
                print(f"PASS {name}", flush=True)
            finally:
                cleanup(process)

    run("baseline", ignored=True)
    run("patched", option=False, ignored=True)
    run("patched", sig=signal.SIGQUIT)
    run("patched")
    run("patched", no_seccomp=True)
    run("patched", mode="exit")
    for unused in range(8):
        run("patched", mode="storm")
    for unused in range(8):
        run("patched", early=True)
    for variant in ("baseline", "patched"):
        path = work / variant / "src/proot"
        evidence[variant + "Sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (work / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(f"PASS {len(evidence['tests'])} real PRoot cases; uid={os.getuid()}; all descendants reaped", flush=True)


if __name__ == "__main__":
    main()
