"""Build the Bionic Python CLI using the installed Windows NDK r29.

Equivalent inputs and flags to bionic-runtime/build-python-cli.sh. Outputs are
new and project-local. No Android execution or installation is performed.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_HOME = "/data/user/0/app.foldgpt/files/runas-native-v1/python"


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runtime-home", default=RUNTIME_HOME)
    args = parser.parse_args()
    ndk, prefix, output = args.ndk.resolve(), args.prefix.resolve(), args.output.resolve()
    runtime_home = args.runtime_home
    if re.fullmatch(r"/data/user/0/app\.foldgpt/files/(?:runas-native|native-runtime)-v[1-9][0-9]*/python", runtime_home) is None:
        raise ValueError("Expected a versioned private FoldGPT Python home")
    prefix.relative_to(ROOT)
    output.relative_to(ROOT)
    properties = (ndk / "source.properties").read_text()
    if "Pkg.Revision = 29.0.14206865" not in properties.splitlines():
        raise ValueError("Exact NDK r29 required")
    source = ROOT / "tools/executor/bionic-runtime"
    specification = importlib.util.spec_from_file_location("python_package", source / "python-package.py")
    package = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(package)
    archive = ROOT / "downloads/native-python/inputs/python-3.14.7-aarch64-linux-android.tar.gz"
    contents = package.package(archive)
    # Libraries as well as headers are exact official bytes before the linker runs.
    for name, data in contents.items():
        if name.startswith("include/") or (name.startswith("lib/lib") and name.endswith(".so")):
            if (prefix / name).read_bytes() != data:
                raise ValueError(f"Official compiler input differs: {name}")
    output.mkdir(parents=True, exist_ok=False)
    cli_source = output / "python-cli.c"
    cli_source.write_bytes((source / "python-cli.c").read_bytes())
    toolchain = ndk / "toolchains/llvm/prebuilt/windows-x86_64"
    compiler = toolchain / "bin/clang.exe"
    executable = output / "libfoldgpt_python_cli.so"
    runpath = runtime_home + "/lib:$ORIGIN"
    command = [str(compiler), "--target=aarch64-linux-android35",
               "--sysroot=" + str(toolchain / "sysroot"), "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
               "-fPIE", "-pie", "-Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384",
               "-Xlinker", "-rpath", "-Xlinker", runpath, "-Wl,--no-undefined",
               '-DFOLDGPT_PYTHON_HOME="' + runtime_home + '"',
               "-I" + str(prefix / "include/python3.14"), str(cli_source), "-L" + str(prefix / "lib"),
               "-Wl,--no-as-needed", "-lpython3.14", "-lcrypto_python", "-lssl_python", "-lsqlite3_python",
               "-Wl,--as-needed", "-o", str(executable)]
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
    result = subprocess.run(command, capture_output=True, timeout=120)
    (output / "compiler.stdout").write_bytes(result.stdout)
    (output / "compiler.stderr").write_bytes(result.stderr)
    result.check_returncode()
    elf = subprocess.run([str(toolchain / "bin/llvm-readelf.exe"), "-h", "-l", "-d", str(executable)],
                         capture_output=True, check=True, timeout=30).stdout.decode("utf-8")
    (output / "elf.txt").write_text(elf, encoding="utf-8")
    if re.findall(r"\(RUNPATH\)\s+Library runpath: \[(.*?)\]", elf) != [runpath]:
        raise ValueError("Compiled RUNPATH differs from its actual deployment")
    needed = set(re.findall(r"\(NEEDED\)\s+Shared library: \[(.*?)\]", elf))
    if not {"libpython3.14.so", "libcrypto_python.so", "libssl_python.so", "libsqlite3_python.so"} <= needed:
        raise ValueError("Required direct runtime dependencies are absent")
    if "AArch64" not in elf or "/system/bin/linker64" not in elf:
        raise ValueError("Wrong architecture or loader")
    version = subprocess.run([str(compiler), "--version"], capture_output=True, check=True, timeout=30).stdout
    (output / "compiler.txt").write_bytes(version)
    (output / "ndk-source.properties").write_text(properties, encoding="utf-8")
    (output / "deployment-prefix.txt").write_text(runtime_home + "\n", encoding="utf-8")
    evidence = {"schema": "foldgpt.runas-python-windows-build.v1", "androidExecuted": False,
                "runtimeHome": runtime_home, "archiveSha256": package.PIN["sha256"],
                "sourceSha256": digest(cli_source), "executableSha256": digest(executable),
                "pythonLibrarySha256": digest(prefix / "lib/libpython3.14.so"),
                "ndk": "29.0.14206865", "compilerHost": "windows-x86_64"}
    (output / "build.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(executable), **evidence}))


if __name__ == "__main__":
    main()
