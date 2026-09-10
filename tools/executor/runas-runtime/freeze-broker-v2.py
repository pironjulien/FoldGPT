from pathlib import Path
import hashlib
import json
import shutil
import zipfile

root = Path(__file__).resolve().parents[3]
service = root / "tools/executor/shizuku-service"
module = service / "runasbrokerqualificationv2"
apk = service / "build/runasbrokerqualification-v2/modules/runasbrokerqualification/outputs/apk/debug/runasbrokerqualificationv2-debug.apk"
stage = service / "build/runasbrokerqualification-v2/stage-r2"
destination = root / "downloads/runas-qualification/broker-v2"
destination.mkdir(parents=True, exist_ok=False)
with zipfile.ZipFile(apk) as archive:
    config = json.loads(archive.read("assets/foldgpt-runas-broker-config.json"))
    libraries = [name for name in archive.namelist() if name.startswith("lib/")]
    assert len(libraries) == len(set(libraries)) == 86
    for name, expected in config["nativeLibraries"].items():
        assert hashlib.sha256(archive.read("lib/arm64-v8a/" + name)).hexdigest() == expected
    assert archive.read("assets/foldgpt-runas-broker/foldgpt_runas_broker.py") == (module / "foldgpt_runas_broker.py").read_bytes()
    for name in ("libfoldgpt_runas_broker_bootstrap.so", "libfoldgpt_shizuku_transport.so", "libfoldgpt_bionic_cwd.so"):
        target = destination / "extra-native" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(archive.read("lib/arm64-v8a/" + name))
shutil.copyfile(apk, destination / "runasbrokerqualification-debug.apk")
shutil.copytree(stage, destination / "stage-r2")
shutil.copytree(root / "downloads/runas-worker-v2-20260908", destination / "worker-build")
sources = list(module.glob("*.py")) + [module / "build.gradle", module / "README.md", service / "settings.gradle"]
sources += [path for path in (module / "src").rglob("*") if path.is_file()]
for source in sources:
    target = destination / "sources" / source.relative_to(service)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
inventory = {"schema": "foldgpt.runas-broker-release-inputs.v2", "package": "app.foldgpt.runasbrokerqualification.v2",
             "target": "app.foldgpt", "deviceExecuted": False,
             "signerSha256": "30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16",
             "files": [{"path": path.relative_to(destination).as_posix(), "bytes": path.stat().st_size,
                        "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                       for path in sorted(destination.rglob("*")) if path.is_file()]}
(destination / "manifest.json").write_text(json.dumps(inventory, indent=2) + "\n", encoding="utf-8")
for entry in inventory["files"]:
    assert hashlib.sha256((destination / entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
print(json.dumps({"destination": str(destination), "files": len(inventory["files"]),
                  "apkSha256": hashlib.sha256(apk.read_bytes()).hexdigest()}, indent=2))
