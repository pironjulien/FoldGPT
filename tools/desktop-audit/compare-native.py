"""Compare two static native inventories without loading or executing client code."""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIELDS = (
    "machine", "elfClass", "osAbi", "type", "interpreter", "needed", "soname", "loaderSearch", "loadSegments",
    "versionRequirements", "highestReferencedGlibc", "highestReferencedGlibcxx", "abiEvidence", "undefinedSymbols",
    "structuralImports", "selectedExports", "napiImportCount", "definedStructuralFunctions")


def read(path):
    resolved = path.resolve()
    resolved.relative_to(ROOT)
    return json.loads(resolved.read_bytes())


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def index(inventory):
    result = {}
    for entry in inventory["entries"]:
        path = entry["path"].removeprefix("usr/lib/chatgpt/")
        if path in result:
            raise ValueError("Duplicate normalized client path")
        result[path] = entry
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installed", type=Path, required=True)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    installed, reference = read(args.installed), read(args.reference)
    actual, baseline = index(installed), index(reference)
    rows = []
    for path in sorted(actual.keys() | baseline.keys()):
        current, prior = actual.get(path), baseline.get(path)
        row = {"path": path, "presentInstalled": current is not None, "presentReference": prior is not None}
        for label, entry in (("installed", current), ("reference", prior)):
            if entry:
                row[label] = {key: entry[key] for key in ("sha256", "bytes")}
        if current and prior:
            row["identicalBytes"] = current["sha256"] == prior["sha256"]
            row["requirementChanges"] = {key: {"installed": current[key], "reference": prior[key]}
                                         for key in FIELDS if current[key] != prior[key]}
            row["moduleIdentityChanges"] = {
                key: {"installed": (current["packageIdentity"] or {}).get(key),
                      "reference": (prior["packageIdentity"] or {}).get(key)}
                for key in ("name", "version", "manifestSha256")
                if (current["packageIdentity"] or {}).get(key) != (prior["packageIdentity"] or {}).get(key)}
        rows.append(row)
    result = {"schema": "foldgpt.desktop-native-comparison.v1", "scope": "static ELF comparison; no client execution",
              "installedVersion": installed["packageVersion"], "referenceVersion": reference["packageVersion"],
              "installedAsarSha256": installed["asarSha256"], "referenceAsarSha256": reference["asarSha256"],
              "installedInventorySha256": sha(args.installed), "referenceInventorySha256": sha(args.reference),
              "comparedFields": list(FIELDS), "commonPathCount": len(actual.keys() & baseline.keys()),
              "onlyInstalledPaths": sorted(actual.keys() - baseline.keys()),
              "onlyReferencePaths": sorted(baseline.keys() - actual.keys()),
              "identicalByteCount": sum(row.get("identicalBytes") is True for row in rows),
              "changedByteCount": sum(row.get("identicalBytes") is False for row in rows),
              "changedRequirementCount": sum(bool(row.get("requirementChanges")) for row in rows),
              "changedModuleIdentityCount": sum(bool(row.get("moduleIdentityChanges")) for row in rows),
              "limits": ["Equal imported requirements do not establish equal behavior, implementation or confinement.",
                         "This compares collected ELF bytes, not runtime paths or the ASAR JavaScript behavior."],
              "entries": rows}
    output = args.output.resolve()
    output.relative_to(ROOT / "work")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "entries"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
