"""Admit the reviewed model PTY build; phone qualification remains separate."""
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys

ROOT = Path(__file__).resolve().parents[3]
NAME = "libfoldgpt_direct_pty_supervisor.so"
# Measured identity of the reviewed, independently rebuilt candidate dossier.
BUILD_SHA256 = "3ff59f211024b9f25abd2aabf3eab49dad9e506c360da13f80b0b12f1b5d309c"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_under(root, relative):
    if (type(relative) is not str or not relative or PurePosixPath(relative).is_absolute()
            or PurePosixPath(relative).as_posix() != relative or ".." in PurePosixPath(relative).parts
            or "\\" in relative or ":" in relative):
        raise ValueError("Invalid PTY build evidence path")
    path = root
    for part in PurePosixPath(relative).parts:
        path /= part
        if path.is_symlink() or path.is_junction():
            raise ValueError("PTY evidence must not traverse a path alias")
    path.resolve(strict=True).relative_to(root.resolve(strict=True))
    if not path.is_file():
        raise ValueError("PTY evidence must be a regular file")
    return path


def production_pty(build):
    relative = Path(build).absolute().relative_to(ROOT).as_posix()
    record_data = file_under(ROOT, relative + "/build.json").read_bytes()
    if digest(record_data) != BUILD_SHA256:
        raise ValueError("PTY build differs from the reviewed candidate")
    build = ROOT / relative
    record = json.loads(record_data)
    if (record["schema"] != "foldgpt.native-pty-candidate.v1"
            or record["profile"] != "bionic-direct-pty-v1"
            or record["reproducibleBytes"] is not True
            or record["androidCandidateExecuted"] is not False):
        raise ValueError("Invalid PTY build scope")
    sources = {}
    for row in record["source"]:
        data = file_under(build, row["local"]).read_bytes()
        if digest(data) != row["sha256"] or row["local"] in sources:
            raise ValueError("PTY source evidence differs")
        sources[row["local"]] = row["sha256"]
        name = PurePosixPath(row["local"]).name
        if name in ("tty-runner.c", "tty_wire.py", "tty_processes.py"):
            if (ROOT / "tools/executor/bionic-supervisor" / name).read_bytes() != data:
                raise ValueError("Packaged PTY implementation differs from its build: " + name)
    if {p.relative_to(build).as_posix() for p in (build / "source").rglob("*") if p.is_file()} != set(sources):
        raise ValueError("PTY frozen source inventory differs")
    for row in record["headers"]:
        if digest(file_under(build, "headers/" + row["path"]).read_bytes()) != row["sha256"]:
            raise ValueError("PTY frozen NDK header differs: " + row["path"])
    closure_data = file_under(build, "python-source-closure.json").read_bytes()
    if digest(closure_data) != record["pythonClosureSha256"]:
        raise ValueError("PTY Python source closure manifest differs")
    closure = json.loads(closure_data)
    closure_paths, runtime_sources = set(), {}
    for row in closure:
        relative_source = row["projectPath"]
        data = file_under(build, "python-closure/" + relative_source).read_bytes()
        if relative_source in closure_paths or digest(data) != row["sha256"]:
            raise ValueError("PTY frozen Python source differs: " + relative_source)
        closure_paths.add(relative_source)
        canonical = relative_source if relative_source.startswith("tools/") else None
        if row["module"] in ("tty_processes", "tty_wire"):
            canonical = "tools/executor/bionic-supervisor/" + row["module"] + ".py"
        if canonical is not None:
            if file_under(ROOT, canonical).read_bytes() != data:
                raise ValueError("PTY runtime source changed after qualification: " + canonical)
            runtime_sources[canonical] = row["sha256"]
    if {p.relative_to(build / "python-closure").as_posix()
            for p in (build / "python-closure").rglob("*") if p.is_file()} != closure_paths:
        raise ValueError("PTY frozen Python closure inventory differs")
    binary = file_under(build, NAME).read_bytes()
    if digest(binary) != record["executableSha256"] or file_under(build, "repeat.so").read_bytes() != binary:
        raise ValueError("PTY independent build bytes differ")
    if sys.flags.optimize:
        raise ValueError("PTY ELF verification requires normal Python assertions")
    spec = importlib.util.spec_from_file_location("foldgpt_pty_elf",
        ROOT / "tools/executor/bionic-runtime/shizuku-check-elf.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    elf = checker.check(build / NAME)
    provenance = {"path": relative, "buildManifestSha256": digest(record_data),
        "executableSha256": digest(binary), "bytes": len(binary), "profile": record["profile"],
        "sourceSha256": {name: sources["source/" + name] for name in ("tty-runner.c", "tty_wire.py", "tty_processes.py")},
        "runtimeSourceSha256": runtime_sources,
        "elf": elf}
    return binary, provenance
