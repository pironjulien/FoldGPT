"""Preserve the completed device identity evidence in the private recovery tree."""
import hashlib
import json
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / "downloads/runas-identity-v1"
destination = root / "recovery/verification/runas-identity-20260908"
verification = json.loads((source / "verification.json").read_text())
if verification.get("passed") is not True:
    raise ValueError("Passing independently collected identity evidence required")
sources = [source / "verification.json"]
for folder in ("before-install-verified", "device-reports", "after-run"):
    sources.extend(sorted((source / folder).glob("*.json")))
records = []
destination.mkdir(parents=True, exist_ok=False)
for path in sources:
    relative = path.relative_to(source)
    output = destination / relative
    data = path.read_bytes()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(data)
    if output.read_bytes() != data:
        raise ValueError("Evidence copy differs")
    records.append({"path": relative.as_posix(), "source": path.relative_to(root).as_posix(),
                    "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
manifest = {"scope": verification["scope"], "passed": True, "files": records}
(destination / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"output": str(destination), "files": len(records)}))
