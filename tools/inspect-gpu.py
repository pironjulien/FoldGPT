"""Inspect the active official client's GPU via local CDP, without page data.

Uses FoldGPT's existing diagnostic guest shell. No forwarding port, UI action,
renderer flag change, model request, or account/profile access is performed.
"""
import argparse
from pathlib import Path
import subprocess
import sys

GUEST = r'''
import asyncio
import json
import urllib.request
import websockets

async def inspect():
    endpoint = "http://127.0.0.1:9223/json/version"
    with urllib.request.urlopen(endpoint, timeout=3) as response:
        url = json.load(response)["webSocketDebuggerUrl"]
    if not url.startswith("ws://127.0.0.1:9223/devtools/browser/"):
        raise RuntimeError("Unexpected local diagnostic endpoint")
    async with websockets.connect(url, open_timeout=4) as websocket:
        await websocket.send(json.dumps({"id": 1, "method": "SystemInfo.getInfo"}))
        async def result():
            async for raw in websocket:
                message = json.loads(raw)
                if message.get("id") == 1:
                    return message
            raise RuntimeError("Diagnostic connection closed")
        message = await asyncio.wait_for(result(), 5)
        if "error" in message:
            raise RuntimeError("GPU diagnostic method unavailable")
        gpu = message["result"]["gpu"]
        attributes = gpu.get("auxAttributes", {})
        print(json.dumps({
            "devices": gpu.get("devices"),
            "featureStatus": gpu.get("featureStatus"),
            "renderer": {key: attributes[key] for key in (
                "glVendor", "glRenderer", "glVersion", "displayType", "glImplementationParts"
            ) if key in attributes},
            "scope": "Current client renderer; not a frame-rate or power measurement"
        }, indent=2))

asyncio.run(inspect())
'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    result = subprocess.run(
        [sys.executable, str(Path(__file__).with_name("device-shell.py")),
         "--serial", args.serial, "/usr/bin/python3", "-"],
        input=GUEST, text=True, timeout=30, capture_output=True,
    )
    if result.returncode:
        print("GPU inspection failed; verify that the FoldGPT runtime is active.", file=sys.stderr)
    else:
        print(result.stdout, end="")
    raise SystemExit(result.returncode)
