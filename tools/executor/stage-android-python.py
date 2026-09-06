"""Pin and stage the official CPython Android package for the debug native probe.

CPython binary/source pins were independently verified with Sigstore 4.5.0,
identity hugo@python.org, issuer https://github.com/login/oauth. No downloaded
source is executed. The launcher is built separately using the installed NDK.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import struct
import subprocess
import tarfile

VERSION = "3.14.7"
PACKAGE = f"python-{VERSION}-aarch64-linux-android.tar.gz"
SOURCE = f"Python-{VERSION}.tar.xz"
PYTHON_URL = f"https://www.python.org/ftp/python/{VERSION}/"
INPUTS = {
    PACKAGE: ("6d50cc3aa66e414a439594089bcdfb5f1264358155c70c1f00471c24cfb477fb", PYTHON_URL + PACKAGE),
    SOURCE: ("3b48dac8fb59f62eaa67ac83c1eb12bda1b7a08406dd286e252c11a66be27f81", PYTHON_URL + SOURCE),
    "bzip2-1.0.8.tar.gz": ("ab5a03176ee106d3f0fa90e381da478ddae405918153cca248e682cd0c4a2269", "https://sourceware.org/pub/bzip2/bzip2-1.0.8.tar.gz"),
    "libffi-3.4.4.tar.gz": ("d66c56ad259a82cf2a9dfc408b32bf5da52371500b84745f7fb8b645712df676", "https://github.com/libffi/libffi/releases/download/v3.4.4/libffi-3.4.4.tar.gz"),
    "openssl-3.5.7.tar.gz": ("a8c0d28a529ca480f9f36cf5792e2cd21984552a3c8e4aa11a24aa31aeac98e8", "https://github.com/openssl/openssl/releases/download/openssl-3.5.7/openssl-3.5.7.tar.gz"),
    "sqlite-autoconf-3500400.tar.gz": ("a3db587a1b92ee5ddac2f66b3edb41b26f9c867275782d46c3a088977d6a5b18", "https://www.sqlite.org/2025/sqlite-autoconf-3500400.tar.gz"),
    "xz-5.4.6.tar.gz": ("aeba3e03bf8140ddedf62a0a367158340520f6b384f75ca6045ccc6c0d43fd5c", "https://github.com/tukaani-project/xz/releases/download/v5.4.6/xz-5.4.6.tar.gz"),
    "zstd-1.5.7.tar.gz": ("eb33e51f49a15e023950cd7825ca74a4a2b43db8354825ac24fc1b7ee09e6fa3", "https://github.com/facebook/zstd/releases/download/v1.5.7/zstd-1.5.7.tar.gz"),
}
RECIPE_REVISIONS = {
    "dcea166d40d573e963a35435e48b047afe243c2d": ("74afea43b8d85b11bbd19d832ec228588225b197b1b7f8f0ae932315a9e4dfee", ["bzip2-1.0.8-3"]),
    "65d87e392d69198f3dd1ed2feb3b5fcea1b029a6": ("b9968d6de23b874a48472396388fef3fbe1ea3d70387d04636d677b7b2700de2", ["libffi-3.4.4-3", "xz-5.4.6-1"]),
    "f4c94a0fbc359d17993547b66f0627d436f8897b": ("e59dbf52195881d9a8ead72446b23a2cfbb9b3301b08d1fdaa09be99501c5670", ["openssl-3.5.7-0", "zstd-1.5.7-2"]),
    "f9628a323ebc5027e3e5cd5e47e1143bfdb26a80": ("f4205912a36792c24fa01d6a182ee27a3b93831016cf643675710207a78a3718", ["sqlite-3.50.4-0"]),
}
for revision, (digest, _) in RECIPE_REVISIONS.items():
    INPUTS[f"recipes-{revision}.tar.gz"] = (
        digest, "https://codeload.github.com/beeware/cpython-android-source-deps/tar.gz/" + revision)

JNI_LIBS = {"libpython3.14.so", "libcrypto_python.so", "libssl_python.so", "libsqlite3_python.so"}
SYSTEM_LIBS = {"libc.so", "libdl.so", "liblog.so", "libm.so", "libz.so"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def check_inputs(inputs):
    for name, (expected, _) in INPUTS.items():
        if digest(inputs / name) != expected:
            raise ValueError(f"Pinned input SHA-256 differs: {name}")


def fetch(inputs):
    inputs.mkdir(parents=True, exist_ok=True)
    for name, (expected, url) in INPUTS.items():
        target = inputs / name
        if not target.exists():
            temporary = target.with_name(target.name + ".part")
            subprocess.run(["curl", "-Lf", "--retry", "3", "-o", str(temporary), url], check=True)
            if digest(temporary) != expected:
                raise ValueError(f"Downloaded input SHA-256 differs: {name}")
            temporary.replace(target)
        elif digest(target) != expected:
            raise ValueError(f"Existing input SHA-256 differs: {name}")
    print(f"Verified {len(INPUTS)} pinned Android Python inputs")


def safe_name(name):
    path = PurePosixPath(name)
    if path.is_absolute() or not path.parts or any(part in {"..", ""} for part in path.parts):
        raise ValueError(f"Unsafe archive member: {name}")
    return path


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def stage(inputs, output):
    check_inputs(inputs)
    prefix = output / "prefix"
    staged = output / "stage"
    if prefix.exists() or staged.exists():
        raise ValueError("Stage and prefix must be new directories")
    members = {}
    with tarfile.open(inputs / PACKAGE) as archive:
        for member in archive:
            if member.isdir():
                continue
            name = safe_name(member.name)
            if name.parts[0] != "prefix":
                continue
            if str(name) in members:
                raise ValueError(f"Duplicate archive member: {name}")
            members[str(name)] = member
        for name, member in members.items():
            # One official alias is a relative symlink. Materialize the exact
            # regular target bytes so the asset tree works on Windows as well.
            if member.issym():
                target = safe_name(str(PurePosixPath(name).parent / member.linkname))
                member = members.get(str(target))
                if member is None or not member.isreg():
                    raise ValueError(f"Invalid native library alias: {name}")
            if not member.isreg() or member.size > 64 * 1024 * 1024:
                raise ValueError(f"Invalid package member: {name}")
            data = archive.extractfile(member).read()
            write(output.joinpath(*PurePosixPath(name).parts), data)
    jni = staged / "jniLibs/arm64-v8a"
    jni.mkdir(parents=True)
    for name in sorted(JNI_LIBS):
        shutil.copyfile(prefix / "lib" / name, jni / name)
    # Keep the complete official runtime library tree, including all standard
    # modules, test modules, OpenSSL providers/engines and licence text.
    runtime = staged / "assets/native-python"
    shutil.copytree(prefix / "lib", runtime / "lib")
    notices = staged / "assets/native-python-notices"
    notice_count = 0
    for name in INPUTS:
        if name == PACKAGE:
            continue
        with tarfile.open(inputs / name) as archive:
            for member in archive:
                if not member.isreg():
                    continue
                path = safe_name(member.name)
                leaf = path.name.upper()
                wanted = (len(path.parts) <= 2 and
                          any(token in leaf for token in ["COPYING", "LICENSE", "COPYRIGHT"]))
                wanted |= str(path) in {f"Python-{VERSION}/Doc/license.rst", f"Python-{VERSION}/Doc/copyright.rst"}
                if wanted:
                    write(notices / name / Path(*path.parts[1:]), archive.extractfile(member).read())
                    notice_count += 1
                elif name.startswith("sqlite-") and path.name == "sqlite3.h" and len(path.parts) == 2:
                    # This file starts with SQLite's public-domain dedication.
                    data = archive.extractfile(member).read().splitlines(keepends=True)
                    write(notices / "sqlite-public-domain.txt", b"".join(data[:11]))
                    notice_count += 1
    if notice_count < 15:
        raise ValueError("The corresponding-source licence inventory is incomplete")
    metadata = {
        "pythonVersion": VERSION,
        "cpythonTag": "v3.14.7",
        "cpythonCommit": "823f0323ee6ec1402088b73bce1a38473cac36dc",
        "releasePinVerification": {"client": "sigstore 4.5.0", "identity": "hugo@python.org",
                                   "issuer": "https://github.com/login/oauth",
                                   "scope": "Independent binary/source pin verification; each staging run verifies pinned hashes"},
        "inputs": [{"name": name, "sha256": sha, "url": url} for name, (sha, url) in INPUTS.items()],
        "recipeRevisions": {revision: versions for revision, (_, versions) in RECIPE_REVISIONS.items()},
        "scope": "Debug trusted native interpreter; no claim of device runtime or sandbox validation",
    }
    write(notices / "sources.json", (json.dumps(metadata, indent=2) + "\n").encode())
    write(output / "inputs.json", (json.dumps(metadata, indent=2) + "\n").encode())
    print(f"Staged official runtime and {notice_count} corresponding-source notices: {staged}")


def elf_info(data):
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Expected ELF64 little endian")
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    if header[0] != 3 or header[1] != 183 or header[8] != 56:
        raise ValueError("Expected AArch64 ELF dynamic object")
    segments = []
    for index in range(header[9]):
        segments.append(struct.unpack_from("<IIQQQQQQ", data, header[4] + index * header[8]))
    loads = []
    interpreter = None
    dynamic = {}
    for kind, flags, offset, address, _, size, memory, alignment in segments:
        if offset + size > len(data):
            raise ValueError("ELF segment exceeds file")
        if kind == 1:
            if alignment < 16384 or offset % 16384 != address % 16384 or flags & 3 == 3:
                raise ValueError("Incompatible or writable-executable LOAD segment")
            loads.append({"flags": flags, "alignment": alignment, "fileSize": size, "memorySize": memory})
        elif kind == 3:
            interpreter = data[offset:offset + size].rstrip(b"\0").decode("ascii")
            if interpreter != "/system/bin/linker64":
                raise ValueError("Non-Bionic ELF interpreter")
        elif kind == 2:
            for entry in range(offset, offset + size, 16):
                tag, value = struct.unpack_from("<qQ", data, entry)
                if tag == 0:
                    break
                dynamic.setdefault(tag, []).append(value)
        elif kind == 0x6474E551 and flags & 1:
            raise ValueError("Executable GNU stack")
    if not loads or 5 not in dynamic or 10 not in dynamic:
        raise ValueError("Missing ELF load or dynamic string table")
    string_address, string_size = dynamic[5][0], dynamic[10][0]
    strings = None
    for kind, _, offset, address, _, size, _, _ in segments:
        if kind == 1 and address <= string_address and string_address + string_size <= address + size:
            start = offset + string_address - address
            strings = data[start:start + string_size]
            break
    if strings is None:
        raise ValueError("Dynamic string table is outside LOAD segments")
    def string(index):
        if not 0 <= index < len(strings):
            raise ValueError("Invalid ELF string offset")
        end = strings.index(b"\0", index)
        return strings[index:end].decode("ascii")
    needed = [string(value) for value in dynamic.get(1, [])]
    if set(needed) - SYSTEM_LIBS - JNI_LIBS:
        raise ValueError(f"Unclosed native dependency set: {needed}")
    return {"machine": "AArch64", "loads": loads, "interpreter": interpreter,
            "needed": needed, "runpath": [string(value) for value in dynamic.get(29, [])]}


def inventory(output):
    staged = output / "stage"
    launcher = staged / "jniLibs/arm64-v8a/libfoldgpt_python.so"
    if not launcher.is_file():
        raise ValueError("Missing compiled embedding launcher")
    records = []
    for path in sorted(staged.rglob("*")):
        if not path.is_file():
            continue
        data = path.read_bytes()
        record = {"path": path.relative_to(staged).as_posix(), "size": len(data),
                  "sha256": hashlib.sha256(data).hexdigest()}
        if data[:4] == b"\x7fELF":
            record["elf"] = elf_info(data)
        records.append(record)
    launcher_info = elf_info(launcher.read_bytes())
    if launcher_info["interpreter"] != "/system/bin/linker64" or launcher_info["runpath"] != ["$ORIGIN"]:
        raise ValueError("Launcher does not use the native APK library directory")
    tree = ast.parse(next((output / "prefix/lib/python3.14").glob("_sysconfigdata*.py")).read_text())
    config = ast.literal_eval(next(node.value for node in tree.body if isinstance(node, ast.Assign)))
    required = ["_ASYNCIO", "_POSIXSUBPROCESS", "_SOCKET", "SELECT", "FCNTL", "_JSON", "_SSL", "_SQLITE3", "_CTYPES"]
    if any(config.get(f"MODULE_{name}_STATE") != "yes" for name in required):
        raise ValueError("Official runtime lacks a required supervisor module")
    result = {"pythonVersion": VERSION, "launcherSourceSha256": digest(output / "android-python-launcher.c"),
              "compiler": (output / "compiler.txt").read_text(),
              "ndk": (output / "ndk-source.properties").read_text(),
              "upstreamUnavailableModules": {key: value for key, value in config.items()
                  if key.startswith("MODULE_") and key.endswith("_STATE") and value != "yes"},
              "requiredModuleBuildStates": "PASS", "files": records,
              "scope": "Authenticated source/package inventory and static ELF validation only; no Android execution claim"}
    write(output / "inventory.json", (json.dumps(result, indent=2) + "\n").encode())
    print(f"Inventory PASS: {len(records)} files, {sum('elf' in row for row in records)} AArch64 ELF; all LOAD segments support 16 KiB")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    fetch_parser = sub.add_parser("fetch")
    fetch_parser.add_argument("--inputs", type=Path, required=True)
    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("--inputs", type=Path, required=True)
    stage_parser.add_argument("--output", type=Path, required=True)
    inventory_parser = sub.add_parser("inventory")
    inventory_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "fetch":
        fetch(args.inputs)
    elif args.command == "stage":
        stage(args.inputs, args.output)
    else:
        inventory(args.output)


if __name__ == "__main__":
    main()
