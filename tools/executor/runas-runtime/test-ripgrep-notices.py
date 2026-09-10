"""Verify native rg notice admission and package rejection against real files."""
import argparse
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source, package, output = args.source.resolve(strict=True), args.package.resolve(strict=True), args.output.resolve()
    for path in (source, package, output): path.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    spec = importlib.util.spec_from_file_location("notice_test", Path(__file__).with_name("ripgrep-notices.py"))
    notice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(notice)
    assets, provenance = notice.production_toolchain_notices(source)
    qualification = json.loads((package / "assets/foldgpt-executor-qualification.json").read_text(encoding="utf-8"))
    names = [p.relative_to(package / "assets").as_posix() for p in (package / "assets").rglob("*") if p.is_file()]
    count = notice.verify_assets(qualification, lambda name: (package / "assets" / name).read_bytes(), names)
    if count != len(assets) - 1 or qualification["ripgrepToolchainNotices"] != provenance:
        raise AssertionError("Actual packaged notice contract differs")
    results = [{"case": "actual-source-and-package-pass", "passed": True, "noticeFiles": count}]
    if notice.verify_assets({}, lambda _: b"", []) != 0: raise AssertionError("r23 compatibility failed")
    results.append({"case": "package-without-rg-remains-supported", "passed": True})

    def rejected(name, call):
        try: call()
        except (ValueError, FileNotFoundError) as error:
            results.append({"case": name, "passed": True, "error": str(error)})
        else: raise AssertionError("Invalid notices were accepted: " + name)

    fixture = output / "source-fixture"
    shutil.copytree(source, fixture)
    selected = "rust/licenses/MIT.txt"
    path = fixture / selected
    before = path.read_bytes()
    path.write_bytes(before + b"changed")
    rejected("modified-source-notice", lambda: notice.production_toolchain_notices(fixture))
    path.write_bytes(before)
    extra = fixture / "undeclared.txt"
    extra.write_bytes(b"extra")
    rejected("extra-source-notice", lambda: notice.production_toolchain_notices(fixture))
    extra.unlink()
    path.unlink()
    rejected("missing-source-notice", lambda: notice.production_toolchain_notices(fixture))
    path.write_bytes(before)
    manifest = fixture / "manifest.json"
    original = manifest.read_bytes()
    manifest.write_bytes(original + b" ")
    rejected("changed-capture-manifest", lambda: notice.production_toolchain_notices(fixture))
    manifest.write_bytes(original)

    def verify_fake(content, q=None):
        notice.verify_assets(qualification if q is None else q, content.__getitem__, content.keys())

    target = notice.PREFIX + selected
    fake = dict(assets)
    del fake[target]
    rejected("missing-packaged-notice", lambda: verify_fake(fake))
    fake = {**assets, notice.PREFIX + "extra.txt": b"extra"}
    rejected("extra-packaged-notice", lambda: verify_fake(fake))
    fake = {**assets, target: assets[target] + b"changed"}
    rejected("modified-packaged-notice", lambda: verify_fake(fake))
    fake = {**assets, notice.PREFIX + "manifest.json": b"{}"}
    q = copy.deepcopy(qualification)
    q["ripgrepToolchainNotices"]["assetManifestSha256"] = hashlib.sha256(b"{}").hexdigest()
    rejected("self-rehashed-hostile-manifest", lambda: verify_fake(fake, q))
    q = copy.deepcopy(qualification)
    q["ripgrepToolchainNotices"]["rustToolchain"] = "1.96.0"
    rejected("wrong-toolchain-provenance", lambda: verify_fake(assets, q))
    q = copy.deepcopy(qualification)
    q["ripgrepToolchainNotices"]["path"] = "../outside"
    rejected("provenance-path-traversal", lambda: verify_fake(assets, q))
    q = copy.deepcopy(qualification)
    del q["ripgrepToolchainNotices"]
    rejected("rg-without-toolchain-notice-attestation", lambda: verify_fake(assets, q))
    rejected("notices-without-rg", lambda: verify_fake(assets, {}))
    report = {"schema": "foldgpt.ripgrep-notices-tests.v1", "passed": True, "tests": results,
              "package": package.relative_to(ROOT).as_posix(), "provenance": provenance, "androidExecuted": False}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "tests": len(results), "noticeFiles": count, "output": str(output / "report.json")}))


if __name__ == "__main__": main()
