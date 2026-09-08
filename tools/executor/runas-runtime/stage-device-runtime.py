"""Install and read back a new app-private Python data tree for the fixed trial.

Uses the reviewed independent APK's native libraries. Never changes Android
system files, the official application, existing runtime trees or markers.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--installation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    release, output = args.release.resolve(), args.output.resolve()
    release.relative_to(ROOT)
    output.relative_to(ROOT)
    manifest = json.loads((release / "manifest.json").read_text())
    match = re.fullmatch(r"app\.foldgpt\.runasbrokerqualification\.v([12])", manifest["package"])
    if match is None:
        raise ValueError("Unreviewed qualification package version")
    version = match[1]
    package = manifest["package"]
    base = "/data/user/0/app.foldgpt/files/runas-native-v" + version
    records = {entry["path"]: entry for entry in manifest["files"]}
    def pinned(relative):
        data = (release / relative).read_bytes()
        entry = records[relative]
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Frozen input differs: " + relative)
        return data
    installation = json.loads(args.installation.read_text(encoding="utf-8-sig"))
    target = installation["target"]
    installed = installation["qualification"]
    if target["packageName"] != "app.foldgpt" or target["dataDir"] != "/data/user/0/app.foldgpt":
        raise ValueError("Wrong FoldGPT installation")
    native = installed["nativeLibraryDir"]
    if installed["packageName"] != package or re.fullmatch(r"/data/app/[A-Za-z0-9_~./+=-]+/lib/arm64", native) is None:
        raise ValueError("Wrong independent qualification package")
    stage = "stage-r2"
    runtime = json.loads(pinned(stage + "/runtime-manifest.json"))
    apk = pinned("runasbrokerqualification-debug.apk")
    apk_digest = hashlib.sha256(apk).hexdigest()
    # The installation record format is checked again against the physical APK.
    adb = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"
    adb_args = [str(adb), "-s", "R3GL808JN4A"]
    commands = []
    def call(parts, *, data=None):
        result = subprocess.run(adb_args + parts, input=data, capture_output=True, timeout=120)
        commands.append({"argv": parts, "code": result.returncode,
                         "stdoutBytes": len(result.stdout), "stderr": result.stderr.decode("utf-8", "replace")})
        result.check_returncode()
        return result.stdout
    source_apk = installed["sourceDir"]
    if re.fullmatch(r"/data/app/[A-Za-z0-9_~./+=-]+\.apk", source_apk) is None:
        raise ValueError("Unexpected installed APK pathname")
    if call(["shell", "sha256sum", source_apk]).decode().split()[0] != apk_digest:
        raise ValueError("Installed qualification APK differs from reviewed release")
    tree = {}
    for entry in runtime["dataFiles"]:
        name = entry["path"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name or name in tree:
            raise ValueError("Unsafe runtime data path")
        data = pinned(stage + "/staged-python-data/" + name)
        if len(data) != entry["bytes"] or hashlib.sha256(data).hexdigest() != entry["sha256"]:
            raise ValueError("Runtime data identity differs")
        tree["python/" + name] = ("file", data)
    for entry in runtime["runtimeAliases"]:
        name, library = entry["path"], entry["nativeLibrary"]
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name or "python/" + name in tree:
            raise ValueError("Unsafe runtime alias")
        if installation["nativeLibraries"][library] != entry["sha256"]:
            raise ValueError("Installed alias target differs")
        tree["python/" + name] = ("alias", native + "/" + library)
    directories = {"python"}
    for name in tree:
        directories.update(str(parent) for parent in PurePosixPath(name).parents if str(parent) != ".")
    if set(tree) & directories:
        raise ValueError("Runtime file conflicts with a directory")
    output.mkdir(parents=True, exist_ok=False)
    tar_path = output / "runtime-data.tar"
    with tarfile.open(tar_path, "w", format=tarfile.GNU_FORMAT) as archive:
        for directory in sorted(directories, key=lambda value: (value.count("/"), value)):
            info = tarfile.TarInfo(directory)
            info.type, info.mode = tarfile.DIRTYPE, 0o700
            archive.addfile(info)
        for name, (kind, value) in sorted(tree.items()):
            info = tarfile.TarInfo(name)
            info.mode = 0o600
            if kind == "file":
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))
            else:
                info.type, info.linkname = tarfile.SYMTYPE, value
                archive.addfile(info)
    report = {"schema": "foldgpt.runas-runtime-install.v1", "base": base,
              "apkSha256": apk_digest, "nativeLibraryDir": native,
              "runtimeFiles": len(tree), "verified": False}
    try:
        report["bootBefore"] = call(["shell", "cat", "/proc/sys/kernel/random/boot_id"]).decode().strip()
        # Exclusive mkdir: any earlier partial deployment is retained and refused.
        call(["shell", "run-as", "app.foldgpt", "mkdir", "-m", "700", base])
        call(["exec-in", "run-as", "app.foldgpt", "tar", "-xf", "-", "-C", base], data=tar_path.read_bytes())
        readback = call(["exec-out", "run-as", "app.foldgpt", "tar", "-cf", "-", "-C", base, "python"])
        (output / "runtime-readback.tar").write_bytes(readback)
        seen = set()
        with tarfile.open(fileobj=io.BytesIO(readback)) as archive:
            for item in archive:
                name = item.name.rstrip("/")
                if name in seen or item.uid != target["uid"]:
                    raise ValueError("Duplicate object or foreign runtime owner")
                seen.add(name)
                if name in directories:
                    if not item.isdir() or item.mode != 0o700:
                        raise ValueError("Runtime directory differs")
                elif name in tree:
                    kind, value = tree[name]
                    if kind == "file":
                        if not item.isreg() or item.mode != 0o600 or archive.extractfile(item).read() != value:
                            raise ValueError("Runtime file readback differs: " + name)
                    elif not item.issym() or item.linkname != value:
                        raise ValueError("Runtime alias readback differs: " + name)
                else:
                    raise ValueError("Unexpected runtime object: " + name)
        if seen != set(tree) | directories:
            raise ValueError("Runtime readback is incomplete")
        report["bootAfter"] = call(["shell", "cat", "/proc/sys/kernel/random/boot_id"]).decode().strip()
        if report["bootAfter"] != report["bootBefore"]:
            raise ValueError("Device boot changed during runtime deployment")
        report["verified"] = True
    finally:
        (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n", encoding="utf-8")
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
