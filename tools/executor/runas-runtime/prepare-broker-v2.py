"""Prepare a fresh qualification after V1's worker checked the old shell UID.

Preserve V1 and all enforcement requirements; compile the expected identity
from the actual installed target record. Never execute Android code here.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parents[3]
service = root / "tools/executor/shizuku-service"
release = root / "downloads/runas-qualification/broker-v1-r2"
destination = service / "runasbrokerqualificationv2"
source = release / "sources/runasbrokerqualification"
record_path = root / "downloads/runas-broker-v1/device-reports/collect_info.json"
record = json.loads(record_path.read_text())
target = record["target"]
assert target["packageName"] == "app.foldgpt" and target["uid"] >= 10000
assert target["signerSha256"] == "30930ffce7c10b673e95e69f2d78bb9e60aa71132db3c21cdc15cf56df77fa16"
destination.mkdir(exist_ok=False)
for path in source.rglob("*"):
    if not path.is_file():
        continue
    data = path.read_text(encoding="utf-8")
    for before, after in ((".v1", ".v2"), ("broker-v1", "broker-v2"), ("native-v1", "native-v2"),
                          ("BROKER_V1", "BROKER_V2"), ("broker_v1", "broker_v2"),
                          ("attempt-started-v1", "attempt-started-v2"), ("version(1)", "version(2)"),
                          ("versionCode 1", "versionCode 2"), ("broker V1", "broker V2")):
        data = data.replace(before, after)
    output = destination / path.relative_to(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(data, encoding="utf-8", newline="\n")
frozen = root / "downloads/bionic-supervisor/foldgpt-bionic-supervisor-qKM94iHA"
worker_source = frozen / "package/tools/executor/bionic-supervisor/qualification-worker.c"
worker = worker_source.read_text()
assert worker == (root / "tools/executor/bionic-supervisor/qualification-worker.c").read_text()
guard = "#ifdef __ANDROID__\n#define QUALIFICATION_UID 2000\n#else\n#define QUALIFICATION_UID 65534\n#endif"
assert worker.count(guard) == 1
worker = worker.replace(guard, '#include "target-identity.h"')
combined = '''       greal!=QUALIFICATION_UID||greal!=geffective||greal!=gsaved||
       prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)!=1||prctl(PR_GET_SECCOMP,0,0,0,0)!=2)
        return fail("required-enforcement",EPERM);'''
assert worker.count(combined) == 1
worker = worker.replace(combined, '''       greal!=QUALIFICATION_UID||greal!=geffective||greal!=gsaved)
        return fail("required-identity",EPERM);
    if(prctl(PR_GET_NO_NEW_PRIVS,0,0,0,0)!=1) return fail("required-no-new-privileges",EPERM);
    if(prctl(PR_GET_SECCOMP,0,0,0,0)!=2) return fail("required-seccomp",EPERM);''')
build = root / "downloads/runas-worker-v2-20260908"
build.mkdir(exist_ok=False)
(build / "qualification-worker.c").write_text(worker, encoding="utf-8", newline="\n")
(build / "target-identity.h").write_text(
    "/* Actual PackageManager target, checked again before the fixed launch. */\n"
    f"#define QUALIFICATION_UID {target['uid']}\n", encoding="ascii")
ndk = Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/ndk/29.0.14206865"
compiler = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
command = [str(compiler), "--target=aarch64-linux-android35", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
           "-pthread", "-fPIE", "-pie", "-Wl,-z,max-page-size=16384,-z,common-page-size=16384,-z,relro,-z,now",
           str(build / "qualification-worker.c"), "-o", str(build / "libfoldgpt_qualification_worker.so")]
result = subprocess.run(command, capture_output=True, timeout=120)
(build / "compiler.stdout").write_bytes(result.stdout)
(build / "compiler.stderr").write_bytes(result.stderr)
result.check_returncode()
sha = hashlib.sha256((build / "libfoldgpt_qualification_worker.so").read_bytes()).hexdigest()
(build / "build.json").write_text(json.dumps({"target": target, "sourceRecord": str(record_path.relative_to(root)),
    "sourceRecordSha256": hashlib.sha256(record_path.read_bytes()).hexdigest(),
    "frozenWorkerSourceSha256": hashlib.sha256(worker_source.read_bytes()).hexdigest(),
    "workerSha256": sha, "command": command, "androidExecuted": False}, indent=2) + "\n")
stage = destination / "stage.py"
data = stage.read_text()
anchor = "    sources = {}"
assert data.count(anchor) == 1
data = data.replace(anchor, f'''    worker_build = REPO / 'downloads/runas-worker-v2-20260908'
    native['libfoldgpt_qualification_worker.so'] = pinned(worker_build / 'libfoldgpt_qualification_worker.so', '{sha}')
    target_identity = json.loads((worker_build / 'build.json').read_text())['target']
    sources = {{}}''')
anchor = "'runtimeFiles': len(runtime['dataFiles']),"
assert data.count(anchor) == 1
data = data.replace(anchor, "'qualificationUid': target_identity['uid'], 'targetApkSha256': target_identity['apkSha256'], " + anchor)
stage.write_text(data, newline="\n")
installation = destination / "src/main/java/app/foldgpt/shizukuexec/RunAsBrokerInstallation.java"
data = installation.read_text()
anchor = '        JSONObject expected = config.getJSONObject("nativeLibraries");'
assert data.count(anchor) == 1
data = data.replace(anchor, '''        if (target.getInt("uid") != config.getInt("qualificationUid")
                || !target.getString("apkSha256").equals(config.getString("targetApkSha256"))) {
            throw new SecurityException("Target identity differs from the compiled qualification identity");
        }
''' + anchor)
installation.write_text(data, newline="\n")
verifier = destination / "verify.py"
data = verifier.read_text().replace("1f7054085ecfd920626cdf24603687cd5e9812b445cf171a2f4cff8efbecd3aa", sha)
verifier.write_text(data, newline="\n")
settings = service / "settings.gradle"
settings.write_text(settings.read_text() + "include ':runasbrokerqualificationv2'\n", newline="\n")
ignore = service / ".gitignore"
ignore.write_text(ignore.read_text() + "runasbrokerqualificationv2/.cxx/\n", newline="\n")
print(json.dumps({"module": str(destination), "worker": str(build), "workerSha256": sha, "uid": target["uid"]}))
