"""Production admission for the source-attested native ripgrep/JIT double build."""
import hashlib
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]

def production_ripgrep(build):
    build = Path(build).resolve(strict=True)
    build.relative_to(ROOT)
    spec = importlib.util.spec_from_file_location("foldgpt_ripgrep_verifier", ROOT / "tools/executor/bionic-runtime/verify-ripgrep-build.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    record = checker.verify(build)
    outputs = {name: (build / name).read_bytes() for name in checker.FILES}
    executable = outputs["libfoldgpt_rg.so"]
    probe = outputs["libfoldgpt_pcre2_jit_probe.so"]
    return outputs, {"path": build.relative_to(ROOT).as_posix(),
        "buildManifestSha256": checker.digest(build / "build.json"),
        "sourceManifestSha256": record["sourceManifestSha256"],
        "executableSha256": hashlib.sha256(executable).hexdigest(), "bytes": len(executable),
        "probeSha256": hashlib.sha256(probe).hexdigest(), "probeBytes": len(probe),
        "ripgrepVersion": record["pins"]["ripgrep"]["version"],
        "pcre2Version": record["pins"]["pcre2"]["version"],
        "pcre2Jit": True, "androidExecuted": False}
