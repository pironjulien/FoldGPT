"""Restart the initialized debug runtime after an authorized maintenance change.

Stops active Linux tasks. Uses FoldGPT's normal stop/start lifecycle, never a
package force-stop or a screen-lock change. Android must already be unlocked.
"""
import argparse
import subprocess
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    adb = ["adb", "-s", args.serial]
    service = "app.foldgpt/com.termux.x11.FoldRuntimeService"

    def run(*command):
        return subprocess.run(adb + list(command), check=True, capture_output=True,
                              text=True, timeout=30).stdout

    def runtime_pid():
        result = subprocess.run(adb + ["shell", "pidof", "app.foldgpt:runtime"],
                                capture_output=True, text=True, timeout=10)
        if result.returncode not in (0, 1):
            raise RuntimeError("Could not inspect runtime process")
        return result.stdout.strip()

    # Fail without restarting if Keystore cannot provide the startup secret.
    policy = run("shell", "dumpsys", "window", "policy")
    if "inputRestricted=false" not in policy or "showing=false" not in policy:
        raise RuntimeError("Android is locked or its lock state could not be verified")
    before = runtime_pid()
    if before:
        run("shell", "run-as", "app.foldgpt", "am", "startservice", "--user", "0",
            "-a", "stop", "-n", service)
        deadline = time.monotonic() + 15
        while runtime_pid():
            if time.monotonic() >= deadline:
                raise RuntimeError("Normal stop did not complete; no forced termination attempted")
            time.sleep(0.1)
    run("shell", "am", "start", "-n", "app.foldgpt/.FoldActivity")
    # If the Activity was already top-most, onResume is not called again.
    run("shell", "run-as", "app.foldgpt", "am", "start-foreground-service",
        "--user", "0", "-n", service)
    deadline = time.monotonic() + 15
    while not (after := runtime_pid()):
        if time.monotonic() >= deadline:
            raise RuntimeError("Runtime process did not start")
        time.sleep(0.1)
    print(f"Runtime restarted: {before or 'stopped'} -> {after}. Verify client startup separately.")


if __name__ == "__main__":
    main()
