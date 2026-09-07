"""Independently collect a completed gm-* Android GNU process diagnostic.

Read-only: never executes the collected Python project, installs a package,
starts a service, or signals a process. Reuses the fixed GNU collector's bounded
ADB byte transport and native identity inspection.
"""
import argparse
import ast
import base64
from datetime import datetime, timezone
import importlib.util
import io
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import zipfile

spec = importlib.util.spec_from_file_location("fixed_gnu_collector", Path(__file__).with_name("collect-android.py"))
shared = importlib.util.module_from_spec(spec)
spec.loader.exec_module(shared)
require, sha = shared.require, shared.sha


def strict_json(data):
    value = shared.strict_json(data)
    def finite(item):
        require(type(item) is not float, "Floating/nonfinite values are not part of the GNU evidence contract")
        if type(item) is dict:
            for child in item.values(): finite(child)
        elif type(item) is list:
            for child in item: finite(child)
    finite(value)
    return value
SOURCES = ("tools/executor/exec_server.py", "tools/executor/native_files.py",
    "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
    "tools/executor/native_files_rpc_fixture.py", "tools/executor/native_process_policy.py",
    "tools/executor/native_processes.py", "tools/executor/native_environment.py",
    "tools/executor/native_environment_unicode.py",
    "tools/executor/gnu-runtime/gnu_process_adapter.py",
    "tools/executor/gnu-runtime/gnu_runtime_capacity.py",
    "tools/executor/gnu-runtime/gnu_runtime_address.py",
    "tools/executor/gnu-runtime/test_gnu_process_adapter.py",
    "tools/executor/gnu-runtime/managed_android_fixture.py")
PROGRAMS = {"runner": "libfoldgpt-gnu-managed.so", "files_helper": "libfoldgpt-native-files.so",
    "proot": "libfoldgpt-strict-proot.so", "loader": "libproot-loader.so", "loader32": "libproot-loader32.so"}
SUPPORT_LIBRARIES = ("libtalloc.so", "libandroid-shmem.so", "libfoldgpt_python.so", "libpython3.14.so",
                     "libcrypto_python.so", "libssl_python.so", "libsqlite3_python.so")
EXPECTED = {"project": (0, b"GNU_MANAGED_PROJECT_PASS"), "policy": (0, b"FULL_POLICY_DENIALS_PASS"),
    "temp-denied": (0, b"TEMP_NO_IMPLICIT_GRANT_PASS"), "temp-admitted": (0, b"TEMP_COMPLETE_POLICY_PASS"),
    "stdin": (23, b"\x00\xffABC"), "cancel": (None, b"READY"), "timeout": (None, b"READY")}
UID_FIELDS = {"uidTasksObserved", "uidTaskBudget", "uidNprocLimit", "inheritedNprocSoft", "inheritedNprocHard"}


def fields(value, names, label):
    require(type(value) is dict and set(value) == set(names), label + " fields differ")


def integer(value, lower=0, upper=(1 << 64) - 1):
    return type(value) is int and lower <= value <= upper


def streams(response):
    result = {"stdout": bytearray(), "stderr": bytearray()}
    previous = 0
    require(type(response["chunks"]) is list and len(response["chunks"]) <= 4096, "Unbounded GNU output")
    for chunk in response["chunks"]:
        fields(chunk, ("seq", "stream", "chunk"), "GNU output chunk")
        require(chunk["stream"] in result and type(chunk["seq"]) is int and chunk["seq"] > previous,
                "GNU output ordering differs")
        previous = chunk["seq"]
        data = base64.b64decode(chunk["chunk"], validate=True)
        require(0 < len(data) <= 65536 and base64.b64encode(data).decode() == chunk["chunk"],
                "Noncanonical or oversized GNU output chunk")
        result[chunk["stream"]].extend(data)
    return {name: bytes(data) for name, data in result.items()}


def inspect_fd_admission(value):
    fields(value, ("baseProcessCapacity", "nativeDependencyCount", "capacity", "inheritedSoft", "inheritedHard", "dependencies"),
           "Native loader FD admission")
    require(value["baseProcessCapacity"] == 128 and integer(value["nativeDependencyCount"], 0, 4096)
            and integer(value["capacity"], 128, 4224)
            and value["capacity"] == value["baseProcessCapacity"] + value["nativeDependencyCount"],
            "Native loader FD capacity accounting differs")
    require(all(type(value[name]) is int and (value[name] == -1 or value[name] >= value["capacity"])
                for name in ("inheritedSoft", "inheritedHard")), "Native loader exceeds an inherited FD ceiling")
    dependencies = value["dependencies"]
    require(type(dependencies) is dict and len(dependencies) == value["nativeDependencyCount"],
            "Native loader dependency inventory disagrees with its capacity")
    for name, entry in dependencies.items():
        path = PurePosixPath(name)
        require(path.is_absolute() and str(path) == name and ".." not in path.parts
                and "\\" not in name and "\0" not in name, "Native loader dependency path is not canonical")
        fields(entry, ("needed", "soname", "stat"), "Native loader dependency")
        require(type(entry["needed"]) is list and len(entry["needed"]) <= 4096
                and all(type(item) is str and re.fullmatch(r"[A-Za-z0-9_+@.\-]+", item) for item in entry["needed"])
                and (entry["soname"] is None or type(entry["soname"]) is str
                     and re.fullmatch(r"[A-Za-z0-9_+@.\-]+", entry["soname"]))
                and type(entry["stat"]) is list and len(entry["stat"]) == 4
                and all(integer(item) for item in entry["stat"]), "Native loader ELF observation differs")


def inspect_address_admission(value, fd_admission, declared):
    """Recompute the retained geometry independently, never run a guest."""
    fields(value, ('schema','addressSpaceBytes','pageSize','scudoClasses','scudoRegionBytes',
        'scudoReservationBytes','cfiShadowBytes','nativeLibraryCount','nativeLoadSpanBytes',
        'gapEligibleLibraries','maximumGapUnits','gapAlignmentBytes','maximumRetainedGapBytes',
        'transientAlignmentBytes','workloadHeadroomBytes','inheritedSoft','inheritedHard',
        'nativeLibraries'), 'Native address admission')
    require(value['schema']=='foldgpt.gnu-address-admission.v1', 'Address admission schema differs')
    constants={'pageSize':4096,'scudoClasses':33,'scudoRegionBytes':1<<28,
        'scudoReservationBytes':33<<28,'cfiShadowBytes':1<<31,'maximumGapUnits':31,
        'gapAlignmentBytes':1<<21,'transientAlignmentBytes':2<<21,'workloadHeadroomBytes':1<<28}
    require(all(type(value[key]) is int and value[key]==expected for key,expected in constants.items()),
        'Reviewed runtime address geometry differs')
    entries=value['nativeLibraries']
    require(type(entries) is dict and entries.keys()==fd_admission['dependencies'].keys(),
        'Address and descriptor dependency inventories differ')
    for entry in entries.values():
        fields(entry, ('loadSpanBytes','maxAlignment','gapEligible'), 'Native ELF load span')
        span,alignment=entry['loadSpanBytes'],entry['maxAlignment']
        require(integer(span,4096,1<<34) and span%4096==0 and integer(alignment,4096,1<<21)
            and alignment&(alignment-1)==0 and type(entry['gapEligible']) is bool
            and entry['gapEligible']==(span>1<<18 or alignment==1<<21), 'Native ELF geometry differs')
    spans=sum(entry['loadSpanBytes'] for entry in entries.values())
    eligible=sum(entry['gapEligible'] for entry in entries.values())
    gap=eligible*31*(1<<21)
    total=(33<<28)+(1<<31)+spans+gap+(2<<21)+(1<<28)
    expected={'nativeLibraryCount':len(entries),'nativeLoadSpanBytes':spans,
        'gapEligibleLibraries':eligible,'maximumRetainedGapBytes':gap,'addressSpaceBytes':total}
    require(all(type(value[key]) is int and value[key]==computed for key,computed in expected.items())
        and total==declared and 16777216<=total<=1<<34, 'Address budget component arithmetic differs')
    require(all(type(value[key]) is int and (value[key]==-1 or value[key]>=total)
        for key in ('inheritedSoft','inheritedHard')), 'Address budget exceeds inherited ceiling')


def inspect_matrix(matrix):
    """Validate retained wire data, without executing a command or test program."""
    fields(matrix, ("status", "uid", "workspace", "observations", "notifications", "sources", "runtimeFdAdmission", "scope"), "GNU matrix")
    require(matrix["status"] == "PASS" and integer(matrix["uid"], 1), "Matrix has no successful nonroot identity")
    inspect_fd_admission(matrix["runtimeFdAdmission"])
    require(type(matrix["observations"]) is list and [v["key"] for v in matrix["observations"]] == list(EXPECTED),
            "GNU case coverage changed; review required")
    groups = {key: {"events": [], "chunks": [], "exit": None, "closed": False} for key in EXPECTED}
    require(type(matrix["notifications"]) is list and len(matrix["notifications"]) <= 8192, "Unbounded GNU notifications")
    for event in matrix["notifications"]:
        fields(event, ("method", "params"), "GNU notification")
        method, params = event["method"], event["params"]
        require(method in ("process/output", "process/exited", "process/closed"), "Unknown GNU event")
        names = {"processId", "seq"} | ({"stream", "chunk"} if method == "process/output"
                else {"exitCode", "sandboxDenied"} if method == "process/exited" else set())
        fields(params, names, "GNU event payload")
        require(params["processId"] in groups, "Unexpected GNU process generation")
        group = groups[params["processId"]]
        require(not group["closed"] and integer(params["seq"], 1)
                and params["seq"] == len(group["events"]) + 1, "GNU event order differs")
        group["events"].append(event)
        if method == "process/output":
            group["chunks"].append({name: params[name] for name in ("seq", "stream", "chunk")})
        elif method == "process/exited":
            require(group["exit"] is None and integer(params["exitCode"], 0, 255)
                    and params["sandboxDenied"] is False, "GNU exit notification differs")
            group["exit"] = params["exitCode"]
        else:
            require(group["exit"] is not None, "GNU close preceded exit")
            group["closed"] = True
    completions, outputs = {}, {}
    for item in matrix["observations"]:
        fields(item, ("key", "response", "nativeStarted", "nativeResult", "supervisorIdentity"), "GNU completion")
        key, response, started, result, identity = (item[name] for name in
            ("key", "response", "nativeStarted", "nativeResult", "supervisorIdentity"))
        fields(started, {"type", "pid", "profile"} | UID_FIELDS, "GNU startup")
        require(started["type"] == "started" and started["profile"] == "managed-process-v2"
                and integer(started["pid"], 1) and all(integer(started[name]) for name in UID_FIELDS)
                and started["uidTasksObserved"] > 0 and started["uidTaskBudget"] > 0
                and started["uidNprocLimit"] == min(started["uidTasksObserved"] + started["uidTaskBudget"],
                    started["inheritedNprocSoft"], started["inheritedNprocHard"])
                and started["uidNprocLimit"] > started["uidTasksObserved"], "GNU UID limit accounting differs")
        fields(identity, ("type", "pid", "profile", "closeOnExec", "identityRoute", "waitOwner", "acknowledgedBeforeWorker"), "GNU supervisor")
        require(identity["type"] == "supervisor" and identity["profile"] == "managed-process-v2"
                and integer(identity["pid"], 1) and identity["pid"] != started["pid"]
                and identity["closeOnExec"] is True and identity["acknowledgedBeforeWorker"] is True
                and identity["identityRoute"] == "native-self-pidfd/SCM_RIGHTS" and identity["waitOwner"] == "asyncio",
                "GNU supervisor identity differs")
        fields(result, ("type", "outcome", "exitCode", "signal", "cleanupComplete", "started", "grants", "denials",
                       "stdoutBytes", "stderrBytes", "stage", "errno"), "GNU native result")
        outcome = "cancelled" if key == "cancel" else "timeout" if key == "timeout" else "exited"
        require(result["type"] == "result" and result["outcome"] == outcome and result["cleanupComplete"] is True
                and result["started"] is True and all(integer(result[name]) for name in
                    ("signal", "grants", "denials", "stdoutBytes", "stderrBytes", "stage", "errno"))
                and result["stage"] == result["errno"] == 0, "GNU native outcome differs")
        require((result["signal"] == 0 and integer(result["exitCode"], 0, 255))
                or (integer(result["signal"], 1, 64) and type(result["exitCode"]) is int and result["exitCode"] == -1),
                "GNU native wait status differs")
        code = 128 + result["signal"] if result["signal"] else result["exitCode"]
        expected_code, marker = EXPECTED[key]
        fields(response, ("chunks", "nextSeq", "exited", "exitCode", "closed", "failure", "sandboxDenied"), "GNU process read")
        group = groups[key]
        require(response["closed"] is True and response["exited"] is True and response["sandboxDenied"] is False
                and group["closed"] and response["exitCode"] == group["exit"] == code
                and integer(response["nextSeq"], 1) and response["nextSeq"] == len(group["events"]) + 1
                and response["chunks"] == group["chunks"], "Native wait, retained bytes and notifications disagree")
        require(response["failure"] == ("Native process ended with timeout" if key == "timeout" else None)
                and (expected_code is None or code == expected_code), "GNU exit code or failure differs")
        captured = streams(response)
        require(result["stdoutBytes"] == len(captured["stdout"]) and result["stderrBytes"] == len(captured["stderr"]),
                "GNU native byte counters disagree with actual wire output")
        if key == "stdin":
            require(captured["stdout"] == marker, "Binary stdin round trip differs")
        elif key == "cancel":
            ready = re.findall(rb"^READY ([1-9][0-9]*)$", captured["stdout"], re.M)
            require(len(ready) == len(set(ready)) == 2, "Cancellation did not observe both GNU descendants")
        else:
            require(marker in captured["stdout"].splitlines(), "Expected GNU output line absent: " + key)
        outputs[key] = captured
        completions[key] = {"exitCode": code, "signal": result["signal"], "nativeOutcome": outcome,
            "grants": result["grants"], "denials": result["denials"], "cleanupComplete": True}
    return completions, outputs


def inspect_project(artifacts, directories):
    """Check the collected tree and ZIP bytes; never import or execute them."""
    fixed = {"app/maths.py", "app/__main__.py", "test.py", "dist/result", "dist/app.pyz"}
    bytecode = set(artifacts) - fixed
    require(directories == {"app", "dist", "app/__pycache__", "__pycache__"} and fixed <= set(artifacts)
            and len(bytecode) == 3, "Created project topology differs")
    cache_tags = []
    for name in bytecode:
        match = re.fullmatch(r"(app/__pycache__/(?:maths|__main__)|__pycache__/test)\.(cpython-[0-9]+)\.pyc", name)
        require(match is not None and len(artifacts[name]) > 16 and artifacts[name][2:4] == b"\r\n",
                "Invalid compiled Python artifact")
        cache_tags.append(match[2])
    require(len(set(cache_tags)) == 1 and len({artifacts[name][:4] for name in bytecode}) == 1,
            "Compiled Python artifact versions disagree")
    require(artifacts["dist/result"] == b"42\n" and artifacts["app/maths.py"] == b"def doubled(n): return n * 2\n"
            and artifacts["app/__main__.py"] == b"from maths import doubled\nprint(doubled(21))\n", "Created/modified project bytes differ")
    tests = ast.parse(artifacts["test.py"])
    require(sorted(node.name for node in ast.walk(tests) if isinstance(node, ast.FunctionDef))
            == ["test_negative", "test_positive", "test_zero"], "Actual project test source coverage differs")
    with zipfile.ZipFile(io.BytesIO(artifacts["dist/app.pyz"])) as archive:
        members = archive.infolist()
        require(len(members) <= 8 and len(archive.namelist()) == len(set(archive.namelist()))
                and sum(entry.file_size for entry in members) <= 4*1024*1024, "Invalid ZIP inventory or decompressed bound")
        zipped_files = {item.filename for item in members if not item.is_dir()}
        require(zipped_files == {name.removeprefix("app/") for name in artifacts if name.startswith("app/")},
                "Built ZIP members differ from actual source/bytecode tree")
        for name in zipped_files:
            require(archive.read(name) == artifacts["app/" + name], "Built ZIP member bytes differ: " + name)


class Collector(shared.Collector):
    def collect(self):
        self.save("collector-source.py", Path(__file__).read_bytes())
        self.save("shared-collector-source.py", Path(shared.__file__).read_bytes())
        self.uid = int(self.command("id", "-u").stdout.strip())
        require(self.uid > 0 and re.fullmatch(r"gm-[0-9]{1,20}", self.args.fixture), "Invalid GNU fixture identity")
        requested_fixture = "/data/data/app.foldgpt/cache/" + self.args.fixture
        fixture = self.command("readlink", "-f", requested_fixture).stdout.decode().strip()
        require(fixture in {requested_fixture, f"/data/user/{self.uid // 100000}/app.foldgpt/cache/" + self.args.fixture},
                "Canonical fixture escaped the application cache")
        self.info(fixture, kind="directory")
        apk_before, security_before = self.apk_identity(), self.security()
        apk_data = self.args.apk.read_bytes()
        require(sha(apk_data) == apk_before["sha256"], "Supplied APK is not installed")
        self.save("installed.apk", apk_data)
        native = str(PurePosixPath(apk_before["path"]).parent / "lib/arm64")
        report_bytes = self.read(fixture + "/report.json", "report.json")
        report = strict_json(report_bytes)
        matrix_bytes = self.read(fixture + "/gnu-tests.json", "gnu-tests.json")
        matrix = strict_json(matrix_bytes)
        output = self.read(fixture + "/fixture-output.txt", "fixture-output.txt").decode()
        require(self.read(fixture + "/android-completion.txt", "android-completion.txt")
                == f"PASS uid={self.uid}\n".encode(), "Android service did not complete")
        require(report["schema"] == "foldgpt.gnu-managed-android.v1" and report["status"] == "PASS"
                and report["uid"] == matrix["uid"] == self.uid and matrix["status"] == "PASS"
                and report["matrixSha256"] == sha(matrix_bytes), "GNU report identity differs")
        fields(report, ("schema", "status", "uid", "suiteSha256", "matrixSha256", "observationBefore", "observationAfter",
                        "addressSpaceBytes", "addressAdmission", "programsSha256", "scope"), "Android GNU report")
        require(integer(report["addressSpaceBytes"], 16777216, 17179869184), "Invalid declared address-space allowance")
        inspect_address_admission(report['addressAdmission'], matrix['runtimeFdAdmission'], report['addressSpaceBytes'])
        fields(report["programsSha256"], PROGRAMS, "Executed native programs")
        before_context = strict_json(self.read(fixture + "/android-context-before.json", "android-context-before.json"))
        require(before_context == report["observationBefore"], "Android context contradicts its retained observation")
        for observation in (report["observationBefore"], report["observationAfter"]):
            fields(observation, ("uid", "gid", "status", "securityContext", "machine", "executable", "mappedFiles"), "Android native context")
            status = observation["status"]
            fields(status, ("Uid", "Gid", "TracerPid", "Seccomp", "CapEff", "CapPrm", "NoNewPrivs"), "Android proc status")
            require(observation["uid"] == self.uid and observation["machine"] == "aarch64"
                    and [int(v) for v in status["Uid"].split()] == [self.uid] * 4
                    and integer(observation["gid"], 1) and [int(v) for v in status["Gid"].split()] == [observation["gid"]] * 4
                    and status["TracerPid"] == "0" and status["Seccomp"] == "2"
                    and int(status["CapEff"], 16) == int(status["CapPrm"], 16) == 0
                    and status["NoNewPrivs"] in ("0", "1")
                    and re.fullmatch(r"u:r:untrusted_app(?:_[0-9]+)?:s0(?::[a-z0-9,:]+)?", observation["securityContext"])
                    and observation["executable"] == native + "/libfoldgpt_python.so",
                    "Fixture did not run as the native Android application interpreter")
            require(type(observation["mappedFiles"]) is list and len(observation["mappedFiles"]) <= 512
                    and observation["mappedFiles"] == sorted(set(observation["mappedFiles"]))
                    and not any("libproot" in name or "fake_userns" in name for name in observation["mappedFiles"]),
                    "Native fixture mapped a compatibility shim or invalid inventory")
        require(report["observationBefore"]["status"] == report["observationAfter"]["status"]
                and report["observationBefore"]["securityContext"] == report["observationAfter"]["securityContext"],
                "Native fixture security identity changed")
        completions, outputs = inspect_matrix(matrix)
        sources, libraries = {}, {}
        with zipfile.ZipFile(io.BytesIO(apk_data)) as apk:
            require(len(apk.namelist()) == len(set(apk.namelist())), "Duplicate APK entries")
            require({name.removeprefix("assets/gnu-managed-probe/") for name in apk.namelist()
                     if name.startswith("assets/gnu-managed-probe/") and not name.endswith("/")} == set(SOURCES),
                    "Packaged GNU diagnostic source inventory changed")
            for name in SOURCES:
                actual = self.read(fixture + "/sources/" + name, "sources/" + name)
                require(actual == apk.read("assets/gnu-managed-probe/" + name), "Executed source differs from APK: " + name)
                sources[name] = sha(actual)
            require(matrix["sources"] == {PurePosixPath(name).name: digest for name, digest in sources.items()
                    if name.startswith("tools/executor/gnu-runtime/")},
                    "Suite's executed source inventory differs")
            require(report["suiteSha256"] == sources["tools/executor/gnu-runtime/test_gnu_process_adapter.py"],
                    "Suite hash differs from executed source")
            for key, name in PROGRAMS.items():
                actual = self.read(native + "/" + name, "libraries/" + name, private=False, bound=32*1024*1024)
                require(actual == apk.read("lib/arm64-v8a/" + name) and sha(actual) == report["programsSha256"][key],
                        "Native program differs from executed APK: " + name)
                libraries[name] = sha(actual)
            for name in SUPPORT_LIBRARIES:
                actual = self.read(native + "/" + name, "libraries/" + name, private=False, bound=64*1024*1024)
                require(actual == apk.read("lib/arm64-v8a/" + name), "Native support library differs from APK: " + name)
                libraries[name] = sha(actual)
            mapped_python = {name for context in (report["observationBefore"], report["observationAfter"])
                             for name in context["mappedFiles"] if name.startswith(fixture + "/python/")}
            for name in sorted(mapped_python):
                relative = shared.relative(name.removeprefix(fixture + "/python/"))
                actual = self.read(name, "python-mapped/" + str(relative), bound=32*1024*1024)
                require(actual == apk.read("assets/native-python/" + str(relative)), "Loaded Android Python extension differs from APK")
        build = self.args.build.resolve(strict=True)
        manifest_data = (build / "manifest.json").read_bytes()
        manifest = strict_json(manifest_data)
        self.save("build/manifest.json", manifest_data)
        required_native_sources = {"sources/tools/executor/gnu-runtime/" + name for name in
            ("gnu-managed-runner.c", "gnu-managed-runtime.h", "gnu-managed-filter.h", "gnu-managed-operations.h")}
        require(type(manifest["files"]) is dict and (required_native_sources | {PROGRAMS["runner"]}) <= set(manifest["files"]),
                "Frozen build lacks native source or binary identities")
        for name, digest in manifest["files"].items():
            require(type(digest) is str and re.fullmatch(r"[0-9a-f]{64}", digest), "Invalid build fingerprint")
            data = build.joinpath(*shared.relative(name).parts).read_bytes()
            require(sha(data) == digest, "Frozen GNU build input changed: " + name)
            if name.startswith("sources/"):
                self.save("build/" + name, data)
                source_name = name.removeprefix("sources/")
                if source_name in sources:
                    require(digest == sources[source_name], "Packaged Python differs from frozen GNU build")
        built = build / PROGRAMS["runner"]
        stripped = self.out / "reproduced-stripped-runner.so"
        proc = subprocess.run([str(self.args.llvm_strip), "--strip-unneeded", "-o", str(stripped), str(built)],
                              capture_output=True, timeout=30)
        require(proc.returncode == 0 and sha(stripped.read_bytes()) == libraries[PROGRAMS["runner"]],
                "Native runner does not match exact NDK strip of frozen build")
        stripping = {"sourceSha256": manifest["files"][PROGRAMS["runner"]], "strippedSha256": sha(stripped.read_bytes()),
                     "toolSha256": sha(self.args.llvm_strip.read_bytes()), "arguments": ["--strip-unneeded"]}
        native_build = self.args.native_build.resolve(strict=True)
        native_manifest_data = (native_build / "manifest.json").read_bytes()
        native_manifest = strict_json(native_manifest_data)
        self.save("native-build/manifest.json", native_manifest_data)
        for name, digest in native_manifest["recipe_and_notices"].items():
            data = native_build.joinpath(*shared.relative(name).parts).read_bytes()
            require(sha(data) == digest, "Frozen PRoot recipe changed: " + name)
            self.save("native-build/" + name, data)
        strict_patch = "build/recipe/proot-strict-sandbox.patch"
        require(strict_patch in native_manifest["recipe_and_notices"]
                and b"restrict_guest_tracer_scope" in (native_build / strict_patch).read_bytes(),
                "PRoot candidate lacks the native child-domain protection source")
        for name in ("libfoldgpt-strict-proot.so", "libproot-loader.so", "libproot-loader32.so", "libtalloc.so", "libandroid-shmem.so"):
            built_name = "libproot.so" if name == "libfoldgpt-strict-proot.so" else name
            built_data = (native_build / "runtime/arm64-v8a" / built_name).read_bytes()
            require(sha(built_data) == native_manifest["artifacts"][built_name]["sha256"] == libraries[name],
                    "Installed strict runtime differs from its frozen native build: " + name)
        require(b"strict guest Landlock tracer scope" in (self.raw / "libraries/libfoldgpt-strict-proot.so").read_bytes(),
                "Installed PRoot does not contain the child-domain bootstrap diagnostic")
        workspace = PurePosixPath(matrix["workspace"])
        require(str(workspace.parent.parent) == fixture + "/cases" and workspace.name == "workspace"
                and re.fullmatch(r"gnu-rpc-[a-z0-9_]+", workspace.parent.name), "Project escaped fixed fixture")
        case = str(workspace.parent)
        observed = matrix["observations"]
        fd_admission = matrix["runtimeFdAdmission"]
        require(fd_admission["nativeDependencyCount"] > 0
                and {native + "/libtalloc.so", native + "/" + PROGRAMS["proot"]} <= set(fd_admission["dependencies"]),
                "Android loader dependency closure lacks its actual PRoot and talloc")
        profile = str(workspace) + "/.home/.bash_profile"
        require(self.read(profile, "login/.bash_profile")
                == b'export FOLDGPT_LOGIN_PROFILE="actual workspace bash profile"\n'
                and self.records[profile]["mode"] == 0o600, "Actual login-shell profile differs")
        for item in observed:
            key = item["key"]
            for stream, data in outputs[key].items():
                require(self.read(case + "/" + key + "." + stream, "output/" + key + "." + stream) == data,
                        "Retained process output contradicts response")
        require(re.search(rb"(?:^|\n)\.\.\.\n-{70}\nRan 3 tests in [0-9.]+s\n\nOK\n", outputs["project"]["stderr"])
                and b"Permission denied" not in outputs["project"]["stderr"]
                and b"Operation not supported" not in outputs["project"]["stderr"]
                and "Traceback (most recent call last)" not in output
                and not any(b"Traceback (most recent call last)" in item["stderr"] for item in outputs.values()),
                "Python project tests did not pass")
        for root in (str(workspace), case + "/guest-tmp"):
            self.info(root, kind="directory")
            for name in (".git/config", "readonly/value"):
                require(self.read(root + "/" + name, "protected/" + PurePosixPath(root).name + "/" + name)
                        == b"protected\n", "Protected bytes changed")
                require(self.records[root + "/" + name]["mode"] == 0o600, "Protected mode changed")
        forbidden = ("workspace/stolen", "workspace/config", "workspace/readonly/newdir", "workspace/project/obsolete",
                     "workspace/project/dist/temporary", "guest-tmp/new-file", "guest-tmp/new-dir", "guest-tmp/readonly/new",
                     "guest-tmp/stolen", "guest-tmp/stolen-git", "scratch/intrusion", "scratch/intrusion-dir")
        for name in forbidden:
            require(self.command("find", case, "-path", case + "/" + name, "-print0").stdout == b"",
                    "A denied or supposedly removed artifact exists: " + name)
        temporary_inventory = self.command("find", case + "/guest-tmp", "-mindepth", "1", "-print0").stdout.split(b"\0")
        require(temporary_inventory[-1] == b"" and {value.decode().removeprefix(case + "/guest-tmp/")
                for value in temporary_inventory[:-1]} == {".git", ".git/config", "readonly", "readonly/value"},
                "Allowed temporary lifecycle left extra objects")
        project = str(workspace) + "/project"
        inventory_bytes = self.command("find", project, "-print0").stdout
        names = inventory_bytes.split(b"\0")
        require(names[-1] == b"" and len(names) <= 32 and len(names[:-1]) == len(set(names[:-1])),
                "Malformed or duplicate native project inventory")
        artifacts = {}
        directories = set()
        for raw in names:
            if not raw:
                continue
            if raw.decode() == project:
                self.info(project, kind="directory")
                continue
            name = raw.decode().removeprefix(project + "/")
            shared.relative(name)
            require(raw.decode() == project + "/" + name and len(artifacts) < 32, "Invalid project inventory")
            if name in ("app", "dist", "app/__pycache__", "__pycache__"):
                self.info(project + "/" + name, kind="directory")
                directories.add(name)
            else:
                artifacts[name] = self.read(project + "/" + name, "project/" + name)
        inspect_project(artifacts, directories)
        snapshot = self.processes(fixture, native)
        # Include this runner explicitly; shared fixed collector recognizes strict PRoot.
        for pid in (item["supervisorIdentity"]["pid"] for item in observed):
            require(self.command("readlink", f"/proc/{pid}/exe", check=False).stdout.strip()
                    != (native + "/" + PROGRAMS["runner"]).encode(), "GNU supervisor still runs")
        # Every historical claim is checked against a stable retained snapshot.
        for target, before in list(self.records.items()):
            require(self.info(target, private=not target.startswith("/data/app/"))
                    == {name: value for name, value in before.items() if name != "sha256"}
                    and self.native_hash(target) == before["sha256"], "Collected file changed: " + target)
        require(self.command("find", project, "-print0").stdout == inventory_bytes, "Project inventory changed during collection")
        require(self.apk_identity() == apk_before and self.security() == security_before,
                "Package or integrity state changed during collection")
        result = {"schema": "foldgpt.gnu-managed-independent-collection.v1", "status": "PASS",
            "collectedAtUtc": datetime.now(timezone.utc).isoformat(), "fixture": fixture, "uid": self.uid,
            "apk": apk_before, "security": security_before, "sources": sources, "libraries": libraries,
            "nativeObservationBefore": report["observationBefore"], "nativeObservationAfter": report["observationAfter"],
            "gnuBuildManifestSha256": sha(manifest_data), "strictBuildManifestSha256": sha(native_manifest_data),
            "runtimeFdAdmission": fd_admission,
            "reproducedStripping": stripping,
            "completions": completions, "projectArtifacts": {name: sha(data) for name, data in artifacts.items()},
            "processSnapshot": snapshot, "fileObservations": self.records,
            "scope": "Real GNU backend calls and project artifacts; not ordinary phone/model execution",
            "limitations": ["Historical syscall denials and reaping are native observations, not replayed.",
                "Post-run PID observations cannot reconstruct every historical descendant or exclude all PID reuse.",
                "The packaged Java service is identified by APK bytes, without a reproducible source-to-DEX proof.",
                "Runtime library and mapped-extension bytes match the APK; not a full Python installation or publisher-authenticity audit.",
                "Child-domain PRoot source/binary provenance is checked; this suite has no controlled Android tracer-memory adversary yet.",
                "This collection does not qualify broader permission policies, TTY, managed networking or warranty terms."]}
        (self.out / "verification.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("serial", "fixture"):
        parser.add_argument("--" + name, required=True)
    for name in ("apk", "build", "native-build", "llvm-strip"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--adb", default="adb")
    collector = Collector(parser.parse_args())
    try:
        result = collector.collect()
        print(json.dumps({"status": result["status"], "output": str(collector.out)}))
    except BaseException as error:
        (collector.out / "failure.json").write_text(json.dumps({"status": "FAIL", "errorType": type(error).__name__,
            "message": str(error), "scope": "Read-only collection failed; no Android test was rerun"}, indent=2) + "\n", encoding="utf-8")
        raise
    finally:
        (collector.out / "commands.json").write_text(json.dumps(collector.commands, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
