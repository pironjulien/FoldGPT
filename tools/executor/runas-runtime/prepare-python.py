"""Stage authenticated compiler inputs for the app-owned Bionic Python runtime.

Preparation only: no Android installation, execution or runtime admission.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
RUNTIME_HOME = "/data/user/0/app.foldgpt/files/runas-native-v1/python"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    source = ROOT / "tools/executor/bionic-runtime/python-package.py"
    spec = importlib.util.spec_from_file_location("foldgpt_python_package", source)
    package = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package)
    archive = ROOT / "downloads/native-python/inputs/python-3.14.7-aarch64-linux-android.tar.gz"
    contents = package.package(archive)
    # A new prefix preserves the earlier qualified deployment inputs exactly.
    output.mkdir(parents=True, exist_ok=False)
    prefix = output / "prefix"
    records = []
    for name, data in sorted(contents.items()):
        destination = prefix / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
        records.append({"path": name, "bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest()})
    result = {"schema": "foldgpt.runas-python-inputs.v1", "androidExecuted": False,
              "runtimeHome": RUNTIME_HOME, "package": package.PIN,
              "sourceSha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "files": records}
    (output / "inputs.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prefix": str(prefix), "runtimeHome": RUNTIME_HOME,
                      "files": len(records), "androidExecuted": False}))


if __name__ == "__main__":
    main()
