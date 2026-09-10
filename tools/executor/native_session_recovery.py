"""Read-only same-boot admission after an ordinary Android session disappeared.

The exclusive broker flock remains held by the caller. No PID is signalled with
a nonzero signal, no old workspace is cleaned, and no old cleanup is certified.
The two Java processes are admitted by OS-supplied PID/start-time identities;
all other processes of the application UID prevent recovery.
"""
import errno
import os

APPLICATION_PROCESSES_SCHEMA = "foldgpt.android-process-population.v1"
APPLICATION_PROCESSES_SOURCE = "android.app.ActivityManager.getRunningAppProcesses"
# Linux include/linux/threads.h: PID_MAX_LIMIT on a 64-bit kernel. Android can
# deny /proc/sys/kernel/pid_max; the compile-time kernel ceiling is still exact
# coverage (the sysctl cannot exceed it). It is not a guessed device PID limit.
LINUX_PID_MAX_LIMIT = 4 * 1024 * 1024


def application_processes(value):
    """Validate the complete OS-selected Java process inventory, without defaults."""
    if (type(value) is not dict or set(value) != {"schema", "source", "processes"}
            or value["schema"] != APPLICATION_PROCESSES_SCHEMA
            or value["source"] != APPLICATION_PROCESSES_SOURCE
            or type(value["processes"]) is not list or not 1 <= len(value["processes"]) <= 2):
        raise ValueError("Android process inventory must identify its exact OS source")
    result, pids, names = [], set(), set()
    for entry in value["processes"]:
        if (type(entry) is not dict or set(entry) != {"pid", "startTimeTicks", "processName"}
                or type(entry["pid"]) is not int or not 0 < entry["pid"] < LINUX_PID_MAX_LIMIT
                or type(entry["startTimeTicks"]) is not int or entry["startTimeTicks"] <= 0
                or entry["processName"] not in ("app.foldgpt", "app.foldgpt:runtime")
                or entry["pid"] in pids or entry["processName"] in names):
            raise ValueError("Android process inventory contains an invalid or duplicate identity")
        pids.add(entry["pid"])
        names.add(entry["processName"])
        result.append(dict(entry))
    if "app.foldgpt:runtime" not in names:
        raise ValueError("Android process inventory lacks its runtime owner")
    return {"schema": APPLICATION_PROCESSES_SCHEMA, "source": APPLICATION_PROCESSES_SOURCE,
            "processes": result}


def _read(path, maximum):
    with open(path, "rb") as stream:
        value = stream.read(maximum + 1)
    if len(value) > maximum:
        raise ValueError("Kernel process identity exceeds its bound")
    return value


def _task_identity(pid, *, tgid=None):
    """Read PID identity twice around status; reused PIDs cannot match start time."""
    def read_stat():
        location = f"/proc/{pid}" if tgid is None else f"/proc/{tgid}/task/{pid}"
        data = _read(location + "/stat", 4096)
        prefix, separator, tail = data.rpartition(b") ")
        fields = tail.split()
        if (not separator or prefix.split(b" (", 1)[0] != str(pid).encode()
                or len(fields) < 20 or not fields[1].isdigit() or not fields[19].isdigit()):
            raise ValueError("Kernel process stat differs from its identity contract")
        return (pid, int(fields[19]), int(fields[1]))

    before = read_stat()
    values = {}
    location = f"/proc/{pid}" if tgid is None else f"/proc/{tgid}/task/{pid}"
    for line in _read(location + "/status", 65536).splitlines():
        name, separator, raw = line.partition(b":")
        if separator and name in (b"Pid", b"Tgid", b"PPid", b"Uid"):
            if name in values:
                raise ValueError("Duplicate kernel process identity field")
            values[name] = raw.split()
    if (set(values) != {b"Pid", b"Tgid", b"PPid", b"Uid"}
            or values[b"Pid"] != [str(pid).encode()] or values[b"Tgid"] != [str(pid if tgid is None else tgid).encode()]
            or values[b"PPid"] != [str(before[2]).encode()] or len(values[b"Uid"]) != 4
            or any(not part.isdigit() for part in values[b"Uid"])):
        raise ValueError("Kernel process status differs from its identity contract")
    uids = tuple(int(part) for part in values[b"Uid"])
    if read_stat() != before:
        raise RuntimeError("Kernel process identity changed during admission")
    return {"pid": pid, "startTimeTicks": before[1], "parentPid": before[2], "uids": uids}


def process_identity(pid):
    """A process leader, distinguished from any of its nonleader task IDs."""
    return _task_identity(pid)


def _allowed_thread(tid, expected):
    """Accept only kernel task membership of an independently pinned process.

    kill(tid, 0) also succeeds for nonleader threads, including new Java threads
    created during a scan. Names and UID alone cannot grant this exemption.
    """
    try:
        values = [line.split()[1:] for line in _read(f"/proc/{tid}/status", 65536).splitlines()
                  if line.startswith(b"Tgid:")]
        if len(values) != 1 or len(values[0]) != 1 or not values[0][0].isdigit():
            raise ValueError("Kernel thread lacks its exact thread-group identity")
        tgid = int(values[0][0])
        if tgid == tid or tgid not in expected:
            return False
        before = process_identity(tgid)
        if before != expected[tgid]:
            raise RuntimeError("Allowed thread group identity changed during recovery")
        task = _task_identity(tid, tgid=tgid)
        if task["uids"] != (os.getuid(),) * 4 or process_identity(tgid) != before:
            raise RuntimeError("Allowed thread membership changed during recovery")
        return True
    except (FileNotFoundError, ProcessLookupError, PermissionError):
        # A hidden live supervisor is refused. A task that exited during these
        # reads no longer needs an exemption; confirm this with the same syscall.
        return not _signal_zero(tid)


def verify_application_processes(value, parent_pid):
    value = application_processes(value)
    if type(parent_pid) is not int or parent_pid != os.getppid() or parent_pid <= 0:
        raise ValueError("Android runtime parent differs from the native kernel parent")
    identities = []
    for entry in value["processes"]:
        observed = process_identity(entry["pid"])
        command = _read(f"/proc/{entry['pid']}/cmdline", 4096).split(b"\0", 1)[0]
        if (observed["uids"] != (os.getuid(),) * 4
                or observed["startTimeTicks"] != entry["startTimeTicks"]
                or command != entry["processName"].encode("ascii")
                or (entry["processName"] == "app.foldgpt:runtime" and entry["pid"] != parent_pid)):
            raise PermissionError("Android process identity no longer matches its OS observation")
        if process_identity(entry["pid"]) != observed:
            raise RuntimeError("Android process identity changed during command validation")
        identities.append(observed)
    return identities


def _signal_zero(pid):
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as error:
        if error.errno not in (errno.EPERM, errno.EACCES):
            raise
        return False


def observe_uid_quiescence(allowed):
    """Refuse survivors; inspect proc UID and the full possible Linux PID range.

    /proc alone is insufficient on Android's hidepid mount. Signal 0 also finds
    nondumpable tasks from this app domain, while status detects same-UID tasks
    in another SELinux domain even when signal 0 is denied. Nothing is killed.
    The caller supplies only separately verified current Java/owner identities.
    """
    expected = {entry["pid"]: entry for entry in allowed}
    if len(expected) != len(allowed) or os.getpid() not in expected:
        raise ValueError("Quiescence requires distinct identities and its own positive control")

    def revalidate():
        for pid, identity in expected.items():
            if process_identity(pid) != identity or identity["uids"] != (os.getuid(),) * 4:
                raise RuntimeError("Allowed process identity changed during quiescence")
            if not _signal_zero(pid):
                raise PermissionError("Allowed application process signal permission is unavailable")

    revalidate()
    observed_threads = set()
    for _ in range(2):
        # Proc directory ownership is useful but never the sole classifier:
        # the status UID is authoritative even for nondumpable proc files.
        listed = [int(name) for name in os.listdir("/proc") if name.isascii() and name.isdecimal()]
        if os.getpid() not in listed:
            raise RuntimeError("Process census lacks its own positive control")
        for pid in listed:
            if pid in expected:
                continue
            try:
                info = os.stat(f"/proc/{pid}")
            except (FileNotFoundError, ProcessLookupError):
                continue
            except PermissionError:
                info = None
            if info is not None and info.st_uid == os.getuid():
                raise FileExistsError("Another application UID process prevents session recovery")
            try:
                lines = _read(f"/proc/{pid}/status", 65536).splitlines()
            except (FileNotFoundError, ProcessLookupError, PermissionError):
                continue
            for line in lines:
                if line.startswith(b"Uid:"):
                    ids = line.split()[1:]
                    if len(ids) != 4 or any(not item.isdigit() for item in ids):
                        raise ValueError("Process census encountered malformed kernel UID data")
                    if str(os.getuid()).encode() in ids:
                        raise FileExistsError("Another application UID process prevents session recovery")
        # A process hidden from /proc is still found by the kernel permission
        # check, across every possible PID. Skip only the pinned allowlist.
        for pid in range(1, LINUX_PID_MAX_LIMIT):
            if pid not in expected and _signal_zero(pid):
                if _allowed_thread(pid, expected):
                    observed_threads.add(pid)
                    continue
                raise FileExistsError("A surviving application process prevents session recovery")
        revalidate()
    return {"schema": "foldgpt.uid-quiescence-observation.v1",
            "route": "proc-uid-and-full-linux-pid-range-signal-zero",
            "uid": os.getuid(), "passes": 2, "pidUpperExclusive": LINUX_PID_MAX_LIMIT,
            "allowedProcesses": [dict(entry, uids=list(entry["uids"])) for entry in allowed],
            "allowedThreadIdsObserved": len(observed_threads),
            "otherSignalableProcessesObserved": False, "nonzeroSignalsSent": 0}


def application_quiescence(value, parent_pid):
    allowed = verify_application_processes(value, parent_pid)
    allowed.append(process_identity(os.getpid()))
    return observe_uid_quiescence(allowed)
