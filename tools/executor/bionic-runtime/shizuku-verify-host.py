"""Exercise the supervisor on the PC only; never contacts an Android device."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

here = Path(__file__).resolve().parent
destination = Path(tempfile.mkdtemp(prefix="foldgpt-shizuku-host-", dir="/var/tmp"))
python = Path(shutil.which("python3")).resolve()
cases = {
    "qualification": (here.joinpath("shizuku-qualification.py").read_text(), 0, "exited"),
    "output-limit": ("import os\nos.write(1, b'x' * 100000)\n", 70, "output-limit"),
    "descendant-cleanup": (
        "import subprocess,sys,json\n"
        "p=subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)'],env={})\n"
        "print(json.dumps({'descendantPid':p.pid}),flush=True)\n", 0, "exited"),
    "timeout": ("import time\ntime.sleep(40)\n", 124, "timeout"),
    "cancel": ("import time\nprint('ready',flush=True)\ntime.sleep(40)\n", 70, "cancelled"),
}
results = []
for name, (fixture, expected_exit, expected_outcome) in cases.items():
    case = destination / name
    case.mkdir(mode=0o700)
    root = case / "lab"
    root.mkdir(mode=0o700)
    case.joinpath("shizuku-fixture.h").write_text(
        "#define SHIZUKU_FIXTURE " + json.dumps(fixture) + "\n")
    shutil.copyfile(here.parent / "native-runner-seccomp.h", case / "native-runner-seccomp.h")
    subprocess.run([
        "gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-function", "-DSHIZUKU_HOST_TEST=1",
        f"-DSHIZUKU_EXPECT_UID={os.getuid()}",
        '-DSHIZUKU_HOST_PYTHON="' + str(python) + '"',
        '-DSHIZUKU_ROOT="' + str(root) + '"',
        "-I" + str(case), str(here / "shizuku-probe.c"), "-o", str(case / "probe"),
    ], check=True)
    started = time.monotonic()
    if name == "cancel":
        process = subprocess.Popen([str(case / "probe")], text=True,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        prefix = ""
        while True:
            line = process.stdout.readline()
            assert line, prefix
            prefix += line
            if line.strip() == "ready":
                break
        process.send_signal(signal.SIGTERM)
        output, error = process.communicate(timeout=6)
        execution = subprocess.CompletedProcess(process.args, process.returncode, prefix + output, error)
    else:
        execution = subprocess.run([str(case / "probe")], text=True, capture_output=True, timeout=40)
    elapsed = time.monotonic() - started
    case.joinpath("stdout.txt").write_text(execution.stdout)
    case.joinpath("stderr.txt").write_text(execution.stderr)
    records = []
    for line in execution.stdout.splitlines():
        # The output-limit fixture writes an unterminated line on purpose.
        marker = line.find('{"type":"probe-result"')
        if marker >= 0:
            line = line[marker:]
        try:
            records.append(json.loads(line))
        except ValueError:
            pass
    report = next(row for row in reversed(records) if row.get("type") == "probe-result")
    assert execution.returncode == expected_exit, (name, execution, report)
    assert report["outcome"] == expected_outcome, (name, report)
    assert report["cleanup_complete"], (name, report)
    assert not Path(f'/proc/{report["childPid"]}').exists(), (name, report)
    if name == "descendant-cleanup":
        descendant = next(row["descendantPid"] for row in records if "descendantPid" in row)
        assert not Path(f"/proc/{descendant}").exists(), (name, descendant)
    if name == "qualification":
        assert report["success"], report
        assert root.joinpath("workspace/dist/calculator.pyz").is_file()
        # Freshness is an admission rule: a second invocation cannot reuse the
        # existing project as an arbitrary input or execute anything again.
        rejected = subprocess.run([str(case / "probe")], capture_output=True, text=True, timeout=5)
        assert rejected.returncode == 70 and "fresh-workspace" in rejected.stderr, rejected
    if name == "timeout":
        assert 29 <= elapsed < 36, elapsed
    results.append({"case": name, "seconds": round(elapsed, 3), "report": report})
    print(json.dumps(results[-1]), flush=True)
destination.joinpath("results.json").write_text(json.dumps(results, indent=2) + "\n")
print(destination)
