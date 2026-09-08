"""Attest the distinct application launcher; no device-execution assertion."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[3]
BOOTSTRAP = "libfoldgpt_app_bootstrap.so"
TRANSPORT = "libfoldgpt_app_transport.so"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def admit_builds(admission, transport, inventory):
    admission, transport = Path(admission).resolve(), Path(transport).resolve()
    for path in (admission, transport):
        path.relative_to(ROOT)
    bootstrap = (admission / BOOTSTRAP).read_bytes()
    library = (transport / TRANSPORT).read_bytes()
    bootstrap_build = json.loads((admission / "build.json").read_bytes())
    transport_build = json.loads((transport / "build.json").read_bytes())
    sources = ((admission, "native-bootstrap.c", ROOT / "tools/executor/runas-runtime/native-bootstrap.c", bootstrap_build),
               (transport, "app-spawn.c", ROOT / "tools/executor/shizuku-service/transport/src/main/cpp/app-spawn.c", transport_build))
    for directory, name, current, record in sources:
        built_source = (directory / name).read_bytes()
        if built_source != current.read_bytes() or digest(built_source) != record.get("sourceSha256"):
            raise ValueError("Application launcher build differs from its reviewed source: " + name)
    if (admission / "runtime-inventory.h").read_bytes() != inventory:
        raise ValueError("Application launcher build uses another runtime inventory")
    record = {"schema": "foldgpt.app-launch-build.v1", "launchOrigin": "android-app",
              "androidProductionExecuted": False, "bootstrapBuild": bootstrap_build,
              "transportBuild": transport_build}
    verify(record, {BOOTSTRAP: digest(bootstrap), TRANSPORT: digest(library)},
           {BOOTSTRAP: bootstrap, TRANSPORT: library}.__getitem__)
    if bootstrap_build["inventorySha256"] != digest(inventory):
        raise ValueError("Application launcher inventory digest differs")
    return record, {BOOTSTRAP: bootstrap, TRANSPORT: library}


def verify(record, libraries, read_library):
    if (type(record) is not dict or set(record) != {"schema", "launchOrigin", "androidProductionExecuted", "bootstrapBuild", "transportBuild"}
            or record["schema"] != "foldgpt.app-launch-build.v1" or record["launchOrigin"] != "android-app"
            or record["androidProductionExecuted"] is not False):
        raise ValueError("Application launcher attestation schema differs")
    bootstrap, transport = record["bootstrapBuild"], record["transportBuild"]
    if (type(bootstrap) is not dict or set(bootstrap) != {"schema", "androidExecuted", "sourceSha256", "inventorySha256",
            "cryptoSha256", "executableSha256", "runtimeHome", "ndk", "launchOrigin", "executableName", "inheritedSeccomp"}
            or bootstrap["schema"] != "foldgpt.native-admission-build.v2" or bootstrap["launchOrigin"] != "android-app"
            or bootstrap["executableName"] != BOOTSTRAP or type(bootstrap["inheritedSeccomp"]) is not int
            or bootstrap["inheritedSeccomp"] != 2 or bootstrap["androidExecuted"] is not False
            or bootstrap["runtimeHome"] != "/data/user/0/app.foldgpt/files/native-runtime-v1/python"
            or bootstrap["cryptoSha256"] != "a0dd60d620cd61bac7306a8293bcb82103971a4dcfc8c11fd55be3653beb42c4"):
        raise ValueError("Application bootstrap build is not the distinct Android profile")
    if (type(transport) is not dict or set(transport) != {"schema", "androidExecuted", "sourceSha256", "librarySha256", "ndk"}
            or transport["schema"] != "foldgpt.app-transport-build.v1" or transport["androidExecuted"] is not False):
        raise ValueError("Application transport build schema differs")
    for build in (bootstrap, transport):
        if build["ndk"] != "29.0.14206865":
            raise ValueError("Application launcher requires the admitted NDK build")
        for key, value in build.items():
            if key.endswith("Sha256") and (type(value) is not str or re.fullmatch("[0-9a-f]{64}", value) is None):
                raise ValueError("Malformed application launcher build digest")
    for name, expected in ((BOOTSTRAP, bootstrap["executableSha256"]), (TRANSPORT, transport["librarySha256"])):
        data = read_library(name)
        if not data.startswith(b"\x7fELF") or digest(data) != expected or libraries.get(name) != expected:
            raise ValueError("Application launcher bytes differ from their build: " + name)
    return "android-app"
