"""Freeze real Fold qualification inputs beside the Windows human ELF.

Preparation only. No device, build of the model runner, or runtime activation.
"""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TRANSPORT = ROOT / "tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor"
MODEL_HASHES = {
    "runner.c": "7d1b2b66763ec16d5ba49a25a001ca02899ab9b67d3c72a4a3cc23524b279805",
    "processes.py": "c756cba658a2e07d98f65f4ef28995682fd2e8a9a8547f3e596ac6c5ec3c8194",
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build, output = args.build.resolve(strict=True), args.output.resolve()
    build.relative_to(ROOT)
    output.relative_to(ROOT)
    for name, expected in MODEL_HASHES.items():
        if digest((ROOT / "tools/executor/bionic-supervisor" / name).read_bytes()) != expected:
            raise ValueError("Qualified model source changed: " + name)
    record = json.loads((build / "build.json").read_text())
    elf = (build / "libfoldgpt_host_supervisor.so").read_bytes()
    if digest(elf) != record["elf"]["sha256"] or not record["reproducible"]:
        raise ValueError("Built human ELF differs or has no repeated-byte proof")
    roots = ["tools.executor.bionic-supervisor.test_host_fold",
             "tools.executor.native_host_channel_v2"]
    pending, seen, files = list(roots), set(), []
    output.mkdir(parents=True, exist_ok=False)
    package = output / "package"
    while pending:
        module = pending.pop()
        if module in seen:
            continue
        seen.add(module)
        if module.startswith("tools."):
            relative = Path(*module.split(".")).with_suffix(".py")
            source = ROOT / relative
        elif module.startswith("foldgpt_"):
            relative = Path(module + ".py")
            source = TRANSPORT / relative
        else:
            continue
        if not source.is_file():
            raise ValueError("Qualification dependency source is absent: " + module)
        data = source.read_bytes()
        tree = ast.parse(data, str(relative))
        compile(tree, str(relative), "exec")
        target = package / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        files.append({"path": relative.as_posix(), "bytes": len(data), "sha256": digest(data)})
        namespace = module.rpartition(".")[0]
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                pending.extend(item.name for item in node.names)
            elif isinstance(node, ast.ImportFrom):
                name = "." * node.level + (node.module or "")
                if node.level:
                    name = importlib.util.resolve_name(name, namespace)
                pending.append(name)
            elif (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "import_module" and node.args
                    and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str)):
                pending.append(node.args[0].value)
    for directory in sorted({parent for path in package.rglob("*.py") for parent in path.parents
                             if parent != package and package in parent.parents}):
        target = directory / "__init__.py"
        if not target.exists():
            target.write_bytes(b"")
            files.append({"path": target.relative_to(package).as_posix(), "bytes": 0, "sha256": digest(b"")})
    (output / "libfoldgpt_host_supervisor.so").write_bytes(elf)
    sources = Path(__file__).read_bytes()
    (output / Path(__file__).name).write_bytes(sources)
    manifest = {"schema": "foldgpt.native.human-qualification-prepared.v1",
                "androidExecuted": False, "productionSelected": False,
                "rustChanged": False, "modelSourceSha256": MODEL_HASHES,
                "hostRunnerSha256": digest(elf), "hostRunnerBytes": len(elf),
                "buildRecordSha256": digest((build / "build.json").read_bytes()),
                "freezeScriptSha256": digest(sources), "sources": sorted(files, key=lambda item: item["path"])}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), "sources": len(files),
                      "hostRunnerSha256": digest(elf), "androidExecuted": False}))


if __name__ == "__main__":
    main()
