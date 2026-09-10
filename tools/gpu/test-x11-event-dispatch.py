#!/usr/bin/env python3
"""Exercise the actual server dispatcher with socketpairs and observable X stubs.

This checks scheduling/ownership/order; it is not an XKB or live-client test.
"""
import pathlib
import subprocess

repo = pathlib.Path(__file__).resolve().parents[2]
native = repo / "vendor/termux-x11/lorie/src/main/cpp/lorie"
output = repo / "downloads/gpu/x11/host-tests"
output.mkdir(parents=True, exist_ok=True)
source = (native / "cmdentrypoint.cpp").read_text()
start = source.index("static LorieEventReader* connectionReader")
end = source.index("\nvoid lorieSendClipboardData", start)
(output / "dispatcher-under-test.inc").write_text(source[start:end])
subprocess.run(["c++", "-std=c++17", "-pthread", "-Wall", "-Wextra", "-Werror",
                "-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g",
                "-I", str(native), "-I", str(output),
                str(repo / "tools/gpu/test-x11-event-dispatch.cpp"),
                "-o", str(output / "test-x11-event-dispatch")], check=True)
subprocess.run([str(output / "test-x11-event-dispatch")], check=True, timeout=30)
