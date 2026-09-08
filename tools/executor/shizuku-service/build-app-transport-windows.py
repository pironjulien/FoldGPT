"""Compile the separate app JNI transport with NDK r29, without device operations."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ndk, output = args.ndk.resolve(), args.output.resolve()
    output.relative_to(ROOT)
    if "Pkg.Revision = 29.0.14206865" not in (ndk / "source.properties").read_text().splitlines():
        raise ValueError("Exact NDK r29 required")
    output.mkdir(parents=True, exist_ok=False)
    source = output / "app-spawn.c"
    source.write_bytes((HERE / "transport/src/main/cpp/app-spawn.c").read_bytes())
    toolchain = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin"
    library = output / "libfoldgpt_app_transport.so"
    command = [str(toolchain / "clang.exe"), "--target=aarch64-linux-android35", "-std=c11", "-O2",
               "-Wall", "-Wextra", "-Werror", "-fPIC", "-fstack-protector-strong", "-shared",
               str(source), "-Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384",
               "-o", str(library)]
    (output / "command.json").write_text(json.dumps(command, indent=2) + "\n")
    compiled = subprocess.run(command, capture_output=True, timeout=120)
    (output / "compiler.stdout").write_bytes(compiled.stdout)
    (output / "compiler.stderr").write_bytes(compiled.stderr)
    compiled.check_returncode()
    elf = subprocess.run([str(toolchain / "llvm-readelf.exe"), "-h", "-l", "-d", "--dyn-syms", str(library)],
                         capture_output=True, check=True, timeout=30).stdout.decode()
    (output / "elf.txt").write_text(elf)
    for symbol in ("Java_app_foldgpt_shizukuexec_AppNativeSpawn_launch", "Java_app_foldgpt_shizukuexec_AppNativeSpawn_waitChild"):
        if symbol not in elf:
            raise ValueError("Missing JNI entry " + symbol)
    if "AArch64" not in elf or "Java_app_foldgpt_shizukuexec_NativeSpawn_" in elf:
        raise ValueError("Unexpected transport architecture or legacy JNI entry")
    record = {"schema": "foldgpt.app-transport-build.v1", "androidExecuted": False,
              "sourceSha256": digest(source), "librarySha256": digest(library), "ndk": "29.0.14206865"}
    (output / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({"output": str(library), **record}))


if __name__ == "__main__":
    main()
