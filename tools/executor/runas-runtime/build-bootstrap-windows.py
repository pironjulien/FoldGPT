"""Build the production pre-Python admission with the installed Android NDK."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--prefix", type=Path, required=True)
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--libraries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ndk, prefix, inventory, libraries, output = [getattr(args, key).resolve() for key in (
        "ndk", "prefix", "inventory", "libraries", "output")]
    for path in (prefix, inventory, libraries, output):
        path.relative_to(ROOT)
    properties = (ndk / "source.properties").read_text()
    if "Pkg.Revision = 29.0.14206865" not in properties.splitlines():
        raise ValueError("Exact NDK r29 required")
    # The crypto library is the official CPython runtime input used in the
    # successful V2 admission, not a separately downloaded implementation.
    crypto = libraries / "libcrypto_python.so"
    if digest(crypto) != "a0dd60d620cd61bac7306a8293bcb82103971a4dcfc8c11fd55be3653beb42c4":
        raise ValueError("Official libcrypto input differs")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "native-bootstrap.c"
    source.write_bytes((Path(__file__).parent / "native-bootstrap.c").read_bytes())
    header = output / "runtime-inventory.h"
    header.write_bytes(inventory.read_bytes())
    toolchain = ndk / "toolchains/llvm/prebuilt/windows-x86_64"
    compiler = toolchain / "bin/clang.exe"
    executable = output / "libfoldgpt_native_bootstrap.so"
    command = [str(compiler), "--target=aarch64-linux-android35", "-std=c11", "-O2",
               "-Wall", "-Wextra", "-Werror", "-fPIE", "-fstack-protector-strong", "-pie",
               "-I" + str(output), "-I" + str(prefix / "include"), str(source),
               "-L" + str(libraries), "-lcrypto_python", "-Xlinker", "-rpath", "-Xlinker", "$ORIGIN",
               "-Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384",
               "-o", str(executable)]
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    compiled = subprocess.run(command, capture_output=True, timeout=120)
    (output / "compiler.stdout").write_bytes(compiled.stdout)
    (output / "compiler.stderr").write_bytes(compiled.stderr)
    compiled.check_returncode()
    elf = subprocess.run([str(toolchain / "bin/llvm-readelf.exe"), "-h", "-l", "-d", str(executable)],
                         capture_output=True, check=True, timeout=30).stdout.decode()
    (output / "elf.txt").write_text(elf)
    if re.findall(r"\(RUNPATH\)\s+Library runpath: \[(.*?)\]", elf) != ["$ORIGIN"]:
        raise ValueError("Admission RUNPATH differs")
    if "AArch64" not in elf or "/system/bin/linker64" not in elf:
        raise ValueError("Admission loader or architecture differs")
    record = {"schema": "foldgpt.native-admission-build.v1", "androidExecuted": False,
              "sourceSha256": digest(source), "inventorySha256": digest(header),
              "cryptoSha256": digest(crypto), "executableSha256": digest(executable),
              "runtimeHome": "/data/user/0/app.foldgpt/files/native-runtime-v1/python",
              "ndk": "29.0.14206865"}
    (output / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(executable), **record}))


if __name__ == "__main__":
    main()
