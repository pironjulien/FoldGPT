"""Compile the actual CLI against Windows CPython and exercise cache semantics.

Only /proc/self/exe resolution is adapted by a host-only unistd.h. PyConfig,
initialization, CLI parsing and imports are the unchanged production C source.
This cannot qualify Android loading, permissions, confinement or admission.
All copied runtime files, binaries and evidence stay in the explicit output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root):
    return {p.relative_to(root).as_posix(): sha(p)
            for p in sorted(root.rglob("*")) if p.is_file()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--msvc", type=Path, required=True)
    parser.add_argument("--windows-sdk", type=Path, required=True)
    parser.add_argument("--sdk-version", required=True)
    args = parser.parse_args()
    if sys.platform != "win32" or sys.version_info[:2] != (3, 14):
        raise SystemExit("Requires actual Windows CPython 3.14 with headers and import library")
    work = args.output.resolve()
    work.relative_to(ROOT)
    work.mkdir(parents=True, exist_ok=False)
    home = work / "host-home"
    binary_dir = work / "host-bin"
    binary_dir.mkdir()
    original = Path(sys.base_prefix)
    shutil.copytree(original / "Lib", home / "Lib",
                    ignore=shutil.ignore_patterns("__pycache__", "site-packages"))
    shutil.copytree(original / "DLLs", home / "DLLs")
    for dll in original.glob("*.dll"):
        shutil.copy2(dll, binary_dir / dll.name)
    source = work / "python-cli.c"
    shutil.copy2(Path(__file__).with_name("python-cli.c"), source)
    (work / "unistd.h").write_text(r'''#include <windows.h>
#include <stdint.h>
#include <errno.h>
#include <string.h>
typedef intptr_t ssize_t;
static ssize_t readlink(const char *path, char *buffer, size_t capacity) {
    if (strcmp(path, "/proc/self/exe") != 0) { errno = EINVAL; return -1; }
    DWORD count = GetModuleFileNameA(NULL, buffer, (DWORD)capacity);
    if (count == 0) { errno = ENOENT; return -1; }
    return (ssize_t)count;
}
''', encoding="utf-8")
    compiler = args.msvc / "bin/Hostx64/x64/cl.exe"
    sdk_include = args.windows_sdk / "Include" / args.sdk_version
    sdk_lib = args.windows_sdk / "Lib" / args.sdk_version
    binary = binary_dir / "python-cli.exe"
    command = [str(compiler), "/nologo", "/O2", "/W4", "/WX", "/std:c11", "/MD",
               "/D_CRT_SECURE_NO_WARNINGS", "/DPATH_MAX=32768",
               "/DFOLDGPT_PYTHON_HOME=" + json.dumps(str(home)),
               "/I" + str(work), "/I" + str(original / "include"),
               "/I" + str(args.msvc / "include"),
               *["/I" + str(sdk_include / name) for name in ("ucrt", "shared", "um")],
               str(source), "/Fo" + str(work / "python-cli.obj"), "/Fe" + str(binary),
               "/link", "/INCREMENTAL:NO", "/DYNAMICBASE", "/NXCOMPAT",
               "/LIBPATH:" + str(original / "libs"),
               "/LIBPATH:" + str(args.msvc / "lib/x64"),
               "/LIBPATH:" + str(sdk_lib / "ucrt/x64"),
               "/LIBPATH:" + str(sdk_lib / "um/x64"), "python314.lib", "kernel32.lib"]
    (work / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    compiled = subprocess.run(command, cwd=work, capture_output=True, timeout=60)
    (work / "compiler.stdout").write_bytes(compiled.stdout)
    (work / "compiler.stderr").write_bytes(compiled.stderr)
    compiled.check_returncode()
    default = str(home) + "-cache"
    fixture = work / "modules"
    fixture.mkdir()
    report = {"schema": "foldgpt.python-cache-host.v1", "hostPython": sys.version,
              "scope": "Actual C CLI with Windows executable-path shim; no Android execution",
              "sourceSha256": sha(source), "binarySha256": sha(binary),
              "defaultPycachePrefix": default, "checks": [], "passed": False}
    baseline = inventory(home)

    def run(name, options=(), environment=None, expected=default, *, bytecode=True):
        module = "cache_probe_" + str(len(report["checks"]))
        (fixture / (module + ".py")).write_text("value = 42\n", encoding="utf-8")
        code = ("import sys,json,pathlib; sys.path.insert(0," + repr(str(fixture)) + "); "
                "m=__import__(" + repr(module) + "); "
                "print(json.dumps(dict(prefix=sys.pycache_prefix,cache=m.__cached__,"
                "exists=pathlib.Path(m.__cached__).is_file(),value=m.value,"
                "dontWrite=sys.dont_write_bytecode,isolated=sys.flags.isolated,"
                "ignoreEnvironment=sys.flags.ignore_environment)))")
        result = subprocess.run([str(binary), *options, "-c", code], cwd=work,
                                env={} if environment is None else environment,
                                capture_output=True, timeout=30)
        observation = {"name": name, "options": list(options), "exit": result.returncode,
                       "stdout": result.stdout.decode("utf-8"),
                       "stderr": result.stderr.decode("utf-8", errors="replace")}
        report["checks"].append(observation)
        if result.returncode or result.stderr:
            raise AssertionError(observation)
        value = json.loads(result.stdout)
        observation["value"] = value
        assert value["prefix"] == expected, observation
        assert value["value"] == 42 and value["dontWrite"] is not bytecode, observation
        assert value["exists"] is bytecode, observation
        if bytecode:
            Path(value["cache"]).relative_to(expected)
        return value

    try:
        run("default-empty-environment")
        run("isolated-default", ["-I"], {"PYTHONPYCACHEPREFIX": str(work / "ignored-I")})
        run("ignore-environment-default", ["-E"], {"PYTHONPYCACHEPREFIX": str(work / "ignored-E")})
        run("empty-environment-variable-default", environment={"PYTHONPYCACHEPREFIX": ""})
        env_prefix, cli_prefix = str(work / "environment-cache"), str(work / "cli-cache")
        run("environment-prefix", environment={"PYTHONPYCACHEPREFIX": env_prefix}, expected=env_prefix)
        run("cli-precedes-environment", ["-X", "pycache_prefix=" + cli_prefix],
            {"PYTHONPYCACHEPREFIX": env_prefix}, expected=cli_prefix)
        isolated_prefix = str(work / "isolated-cli-cache")
        run("isolated-explicit-cli-prefix", ["-I", "-X", "pycache_prefix=" + isolated_prefix],
            {"PYTHONPYCACHEPREFIX": env_prefix}, expected=isolated_prefix)
        run("unrelated-xoption-does-not-disable-default", ["-X", "pycache_prefix_extra=ignored"])
        # Explicitly requested -B is tested only for the caller's opt-out case;
        # all preceding imports generated real .pyc files with caching enabled.
        run("explicit-empty-cli-prefix", ["-B", "-X", "pycache_prefix="],
            {"PYTHONPYCACHEPREFIX": env_prefix}, expected=None, bytecode=False)
        run("explicit-bare-cli-prefix", ["-B", "-X", "pycache_prefix"],
            {"PYTHONPYCACHEPREFIX": env_prefix}, expected=None, bytecode=False)
        code = ("import subprocess,sys; r=subprocess.run([sys.executable,'-c',"
                "'import sys,json,zipapp; print(json.dumps(dict(prefix=sys.pycache_prefix,"
                "dontWrite=sys.dont_write_bytecode)))'],env={},capture_output=True,check=True); "
                "sys.stdout.buffer.write(r.stdout)")
        child = subprocess.run([str(binary), "-I", "-c", code], cwd=work, env={},
                               capture_output=True, timeout=30)
        report["checks"].append({"name": "subprocess-empty-environment", "exit": child.returncode,
                                 "stdout": child.stdout.decode(), "stderr": child.stderr.decode()})
        assert child.returncode == 0 and child.stderr == b""
        assert json.loads(child.stdout) == {"prefix": default, "dontWrite": False}
        after = inventory(home)
        assert baseline == after, "Imports changed the copied trusted runtime"
        assert not list(home.rglob("__pycache__")), "Cache directory appeared inside runtime"
        assert not list(home.rglob("*.pyc")), "Bytecode appeared inside runtime"
        assert list(Path(default).rglob("*.pyc")), "No real default cache generated"
        report["runtimeUnchanged"] = True
        report["runtimeFilesChecked"] = len(baseline)
        report["cacheFileCount"] = len(list(Path(default).rglob("*.pyc")))
        report["passed"] = True
    finally:
        (work / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(work), "passed": True, "checks": len(report["checks"]),
                      "cacheFiles": report["cacheFileCount"], "sourceSha256": report["sourceSha256"]}))


if __name__ == "__main__":
    main()
