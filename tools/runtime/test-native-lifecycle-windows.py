"""Run the desktop JVM lifecycle tests without Android's restricted Java modules."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
DEPENDENCIES = {
    "junit-4.13.2.jar": ("junit/junit/4.13.2", "8e495b634469d64fb8acfa3495a065cbacc8a0fff55ce1e31007be4c16dc57d3"),
    "hamcrest-core-1.3.jar": ("org/hamcrest/hamcrest-core/1.3", "66fdef91e9739348df7a096aa384a5685f4e875584cce89386a7a47251c4d8e9"),
    "json-20260719.jar": ("org/json/json/20260719", "c243f45f9590c12694a4142ed3f07fc70dfb71e4daebd05ae234bf92a2da92a6"),
}


def fetch_dependency(name):
    relative, expected = DEPENDENCIES[name]
    cache = ROOT / "work/build-cache/lifecycle-deps"
    path = cache / name
    if path.exists():
        data = path.read_bytes()
    else:
        url = "https://repo.maven.apache.org/maven2/" + relative + "/" + name
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.url != url:
                raise ValueError("Unexpected JVM dependency redirect")
            data = response.read(1024 * 1024)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("JVM dependency checksum differs: " + name)
    cache.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("xb") as destination:
            destination.write(data)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--java-home", type=Path, help="Explicit JDK containing bin/java and bin/javac")
    parser.add_argument("--junit", type=Path, help="Explicit JUnit 4.13.2 jar")
    parser.add_argument("--hamcrest", type=Path, help="Explicit Hamcrest Core 1.3 jar")
    parser.add_argument("--json", type=Path, help="Explicit org.json 20260719 jar")
    parser.add_argument("--fetch-dependencies", action="store_true", help="Fetch exact checksum-pinned Maven test jars into the project cache")
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    classes, temporary = output / "classes", output / "tmp"
    classes.mkdir(); temporary.mkdir()
    dependencies = ROOT / "work/build-cache/gradle/caches/modules-2/files-2.1"
    jars = []
    for supplied, relative, name in ((args.junit, "junit/junit/4.13.2", "junit-4.13.2.jar"),
                                    (args.hamcrest, "org.hamcrest/hamcrest-core/1.3", "hamcrest-core-1.3.jar"),
                                    (args.json, "org.json/json/20260719", "json-20260719.jar")):
        found = ([supplied.resolve(strict=True)] if supplied else [fetch_dependency(name)]
                 if args.fetch_dependencies else list((dependencies / relative).glob("*/" + name)))
        if len(found) != 1:
            raise ValueError("Required local JVM test dependency differs: " + name)
        if not found[0].is_file():
            raise ValueError("JVM test dependency is not a file: " + str(found[0]))
        jars.append(str(found[0]))
    names = ("RuntimeExitGate", "NativeSessionObservation", "RuntimeShutdownGate", "RuntimeRecoveryPolicy",
             "RuntimeOwnerWorker", "RuntimeActivations", "FoldWebUri", "ConversationActivity")
    sources = [ROOT / ("android/app/src/" + tree + "/java/app/foldgpt/" + name + suffix + ".java")
               for name in names for tree, suffix in (("main", ""), ("test", "Test"))]
    cp = os.pathsep.join(jars)
    def jdk_tool(name):
        supplied = args.java_home / "bin" / (name + (".exe" if os.name == "nt" else "")) if args.java_home else None
        resolved = str(supplied.resolve(strict=True)) if supplied else shutil.which(name)
        if not resolved or not Path(resolved).is_file():
            raise ValueError("JDK tool is unavailable: " + name)
        return resolved
    commands = [[jdk_tool("javac"), "-encoding", "UTF-8", "-source", "17", "-target", "17",
                 "-cp", cp, "-d", str(classes), *map(str, sources)],
                [jdk_tool("java"), "-Djava.io.tmpdir=" + str(temporary), "-cp", str(classes) + os.pathsep + cp,
                 "org.junit.runner.JUnitCore", *["app.foldgpt." + name + "Test" for name in names]]]
    for label, command in zip(("compile", "test"), commands):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=60)
        (output / (label + ".log")).write_bytes(result.stdout + result.stderr)
        (output / (label + "-command.json")).write_text(json.dumps(command, indent=2) + "\n")
        result.check_returncode()
    report = {"success": True, "androidExecuted": False,
        "dependencySha256": {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in jars},
        "sourceSha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
        "result": (output / "test.log").read_text()}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
