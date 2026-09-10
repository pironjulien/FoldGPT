"""Validate the reviewed native executor package and its APK embedding."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "config/android/executor-package.json"


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_contract() -> dict:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    if contract.get("schema") != "foldgpt.executor.package.v1":
        raise ValueError("Unsupported executor package contract")
    required = {"abi", "assets", "deploymentInventory", "jniExcludedFromPackage"}
    if set(contract) != {"schema", *required}:
        raise ValueError("Executor package contract has unexpected or missing fields")
    if not isinstance(contract["assets"], list) or not contract["assets"]:
        raise ValueError("Executor package contract must list assets")
    return contract


def validate_package(package: Path) -> dict:
    contract = load_contract()
    package = package.resolve(strict=True)
    assets = package / "assets"
    jni = package / "jniLibs" / contract["abi"]
    if not assets.is_dir() or not jni.is_dir():
        raise ValueError("Executor package must contain assets and ABI JNI directories")
    for name in contract["assets"]:
        if not (assets / name).is_file():
            raise ValueError(f"Executor package is missing required asset: {name}")
    deployment = json.loads((assets / contract["deploymentInventory"]).read_text(encoding="utf-8"))
    native = deployment.get("nativeLibraries")
    if not isinstance(native, dict) or not native:
        raise ValueError("Executor deployment inventory has no nativeLibraries")
    excluded = set(contract["jniExcludedFromPackage"])
    expected = set(native) - excluded
    actual = {p.relative_to(jni).as_posix() for p in jni.rglob("*") if p.is_file()}
    if actual != expected:
        raise ValueError(f"Executor JNI inventory differs: missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}")
    for name in sorted(expected):
        if _digest(jni / name) != native[name]:
            raise ValueError(f"Executor JNI digest differs: {name}")
    return {"package": str(package), "abi": contract["abi"], "nativeLibraries": len(expected), "assets": list(contract["assets"])}


def verify_apk(apk: Path, package: Path) -> dict:
    contract = load_contract()
    package_report = validate_package(package)
    assets = package / "assets"
    deployment = json.loads((assets / contract["deploymentInventory"]).read_text(encoding="utf-8"))
    expected = set(deployment["nativeLibraries"]) - set(contract["jniExcludedFromPackage"])
    with ZipFile(apk) as archive:
        names = set(archive.namelist())
        missing_assets = {f"assets/{name}" for name in contract["assets"]} - names
        if missing_assets:
            raise ValueError(f"APK is missing executor assets: {sorted(missing_assets)}")
        missing_native = {f"lib/{contract['abi']}/{name}" for name in expected} - names
        if missing_native:
            raise ValueError(f"APK is missing executor JNI libraries: {sorted(missing_native)}")
        bad = []
        for name in sorted(expected):
            digest = hashlib.sha256(archive.read(f"lib/{contract['abi']}/{name}")).hexdigest()
            if digest != deployment["nativeLibraries"][name]:
                bad.append(name)
        if bad:
            raise ValueError(f"APK executor JNI digest differs: {bad}")
    return {**package_report, "apk": str(apk.resolve()), "apkNativeLibraries": len(expected)}
