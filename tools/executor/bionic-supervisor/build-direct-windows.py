"""Freeze and compile the new direct runner using Windows NDK; no device action."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    ndk = args.ndk.resolve(strict=True)
    if "Pkg.Revision = 29.0.14206865" not in (ndk / "source.properties").read_text().splitlines():
        raise ValueError("Exact NDK r29 required")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "source"
    source.mkdir()
    inputs = {name: Path(__file__).with_name(name) for name in (
        "direct-runner.c", "direct-worker.c", "direct_wire.py", "direct-design.md", "direct-api.md",
        "test_direct_runner.py", "build-direct-windows.py")}
    check = ROOT / "tools/executor/bionic-runtime/shizuku-check-elf.py"
    inputs["check-elf.py"] = check
    for name, origin in inputs.items():
        shutil.copyfile(origin, source / name)
        if digest(origin) != digest(source / name):
            raise ValueError("Source changed during the snapshot copy")
    manifest = [{"path": path.name, "sha256": digest(path), "bytes": path.stat().st_size}
                for path in sorted(source.iterdir())]
    (output / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    source_manifest_sha256 = digest(output / "sources.json")
    shutil.copyfile(ndk / "source.properties", output / "ndk-source.properties")
    toolchain = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    compiler = toolchain / "clang.exe"

    def run(command, name):
        result = subprocess.run(list(map(str, command)), cwd=output, capture_output=True, timeout=120)
        (output / (name + ".command.json")).write_text(json.dumps(list(map(str, command)), indent=2) + "\n")
        (output / (name + ".stdout")).write_bytes(result.stdout)
        (output / (name + ".stderr")).write_bytes(result.stderr)
        (output / (name + ".result.json")).write_text(json.dumps({"exitCode": result.returncode}) + "\n")
        result.check_returncode()
        return result.stdout

    run([compiler, "--version"], "compiler")
    records = []
    for name in ("direct-runner", "direct-worker"):
        target = output / ("libfoldgpt_" + name.replace("-", "_") + ".so")
        base = [compiler, "--target=aarch64-linux-android35", "-std=c11", "-O2", "-Wall", "-Wextra",
                "-Werror", "-fPIE", "-pie", "-fstack-protector-strong", "-pthread", source / (name + ".c"),
                "-Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack",
                "-Wl,-z,max-page-size=16384,-z,common-page-size=16384"]
        run([*base, "-o", target], "compile-" + name)
        repeat = output / (name + ".repeat.so")
        run([*base, "-o", repeat], "recompile-" + name)
        if target.read_bytes() != repeat.read_bytes():
            raise ValueError("Actual recompilation differs")
        spec = importlib.util.spec_from_file_location("direct_elf_check", source / "check-elf.py")
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        elf = checker.check(target)
        (output / (name + ".elf.json")).write_text(json.dumps(elf, indent=2) + "\n")
        run([toolchain / "llvm-readelf.exe", "-h", "-l", "-d", "-s", target], "readelf-" + name)
        records.append({"path": target.name, "sha256": digest(target), "bytes": target.stat().st_size,
                        "realRecompilationIdentical": True, "androidExecuted": False})
    for row in manifest:
        if digest(inputs[row["path"]]) != row["sha256"] or digest(source / row["path"]) != row["sha256"]:
            raise ValueError("Current or frozen source changed during compilation")
    if digest(output / "sources.json") != source_manifest_sha256:
        raise ValueError("Source manifest changed during compilation")
    result = {"schema": "foldgpt.direct.native.compile.v1", "binaries": records,
              "ndk": "29.0.14206865", "apiLevel": 35,
              "sourceManifestSha256": source_manifest_sha256,
              "hostTestsExecuted": False, "phoneActions": False}
    (output / "build.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
