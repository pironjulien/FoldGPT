"""Run the desktop JVM lifecycle tests without Android's restricted Java modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    classes, temporary = output / "classes", output / "tmp"
    classes.mkdir(); temporary.mkdir()
    dependencies = ROOT / "work/build-cache/gradle/caches/modules-2/files-2.1"
    jars = []
    for relative, name in (("junit/junit/4.13.2", "junit-4.13.2.jar"),
                           ("org.hamcrest/hamcrest-core/1.3", "hamcrest-core-1.3.jar"),
                           ("org.json/json/20260719", "json-20260719.jar")):
        found = list((dependencies / relative).glob("*/" + name))
        if len(found) != 1:
            raise ValueError("Required local JVM test dependency differs: " + name)
        jars.append(str(found[0]))
    names = ("RuntimeExitGate", "NativeSessionObservation", "RuntimeShutdownGate")
    sources = [ROOT / ("android/app/src/" + tree + "/java/app/foldgpt/" + name + suffix + ".java")
               for name in names for tree, suffix in (("main", ""), ("test", "Test"))]
    cp = os.pathsep.join(jars)
    commands = [[shutil.which("javac"), "-encoding", "UTF-8", "-source", "17", "-target", "17",
                 "-cp", cp, "-d", str(classes), *map(str, sources)],
                [shutil.which("java"), "-Djava.io.tmpdir=" + str(temporary), "-cp", str(classes) + os.pathsep + cp,
                 "org.junit.runner.JUnitCore", *["app.foldgpt." + name + "Test" for name in names]]]
    for label, command in zip(("compile", "test"), commands):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60)
        (output / (label + ".log")).write_bytes(result.stdout + result.stderr)
        (output / (label + "-command.json")).write_text(json.dumps(command, indent=2) + "\n")
        result.check_returncode()
    report = {"success": True, "androidExecuted": False,
        "sourceSha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "result": (output / "test.log").read_text()}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
