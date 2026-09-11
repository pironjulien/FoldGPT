"""Package a debug candidate from explicit, pinned local inputs; never install it.

record-inputs captures reviewed payloads and installed toolchains. build admits
that snapshot and preserves build/source/signature evidence. Neither step proves
upstream authenticity, a clean-clone native rebuild, or Android qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from executor_package import validate_package, verify_apk

SCHEMA = "foldgpt.candidate-inputs.v1"
PAYLOADS = ("executor", "runtimeJni", "x11Jni", "transportJni", "debugJni", "debugAssets")
TOOLCHAINS = ("jdk", "gradleHome", "sdkPlatform", "sdkBuildTools", "sdkNdk", "sdkCmake")
RUNTIME = {"arm64-v8a/" + name for name in (
    "libproot.so", "libproot-loader.so", "libproot-loader32.so", "libtalloc.so", "libandroid-shmem.so")}
TRANSPORT = {"arm64-v8a/" + name for name in ("libfoldgpt_shizuku_transport.so", "libfoldgpt_bionic_cwd.so")}


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def digest_file(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Duplicate descriptor key: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=pairs)


def inventory(directory, *, toolchain=False):
    """Inventory effective bytes, including explicit Linux toolchain file links."""
    directory = Path(directory).resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("Input must be a directory: " + str(directory))
    rows = {}
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory).as_posix()
        if path.is_symlink():
            if not toolchain or path.is_dir():
                raise ValueError("Payload/directory link requires a self-contained snapshot: " + str(path))
            row = {"link": os.readlink(path)}
            # Distribution toolchains can include unused dangling source links.
            # Executable prerequisites are checked separately with is_file().
            if path.exists():
                if not path.is_file():
                    raise ValueError("Special toolchain link: " + str(path))
                row.update(bytes=path.stat().st_size, sha256=digest_file(path))
            rows[relative] = row
            continue
        if hasattr(path, "is_junction") and path.is_junction():
            raise ValueError("Input directory junction requires a self-contained snapshot: " + str(path))
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Nonregular build input: " + str(path))
        rows[relative] = {"bytes": path.stat().st_size, "sha256": digest_file(path)}
    if not rows:
        raise ValueError("Input directory is empty: " + str(directory))
    return rows


def path_record(path):
    path = Path(path).resolve(strict=True)
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def descriptor_path(value):
    if not isinstance(value, str) or not value:
        raise ValueError("Expected an explicit input path")
    path = Path(value)
    return (path if path.is_absolute() else ROOT / path).resolve(strict=True)


def output_path(value):
    path = Path(value)
    path = (path if path.is_absolute() else ROOT / path).resolve()
    relative = path.relative_to(ROOT.resolve())
    if len(relative.parts) < 2 or relative.parts[0] not in {"work", "downloads"}:
        raise ValueError("Output must be a new child beneath the project's work/ or downloads/")
    if path.exists():
        raise FileExistsError("Existing attempts are retained: " + str(path))
    return path


def write_new(path, value):
    with Path(path).open("xb") as stream:
        stream.write(canonical(value))


def validate_source_closure(executor):
    assets = executor / "assets"
    manifest = strict_json((assets / "foldgpt-executor-manifest.json").read_bytes())
    expected = {row["path"]: row["sha256"] for row in manifest}
    actual = inventory(assets / "foldgpt-executor")
    if len(expected) != len(manifest) or {name: row["sha256"] for name, row in actual.items()} != expected:
        raise ValueError("Executor source manifest differs from its complete payload")
    transport = ROOT / "tools/executor/shizuku-service/transport/src/main/assets/foldgpt-executor"
    for name in expected:
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("Noncanonical executor source path")
        source = ROOT / name if name.startswith("tools/") else transport / name
        packaged = (assets / "foldgpt-executor" / name).read_bytes()
        current = source.read_bytes() if source.is_file() else b"" if name.endswith("/__init__.py") else None
        if current is None or current.replace(b"\r\n", b"\n") != packaged.replace(b"\r\n", b"\n"):
            raise ValueError("Executor source differs from current checkout; restage it: " + name)
    return len(expected)


def validate_payloads(paths, trees):
    for key, required in (("runtimeJni", RUNTIME), ("x11Jni", {"arm64-v8a/libXlorie.so"}), ("transportJni", TRANSPORT)):
        names = set(trees[key]) - ({"build-manifest.json"} if key == "x11Jni" else set())
        if names != required:
            raise ValueError("Unexpected or missing files in " + key)
    if "build-manifest.json" in trees["x11Jni"]:
        provenance = strict_json((paths["x11Jni"] / "build-manifest.json").read_bytes())
        if provenance.get("sha256") != trees["x11Jni"]["arm64-v8a/libXlorie.so"]["sha256"]:
            raise ValueError("X11 build-manifest.json does not identify the selected library; select matching reviewed build inputs")
    report = validate_package(paths["executor"])
    deployment = strict_json((paths["executor"] / "assets/foldgpt-executor-deployment.json").read_bytes())
    for name in TRANSPORT:
        if trees["transportJni"][name]["sha256"] != deployment["nativeLibraries"].get(PurePosixPath(name).name):
            raise ValueError("Frozen transport differs from executor deployment: " + name)
    report["currentSourceFiles"] = validate_source_closure(paths["executor"])
    return report


def tool_paths(args):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", args.build_tools):
        raise ValueError("Select an exact SDK build-tools version")
    if args.sdk_platform not in {"android-37", "android-37.0"}:
        raise ValueError("Select the installed stable API 37 platform directory")
    sdk, gradle = args.sdk.resolve(strict=True), args.gradle.resolve(strict=True)
    executable = ".exe" if os.name == "nt" else ""
    paths = {"jdk": args.jdk.resolve(strict=True), "gradleHome": gradle.parent.parent,
             "sdkPlatform": sdk / "platforms" / args.sdk_platform, "sdkBuildTools": sdk / "build-tools" / args.build_tools,
             "sdkNdk": sdk / "ndk/29.0.14206865", "sdkCmake": sdk / "cmake/3.22.1"}
    for path in (gradle, paths["jdk"] / ("bin/java" + executable), paths["jdk"] / ("bin/javac" + executable),
                 paths["sdkPlatform"] / "android.jar", paths["sdkNdk"] / "source.properties",
                 paths["sdkCmake"] / ("bin/cmake" + executable),
                 paths["sdkBuildTools"] / ("apksigner.bat" if os.name == "nt" else "apksigner")):
        if not path.is_file():
            raise FileNotFoundError("Missing selected Android tool: " + str(path))
    if gradle.name not in {"gradle", "gradle.bat"} or gradle.parent.name != "bin":
        raise ValueError("Select bin/gradle or bin/gradle.bat from a Gradle distribution")
    return sdk, gradle, paths


def record_inputs(args):
    output = output_path(args.output)
    sdk, gradle, paths = tool_paths(args)
    paths.update({key: getattr(args, key).resolve(strict=True) for key in PAYLOADS})
    trees = {key: inventory(paths[key]) for key in PAYLOADS}
    validate_payloads(paths, trees)
    trees.update({key: inventory(paths[key], toolchain=True) for key in TOOLCHAINS})
    descriptor = {"schema": SCHEMA, "scope": "Local byte inventory; upstream provenance and device qualification are separate",
                  "sdk": path_record(sdk), "gradle": path_record(gradle), "buildToolsVersion": args.build_tools,
                  "sdkPlatformDirectory": args.sdk_platform,
                  "inputs": {key: {"path": path_record(paths[key]), "files": trees[key]} for key in sorted(paths)}}
    output.parent.mkdir(parents=True, exist_ok=True)
    write_new(output, descriptor)
    return {"inputs": str(output), "sha256": digest_file(output), "files": sum(map(len, trees.values()))}


def admit_inputs(path, trusted_sha):
    if not re.fullmatch(r"[0-9a-f]{64}", trusted_sha):
        raise ValueError("An independently retained lowercase descriptor SHA-256 is required")
    data = Path(path).read_bytes()
    if hashlib.sha256(data).hexdigest() != trusted_sha:
        raise ValueError("Input descriptor digest differs")
    descriptor = strict_json(data)
    if (set(descriptor) != {"schema", "scope", "sdk", "gradle", "buildToolsVersion", "sdkPlatformDirectory", "inputs"}
            or descriptor["schema"] != SCHEMA or set(descriptor["inputs"]) != set(PAYLOADS + TOOLCHAINS)):
        raise ValueError("Unsupported or incomplete candidate input descriptor")
    paths, trees = {}, {}
    for name, record in descriptor["inputs"].items():
        if set(record) != {"path", "files"}:
            raise ValueError("Invalid input record: " + name)
        paths[name] = descriptor_path(record["path"])
        trees[name] = inventory(paths[name], toolchain=name in TOOLCHAINS)
        if trees[name] != record["files"]:
            raise ValueError("Input inventory/hash differs: " + name)
    sdk, _, toolchain = tool_paths(argparse.Namespace(sdk=descriptor_path(descriptor["sdk"]),
        gradle=descriptor_path(descriptor["gradle"]), jdk=paths["jdk"], build_tools=descriptor["buildToolsVersion"],
        sdk_platform=descriptor["sdkPlatformDirectory"]))
    if any(paths[key] != value.resolve(strict=True) for key, value in toolchain.items()):
        raise ValueError("Toolchain paths differ from the selected SDK/JDK/Gradle")
    report = validate_payloads(paths, trees)
    local = ROOT / "android/local.properties"
    if local.exists():
        for line in local.read_text(encoding="utf-8").splitlines():
            match = re.fullmatch(r"\s*(sdk\.dir|ndk\.dir)\s*[:=]\s*(.*?)\s*", line)
            if match:
                value = match[2].replace("\\:", ":").replace("\\\\", "\\")
                expected = sdk if match[1] == "sdk.dir" else paths["sdkNdk"]
                if Path(value).resolve(strict=True) != expected:
                    raise ValueError("android/local.properties selects a different " + match[1])
    return descriptor, paths, report


def source_inventory():
    roots = ("android", "tools", "runtime", "config", "plugins", "compat")
    flags = ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    names = subprocess.check_output([*flags, "--", *roots], cwd=ROOT).decode().split("\0")
    vendor_names = subprocess.check_output(flags, cwd=ROOT / "vendor/termux-x11").decode().split("\0")
    names += ["vendor/termux-x11/" + name for name in vendor_names if name]
    rows = {}
    for name in sorted(set(names)):
        if name and (ROOT / name).is_file():
            rows[name] = {"bytes": (ROOT / name).stat().st_size, "sha256": digest_file(ROOT / name)}
    if not rows:
        raise ValueError("No tracked build sources found")
    return rows


def command_for(descriptor, paths):
    command = [str(descriptor_path(descriptor["gradle"])), "--no-daemon", "--max-workers=2", "--no-parallel",
               "-Dorg.gradle.jvmargs=-Xmx1g -Dfile.encoding=UTF-8", "-PfoldgptRequireExecutor=true",
               "-PfoldgptBuildToolsVersion=" + descriptor["buildToolsVersion"]]
    for prop, key in (("foldgptRuntimeJni", "runtimeJni"), ("foldgptX11Jni", "x11Jni"),
                      ("foldgptFrozenTransportJni", "transportJni"), ("foldgptDebugJni", "debugJni"), ("foldgptDebugAssets", "debugAssets")):
        command.append("-P" + prop + "=" + str(paths[key]))
    return command + ["-PfoldgptExecutorAssets=" + str(paths["executor"] / "assets"),
                     "-PfoldgptExecutorJni=" + str(paths["executor"] / "jniLibs"),
                     ":app:assembleDebug", ":shizukuTransport:testDebugUnitTest"]


def verify_packaged_inputs(apk, descriptor):
    with ZipFile(apk) as archive:
        if len(archive.namelist()) != len(set(archive.namelist())):
            raise ValueError("Duplicate APK entries")
        expected = {}
        for key in ("debugJni", "runtimeJni", "x11Jni", "transportJni"):
            expected.update({"lib/" + name: row for name, row in descriptor["inputs"][key]["files"].items()
                             if name.endswith(".so")})
        # Explicit executor JNI replaces selected duplicate debug JNI in Gradle.
        expected.update({"lib/" + name.removeprefix("jniLibs/"): row
                         for name, row in descriptor["inputs"]["executor"]["files"].items() if name.startswith("jniLibs/")})
        expected.update({"assets/" + name: row for name, row in descriptor["inputs"]["debugAssets"]["files"].items()})
        expected.update({name: row for name, row in descriptor["inputs"]["executor"]["files"].items() if name.startswith("assets/")})
        for name, row in expected.items():
            data = archive.read(name)
            if len(data) != row["bytes"] or hashlib.sha256(data).hexdigest() != row["sha256"]:
                raise ValueError("Packaged input differs: " + name)


def build_candidate(args):
    if not re.fullmatch(r"[A-Za-z0-9]+", args.candidate):
        raise ValueError("Candidate must be an ASCII alphanumeric name")
    output = output_path(args.output)
    descriptor, paths, package = admit_inputs(args.inputs, args.inputs_sha256)
    command = command_for(descriptor, paths)
    if args.preflight_only:
        return {"preflight": "PASS", "output": str(output), "package": package, "argv": command, "deviceQualified": False}
    if not args.signing_keystore or not args.signing_cert_sha256:
        raise ValueError("Candidate builds require an explicit signing keystore and certificate SHA-256")
    key, cert = args.signing_keystore.resolve(strict=True), args.signing_cert_sha256.replace(":", "").lower()
    if not key.is_file() or not re.fullmatch(r"[0-9a-f]{64}", cert):
        raise ValueError("Invalid signing keystore or certificate SHA-256")
    sources = source_inventory()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(exist_ok=False)
    write_new(output / "inputs.json", descriptor)
    write_new(output / "sources.json", sources)
    (output / "tmp").mkdir()
    env = dict(os.environ)
    env.update(JAVA_HOME=str(paths["jdk"]), ANDROID_HOME=str(descriptor_path(descriptor["sdk"])),
               ANDROID_SDK_ROOT=str(descriptor_path(descriptor["sdk"])),
               FOLDGPT_SIGNING_KEYSTORE=str(key), FOLDGPT_SIGNING_CERT_SHA256=cert,
               GRADLE_USER_HOME=str(ROOT / "work/build-cache/gradle"),
               TEMP=str(output / "tmp"), TMP=str(output / "tmp"), TMPDIR=str(output / "tmp"))
    report = {"schema": "foldgpt.candidate-build.v1", "candidate": args.candidate, "success": False,
              "inputDescriptorSha256": args.inputs_sha256, "sourceInventorySha256": digest_file(output / "sources.json"),
              "gitHead": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "argv": command, "signingCertificateSha256": cert, "deviceQualified": False,
              "scope": "Debug APK from existing pinned inputs; fresh install and bit-for-bit rebuild unqualified"}
    def run(name, argv):
        with (output / (name + ".log")).open("xb") as log:
            result = subprocess.run(argv, cwd=ROOT / "android", env=env, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(name + " failed; see " + str(output / (name + ".log")))
    try:
        run("java-version", [str(paths["jdk"] / ("bin/java.exe" if os.name == "nt" else "bin/java")), "-version"])
        run("gradle-version", [command[0], "--version"])
        # These are real host-JVM tests. The Android unit-test bootclasspath
        # cannot compile the separate HTTPS fixture's jdk.httpserver module.
        # Keep that fixture and its Linux runner; never silently exclude it.
        run("lifecycle-tests", [sys.executable, "-B", str(ROOT / "tools/runtime/test-native-lifecycle-windows.py"),
            "--java-home", str(paths["jdk"]), "--fetch-dependencies", "--output", str(output / "lifecycle")])
        run("gradle-build", command)
        if source_inventory() != sources:
            raise ValueError("Sources changed during compilation; candidate not admitted")
        admit_inputs(args.inputs, args.inputs_sha256)
        staged = output / "unverified.apk"
        with staged.open("xb") as target, (ROOT / "android/app/build/outputs/apk/debug/app-debug.apk").open("rb") as source:
            shutil.copyfileobj(source, target)
        verify_packaged_inputs(staged, descriptor)
        run("executor-verification", [sys.executable, "-B", str(ROOT / "tools/executor/runas-runtime/verify-production-apk.py"),
            str(staged), "--output", str(output / "executor-verification.json")])
        run("apk-contents", [sys.executable, "-B", str(ROOT / "tools/install/verify-apk-contents.py"), str(staged), "--debug"])
        run("apk-signature", [str(paths["sdkBuildTools"] / ("apksigner.bat" if os.name == "nt" else "apksigner")),
            "verify", "--verbose", "--print-certs", str(staged)])
        signature = (output / "apk-signature.log").read_text(encoding="utf-8")
        actual = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]+)", signature)
        if [value.lower() for value in actual] != [cert]:
            raise ValueError("Built APK signing certificate differs from the required identity")
        embedding = verify_apk(staged, paths["executor"])
        apk = output / ("FoldGPT-" + args.candidate + ".apk")
        os.link(staged, apk)  # Exclusive publication; never overwrites an artifact.
        staged.unlink()
        embedding["apk"] = str(apk)
        report.update(success=True, apk=str(apk), apkSha256=digest_file(apk), apkBytes=apk.stat().st_size,
                      package=package, embedding=embedding)
    except Exception as error:
        report["failure"] = str(error)
        raise
    finally:
        write_new(output / "build-report.json", report)
    return report


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="action", required=True)
    record = commands.add_parser("record-inputs", help="Inventory explicitly selected reviewed inputs into a new local manifest")
    for name, flag in (("executor", "package"), ("runtimeJni", "runtime-jni"), ("x11Jni", "x11-jni"),
                       ("transportJni", "transport-jni"), ("debugJni", "debug-jni"), ("debugAssets", "debug-assets")):
        record.add_argument("--" + flag, dest=name, type=Path, required=True)
    for name in ("sdk", "jdk", "gradle", "output"):
        record.add_argument("--" + name, type=Path, required=True)
    record.add_argument("--build-tools", required=True, help="Installed SDK build-tools version, e.g. 36.0.0")
    record.add_argument("--sdk-platform", required=True, help="Installed stable API 37 platform directory, e.g. android-37.0")
    build = commands.add_parser("build", help="Admit pinned inputs, compile and verify without installing")
    build.add_argument("--inputs", type=Path, required=True)
    build.add_argument("--inputs-sha256", required=True)
    build.add_argument("--candidate", required=True)
    build.add_argument("--output", type=Path, required=True, help="New directory beneath this project's work/ or downloads/")
    build.add_argument("--signing-keystore", type=Path)
    build.add_argument("--signing-cert-sha256")
    build.add_argument("--preflight-only", action="store_true", help="Read-only admission; do not create output or execute Gradle")
    return result


if __name__ == "__main__":
    args = parser().parse_args()
    print(json.dumps(record_inputs(args) if args.action == "record-inputs" else build_candidate(args), indent=2))
