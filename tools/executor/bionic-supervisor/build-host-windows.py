"""Freeze and build only the separate human supervisor with Windows NDK r29.

No WSL, Android execution, model-runner mutation, dependency installation or
runtime activation. Every output remains beneath the FoldGPT project directory.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "tools/executor/native-runner-seccomp.h").is_file())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command, output, name, *, timeout=120):
    (output / (name + ".command.json")).write_text(json.dumps(command, indent=2) + "\n")
    result = subprocess.run(command, capture_output=True, timeout=timeout, cwd=output)
    (output / (name + ".stdout")).write_bytes(result.stdout)
    (output / (name + ".stderr")).write_bytes(result.stderr)
    (output / (name + ".result.json")).write_text(json.dumps({"exitCode": result.returncode}) + "\n")
    result.check_returncode()
    return result.stdout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-directory", type=Path)
    args = parser.parse_args()
    ndk, output = args.ndk.resolve(strict=True), args.output.resolve()
    output.relative_to(ROOT)
    properties = ndk / "source.properties"
    if "Pkg.Revision = 29.0.14206865" not in properties.read_text().splitlines():
        raise ValueError("Exact Windows Android NDK 29.0.14206865 required")
    toolchain = ndk / "toolchains/llvm/prebuilt/windows-x86_64"
    compiler, readelf = [toolchain / "bin" / name for name in ("clang.exe", "llvm-readelf.exe")]
    output.mkdir(parents=True, exist_ok=False)
    frozen = output / "source"
    frozen.mkdir()
    inputs = {
        "host-runner.c": ROOT / "tools/executor/bionic-supervisor/host-runner.c",
        "native-runner-seccomp.h": ROOT / "tools/executor/native-runner-seccomp.h",
        "check-elf.py": ROOT / "tools/executor/bionic-runtime/shizuku-check-elf.py",
        "build-host-windows.py": Path(__file__).resolve(),
    }
    if args.source_directory:
        origin = args.source_directory.resolve(strict=True)
        origin.relative_to(ROOT)
        inputs = {name: origin / name for name in inputs}
    manifest = []
    for name, path in inputs.items():
        target = frozen / name
        shutil.copyfile(path, target)
        if digest(target) != digest(path):
            raise ValueError("Frozen build input changed during copy")
        manifest.append({"path": name, "sha256": digest(target), "bytes": target.stat().st_size})
    (output / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copyfile(properties, output / "ndk-source.properties")
    run([str(compiler), "--version"], output, "compiler-version", timeout=30)
    executable = output / "libfoldgpt_host_supervisor.so"
    command = [str(compiler), "--target=aarch64-linux-android35", "-std=c11", "-O2",
        "-Wall", "-Wextra", "-Werror", "-fPIE", "-pie", "-fstack-protector-strong",
        "-I" + str(frozen), "-MD", "-MF", str(output / "headers.d"), "-MT", "host-runner.o",
        str(frozen / "host-runner.c"), "-Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack",
        "-Wl,-z,max-page-size=16384,-z,common-page-size=16384",
        "-Wl,--reproduce=" + str(output / "linker-reproduction.tar"), "-o", str(executable)]
    run(command, output, "compile")
    dependencies = (output / "headers.d").read_text().replace("\\\n", " ").split(":", 1)[1]
    headers = []
    for token in re.findall(r"(?:\\.|[^\s])+", dependencies):
        path = Path(token.replace("\\ ", " ").replace("\\#", "#").replace("\\:", ":")).resolve(strict=True)
        try:
            relative = Path("ndk") / path.relative_to(ndk)
        except ValueError:
            relative = Path("project") / path.relative_to(frozen)
        target = output / "headers" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        headers.append({"path": relative.as_posix(), "sha256": digest(target), "bytes": target.stat().st_size})
    (output / "headers.json").write_text(json.dumps(headers, indent=2) + "\n")
    elf = run([str(readelf), "-h", "-l", "-d", "-s", "-n", str(executable)], output, "readelf", timeout=30)
    (output / "elf.txt").write_bytes(elf)
    spec = importlib.util.spec_from_file_location("foldgpt_host_elf_check", frozen / "check-elf.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    evidence = checker.check(executable)
    (output / "elf.json").write_text(json.dumps(evidence, indent=2) + "\n")
    # Same frozen inputs, compiler and linker in a second output path. This is
    # an actual byte-for-byte reproducibility check, not a repeated hash read.
    rebuild = output / "rebuild"
    rebuild.mkdir()
    repeated = list(command)
    repeated[repeated.index("-MF") + 1] = str(rebuild / "headers.d")
    repeated[repeated.index("-o") + 1] = str(rebuild / executable.name)
    repeated = [value for value in repeated if not value.startswith("-Wl,--reproduce=")]
    run(repeated, output, "recompile")
    if digest(rebuild / executable.name) != digest(executable):
        raise ValueError("Repeated frozen native build differs byte-for-byte")
    report = {"schema": "foldgpt.native-host-build.v1", "androidExecuted": False,
        "wslExecuted": False, "ndk": "29.0.14206865", "apiLevel": 35,
        "compilerSha256": digest(compiler), "readelfSha256": digest(readelf),
        "sourceSha256": digest(frozen / "host-runner.c"),
        "profileHeaderSha256": digest(frozen / "native-runner-seccomp.h"),
        "includedHeaders": len(headers), "reproducible": True,
        "elf": evidence, "modelRunnerChanged": False}
    (output / "build.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"output": str(executable), **report}))


if __name__ == "__main__":
    main()
