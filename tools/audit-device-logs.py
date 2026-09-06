"""Read-only FoldGPT log capture; print fixed diagnostic counters, never log text.

Raw evidence stays beneath ignored logs/. Treat it as private: logs may contain
account or conversation metadata. This tool never restarts or interacts with UI.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = {
    "runtime": {
        "keyring_unlocked": r"^FoldGPT keyring unlocked$",
        "keyring_unlock_failed": r"^FoldGPT keyring unlock failed",
        "gpu_driver_selected": r"^FoldGPT GPU driver selected:",
        "gpu_driver_not_installed": r"^FoldGPT GPU driver not installed;",
        "gpu_driver_incomplete": r"^FoldGPT GPU installation incomplete:",
        "gpu_process_crashed": r"GPU process exited unexpectedly:",
        "gpu_calibrated_timestamp_failed": r"vkGetCalibratedTimestamps(?:EXT|KHR) failed",
        "gpu_refresh_rate_failed": r"glXGetMscRateOML failed",
        "gpu_dmabuf_sync_failed": r"DMA-BUF renderer CPU access(?: completion)? failed:",
        "local_app_server_connected": r"app_server_connection.state_changed .*next=connected",
        "primary_runtime_manifest_404": r"Failed to download primary runtime manifest \(404",
        "process_sampler_boot_time_unavailable": r"Failed to collect child process snapshot.*Unable to get system boot time",
        "thread_scheduler_permission_failure": r"RAW: pthread_getschedparam failed: 1$",
        "system_dbus_socket_missing": r"Failed to connect to socket /run/dbus/system_bus_socket",
        "inotify_limit_unreadable": r"Failed to read /proc/sys/fs/inotify/max_user_watches",
        "udev_monitor_unavailable": r"Failed to initialize a udev monitor",
        "webgl_blocklisted": r"WebGL[12] blocklisted",
        "deprecated_push_endpoint": r"Registration response error message: DEPRECATED_ENDPOINT",
        "event_listener_limit_warning": r"MaxListenersExceededWarning",
        "filesystem_read_error": r"response_routed .*errorCode=-\d+ .*method=fs/readFile",
    },
    "ime": {
        "focus_listeners_attached": r"Focus listener attached to target",
        "keyboard_requests_applied": r"IME visible=(?:True|False) accepted=True",
        "keyboard_requests_declined": r"IME visible=(?:True|False) accepted=False",
        "warning_or_error_lines": r"\b(?:WARNING|ERROR|CRITICAL)\b",
    },
    "wm": {
        "software_renderer_llvmpipe": r"Unsupported GL renderer \(llvmpipe",
        "accessibility_bus_missing": r"org.a11y.Bus was not provided",
        "desktop_session_manager_absent": r"SESSION_MANAGER environment variable not defined",
    },
    "android-current": {
        "ime_endpoint_bind_failed": r"FoldGPT-IME: (?:Endpoint failed|Endpoint start failed)",
        "ime_address_already_used": r"FoldGPT-IME: .*Address already in use",
        "ime_listening": r"FoldGPT-IME: Endpoint listening",
        "ime_closed": r"FoldGPT-IME: Endpoint closed",
        "ime_applied": r"FoldGPT-IME: requested=(?:true|false) applied=true",
        "ime_declined": r"FoldGPT-IME: requested=(?:true|false) applied=false",
        "fatal_android_exception": r"AndroidRuntime: FATAL EXCEPTION",
        "optional_vendor_library_missing": r"Unable to open libpenguin.so",
    },
}


def summarize(text, patterns):
    lines = text.splitlines()
    summary = {"line_count": len(lines), "categories": {}}
    for label, pattern in patterns.items():
        matching = [number for number, line in enumerate(lines, 1) if re.search(pattern, line)]
        summary["categories"][label] = {"count": len(matching), "first_line": matching[0] if matching else None,
                                        "last_line": matching[-1] if matching else None}
    return summary


def capture(serial):
    adb = ["adb", "-s", serial]
    def read(*args):
        result = subprocess.run(adb + list(args), stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        if result.returncode:
            raise RuntimeError("A read-only device diagnostic failed; no raw error payload printed")
        return result.stdout

    uid = int(read("shell", "run-as", "app.foldgpt", "id", "-u").strip())
    table = read("shell", "ps", "-A", "-o", "UID,PID,PPID,COMM").decode(errors="replace")
    processes = []
    for line in table.splitlines():
        columns = line.split(maxsplit=3)
        if len(columns) == 4 and columns[0] == str(uid):
            processes.append({"pid": int(columns[1]), "parent": int(columns[2]), "comm": columns[3]})
    now = datetime.now(timezone.utc)
    destination = ROOT / "logs" / ("audit-" + now.strftime("%Y%m%dT%H%M%S%fZ"))
    destination.mkdir(parents=True)
    paths = {"runtime": "files/runtime.log", "ime": "files/debian/home/julien/.local/state/foldgpt-ime.log",
             "wm": "files/debian/home/julien/.local/state/foldgpt-wm.log"}
    raw = {name: read("exec-out", "run-as", "app.foldgpt", "cat", path) for name, path in paths.items()}
    raw["android-history"] = read("logcat", "-d", f"--uid={uid}", "-v", "threadtime",
                                  "FoldGPT:I", "FoldGPT-IME:I", "AndroidRuntime:E", "*:W")
    pids = {process["pid"] for process in processes}
    current = []
    for line in raw["android-history"].decode(errors="replace").splitlines():
        match = re.match(r"\d\d-\d\d\s+\S+\s+(\d+)\s+\d+\s+", line)
        if match and int(match[1]) in pids:
            current.append(line)
    raw["android-current"] = "\n".join(current).encode()
    report = {"captured_at": now.isoformat(), "evidence_directory": str(destination), "processes": processes,
              "scope": "Static log evidence and live processes; no execution or Remote test", "logs": {}}
    for name, data in raw.items():
        (destination / (name + ".log")).write_bytes(data)
        if name in PATTERNS:
            report["logs"][name] = summarize(data.decode(errors="replace"), PATTERNS[name])
    (destination / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    print(json.dumps(capture(args.serial), indent=2))
