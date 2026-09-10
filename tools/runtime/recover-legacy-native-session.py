"""One-time v1 maintenance after independently proving the whole app UID stopped.

Preserves the old marker and its bytes. This is not automatic crash recovery,
and PID disappearance alone never authorizes it. Only FoldGPT is stopped.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "app.foldgpt"
DATA = "/data/user/0/app.foldgpt"

# Executed by the installed, verified Bionic interpreter after an external
# complete UID process census. The lock additionally excludes any native owner.
RECOVER = r'''
import base64,fcntl,hashlib,json,os,stat,sys
from pathlib import Path
expected,uid,boot,nonce=sys.argv[1:]
uid=int(uid)
if os.getresuid()!=(uid,uid,uid) or os.getresgid()!=(uid,uid,uid) or uid<10000:
    raise PermissionError('Maintenance identity differs')
if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=boot:
    raise RuntimeError('Boot changed before recovery')
directory=Path('/data/user/0/app.foldgpt/app_foldgpt_exec')
if directory.resolve(strict=True)!=directory:
    raise ValueError('Legacy maintenance must use its observed canonical run-as view')
fd=os.open(directory,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC)
info=os.fstat(fd)
if info.st_uid!=uid or stat.S_IMODE(info.st_mode)&0o077:
    raise PermissionError('Endpoint directory is not private')
lock=os.open('broker.lock',os.O_RDWR|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
li=os.fstat(lock)
if not stat.S_ISREG(li.st_mode) or li.st_uid!=uid or li.st_nlink!=1 or li.st_mode&0o077:
    raise PermissionError('Invalid existing ownership lock')
fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
marker=os.open('process-session.json',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
mi=os.fstat(marker)
if not stat.S_ISREG(mi.st_mode) or mi.st_uid!=uid or mi.st_nlink!=1 or mi.st_mode&0o077 or mi.st_size>4096:
    raise PermissionError('Invalid legacy marker')
data=os.read(marker,4097)
if len(data)!=mi.st_size or hashlib.sha256(data).hexdigest()!=expected:
    raise ValueError('Legacy marker changed since quiescence evidence')
value=json.loads(data)
allowed_v1={'version','brokerPid','uid','workspaceDevice','workspaceInode'}
allowed_v2={'version','brokerPid','uid','workspaceDevice','workspaceInode','bootEpoch'}
if value.get('version')==1 and set(value)==allowed_v1 and value['uid']==uid:
    archive_prefix='recovered-v1-'
elif value.get('version')==2 and set(value)==allowed_v2 and value['uid']==uid:
    epoch=value.get('bootEpoch')
    if not isinstance(epoch, dict) or epoch.get('schema')!='foldgpt.android-boot-epoch.v1' or epoch.get('source')!='android.provider.Settings.Global.BOOT_COUNT' or type(epoch.get('bootCount')) is not int:
        raise ValueError('Invalid legacy v2 bootEpoch')
    archive_prefix='recovered-v2-'
else:
    raise ValueError('This maintenance is only for an observed legacy v1 or v2 marker')
workspace=os.stat('/data/user/0/app.foldgpt/files/projects',follow_symlinks=False)
if (workspace.st_dev,workspace.st_ino)!=(value['workspaceDevice'],value['workspaceInode']):
    raise ValueError('Legacy workspace identity differs')
# The app context cannot inspect unrelated proc directories. Retain the lock
# while the external shell performs its complete UID census, with this helper
# as a positive control. An EOF or mismatched challenge changes no marker.
print(json.dumps({'phase':'locked','helperPid':os.getpid(),'uid':uid,'nonce':nonce}),flush=True)
if sys.stdin.readline().strip()!=nonce:
    raise RuntimeError('Independent locked UID census was not confirmed')
if Path('/proc/sys/kernel/random/boot_id').read_text().strip()!=boot:
    raise RuntimeError('Boot changed before archival')
archive=archive_prefix+nonce
os.mkdir(archive,0o700,dir_fd=fd)
archive_fd=os.open(archive,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=fd)
named=os.stat('process-session.json',dir_fd=fd,follow_symlinks=False)
if (named.st_dev,named.st_ino,named.st_size,named.st_mtime_ns,named.st_ctime_ns)!=(mi.st_dev,mi.st_ino,mi.st_size,mi.st_mtime_ns,mi.st_ctime_ns):
    raise RuntimeError('Legacy marker identity changed before archival')
os.rename('process-session.json','process-session.json',src_dir_fd=fd,dst_dir_fd=archive_fd)
moved=os.stat('process-session.json',dir_fd=archive_fd,follow_symlinks=False)
if (moved.st_dev,moved.st_ino)!=(mi.st_dev,mi.st_ino):
    raise RuntimeError('Archived marker identity differs')
os.fsync(archive_fd);os.fsync(fd)
os.close(archive_fd);os.close(marker);os.close(lock);os.close(fd)
print(json.dumps({'archived':str(directory/archive/'process-session.json'),'sha256':expected,'markerDevice':mi.st_dev,'markerInode':mi.st_ino,'uid':uid,'helperPid':os.getpid(),'previousCleanupClaimed':False}))
'''


def app_processes(text, uid):
    lines = text.splitlines()
    if not lines or lines[0].split() != ["PID", "UID", "NAME"]:
        raise ValueError("Unexpected complete process census format")
    rows = [line.split(maxsplit=2) for line in lines[1:] if line.strip()]
    if not rows or any(len(row) != 3 or not row[0].isdigit() or not row[1].isdigit() for row in rows):
        raise ValueError("Incomplete or nonnumeric process census")
    if not any(int(row[0]) == 1 for row in rows):
        raise ValueError("System process census lacks its init positive control")
    return [row for row in rows if int(row[1]) == uid]


def validate_legacy_observation(state, marker, owned, uid, allow_stale_stopping=False):
    """Admit maintenance only; whole-UID quiescence and flock are still required."""
    version = marker.get("version")
    if version not in (1, 2) or marker.get("uid") != uid:
        raise ValueError("This recovery requires an observed legacy v1 or v2 marker for this UID")
    if version == 2:
        epoch = marker.get("bootEpoch")
        if not isinstance(epoch, dict) or epoch.get("schema") != "foldgpt.android-boot-epoch.v1" or epoch.get("source") != "android.provider.Settings.Global.BOOT_COUNT" or type(epoch.get("bootCount")) is not int:
            raise ValueError("This recovery requires a valid bootEpoch for v2 marker")
    if state.get("state") == "unavailable":
        return
    if not allow_stale_stopping or state.get("state") != "stopping":
        raise ValueError("This recovery requires unavailable or explicitly qualified stale stopping")
    native = state.get("lastNativeSessionStatus") or {}
    pid = marker.get("brokerPid")
    if (state.get("schema") != "foldgpt.native.owner.v1"
            or state.get("launchOrigin") != "android-app"
            or native.get("launchOrigin") != "android-app"
            or native.get("directNative") is not True
            or type(pid) is not int or pid <= 0
            or native.get("bootstrapPid") != pid
            or native.get("cleanupComplete") is not False
            or native.get("ownerRetained") is not True
            or any(row[2] != PACKAGE for row in owned)):
        raise ValueError("Stopping owner is not the observed dead application-origin session")
    # Only the main activity may remain. A missing PID is not cleanup proof:
    # main() subsequently force-stops Android's entire app UID, independently
    # observes it empty, and rechecks while the helper holds the native lock.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default="<device-serial>", help="ADB transport for the FoldGPT phone")
    parser.add_argument("--installed-apk-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--previous-observation", type=Path)
    parser.add_argument("--allow-stale-stopping", action="store_true",
                        help="Qualify a dead v1 app-origin owner; retain full UID quiescence proof")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{64}", args.installed_apk_sha256):
        raise ValueError("Installed APK hash is required")
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    (output / "recovery-helper.py").write_text(RECOVER)
    adb = [str(Path(os.environ["LOCALAPPDATA"]) / "Android/Sdk/platform-tools/adb.exe"), "-s", args.serial]
    records = []
    def call(argv, *, required=True):
        result = subprocess.run(adb + ["shell", "-T", shlex.join(argv)], capture_output=True, timeout=30)
        row = {"argv": argv, "returncode": result.returncode, "stdout": result.stdout.decode("utf-8", "replace"),
               "stderr": result.stderr.decode("utf-8", "replace")}
        records.append(row)
        (output / "commands.json").write_text(json.dumps(records, indent=2) + "\n")
        if required: result.check_returncode()
        return row["stdout"].strip()
    boot = call(["cat", "/proc/sys/kernel/random/boot_id"])
    apk = call(["pm", "path", PACKAGE]).removeprefix("package:")
    if not apk.startswith("/data/app/") or "\n" in apk or not apk.endswith("/base.apk"):
        raise ValueError("Installed APK location differs")
    if call(["sha256sum", apk]).split()[0] != args.installed_apk_sha256:
        raise ValueError("Installed APK changed")
    uid = int(call(["run-as", PACKAGE, "id", "-u"]))
    before = call(["ps", "-A", "-o", "PID,UID,NAME"])
    owned = app_processes(before, uid)
    if not any(row[2] in (PACKAGE, PACKAGE + ":runtime") for row in owned):
        if args.previous_observation is None:
            raise ValueError("The app must be observable as a positive control before maintenance")
        prior = args.previous_observation.resolve(strict=True)
        prior.relative_to(ROOT)
        prior_calls = json.loads((prior / "commands.json").read_bytes())
        observed = [row for row in prior_calls if row["argv"] == ["ps", "-A", "-o", "PID,UID,NAME"]]
        old_boot = [row for row in prior_calls if row["argv"] == ["cat", "/proc/sys/kernel/random/boot_id"]]
        if (not observed or not old_boot or old_boot[0]["stdout"].strip() != boot
                or not any(row[2] in (PACKAGE, PACKAGE + ":runtime") for row in app_processes(observed[0]["stdout"], uid))):
            raise ValueError("Prior positive control does not match this device boot and UID")
        (output / "prior-observation.json").write_text(json.dumps({"path": str(prior),
            "commandsSha256": hashlib.sha256((prior / "commands.json").read_bytes()).hexdigest()}))
    (output / "uid-before.json").write_text(json.dumps(owned, indent=2) + "\n")
    marker = base64.b64decode(call(["run-as", PACKAGE, "base64", "app_foldgpt_exec/process-session.json"]))
    (output / "process-session-before.json").write_bytes(marker)
    state = base64.b64decode(call(["run-as", PACKAGE, "base64", "files/native-executor-status.json"]))
    (output / "owner-status-before.json").write_bytes(state)
    observed_state = json.loads(state)
    validate_legacy_observation(observed_state, json.loads(marker), owned, uid, args.allow_stale_stopping)
    if owned and observed_state.get("state") == "unavailable":
        call(["am", "start", "-W", "-n", PACKAGE + "/.NativePreparationActivity", "-a", "app.foldgpt.action.STOP_NATIVE_EXECUTOR"])
    # The old disconnected Binder cannot supply a successful wait receipt.
    # Stop the entire application with Android, then prove whole-UID quiescence.
    call(["am", "force-stop", PACKAGE])
    for i in range(2):
        census = call(["ps", "-A", "-o", "PID,UID,NAME"])
        if app_processes(census, uid):
            raise RuntimeError("FoldGPT UID still owns processes; preserve marker and stop recovery")
        (output / ("uid-quiescent-" + str(i) + ".json")).write_text(json.dumps({"uid": uid, "processes": [], "fullCensusSha256": hashlib.sha256(census.encode()).hexdigest()}))
        if i == 0: time.sleep(1)
    if call(["cat", "/proc/sys/kernel/random/boot_id"]) != boot:
        raise RuntimeError("Boot changed during quiescence evidence")
    executable = apk.rsplit("/", 1)[0] + "/lib/arm64/libfoldgpt_python_cli.so"
    nonce = os.urandom(16).hex()
    helper_argv = ["run-as", PACKAGE, executable, "-I", "-S", "-B", "-u", "-c", RECOVER,
                   hashlib.sha256(marker).hexdigest(), str(uid), boot, nonce]
    # Readiness comes before the census, and the census before the single
    # archival command. Never prefeed the permission token to the helper.
    with (output / "helper.stderr").open("wb") as errors:
        helper = subprocess.Popen(adb + ["shell", "-T", shlex.join(helper_argv)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors)
        try:
            import concurrent.futures
            reader = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            ready_line = reader.submit(helper.stdout.readline).result(timeout=30)
            ready = json.loads(ready_line)
            if ready != {"phase": "locked", "helperPid": ready.get("helperPid"), "uid": uid, "nonce": nonce}:
                raise ValueError("Maintenance helper readiness differs")
            census = call(["ps", "-A", "-o", "PID,UID,NAME"])
            owned = app_processes(census, uid)
            if len(owned) != 1 or int(owned[0][0]) != ready["helperPid"]:
                raise RuntimeError("Whole-UID locked census contains another process; recovery refused")
            (output / "locked-census.json").write_text(json.dumps({"ready": ready, "uidProcesses": owned,
                "censusSha256": hashlib.sha256(census.encode()).hexdigest()}, indent=2) + "\n")
            helper.stdin.write((nonce + "\n").encode()); helper.stdin.flush(); helper.stdin.close()
            final_line = reader.submit(helper.stdout.readline).result(timeout=30)
            code = helper.wait(timeout=30)
            (output / "helper.stdout").write_bytes(ready_line + final_line)
            if code != 0:
                raise RuntimeError("Maintenance helper failed; preserve its exact stderr and prior marker")
            receipt = json.loads(final_line)
        finally:
            if helper.poll() is None:
                helper.stdin.close()
                helper.wait(timeout=30)
            reader.shutdown(wait=True)
    archived = base64.b64decode(call(["run-as", PACKAGE, "base64", receipt["archived"]]))
    if archived != marker:
        raise RuntimeError("Independent archived marker bytes differ")
    (output / "process-session-archived.json").write_bytes(archived)
    if app_processes(call(["ps", "-A", "-o", "PID,UID,NAME"]), uid):
        raise RuntimeError("Maintenance helper did not exit")
    report = {"recovered": True, "basis": "Android force-stop and complete app-UID quiescence plus exclusive native lock",
              "boot": boot, "previousCleanupClaimed": False, "receipt": receipt}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
