"""Operate the Fold's existing desktop UI through its debug endpoint for validation.

The port must be an explicit ADB forward to the Fold's desktop renderer.
This tool changes no installed client files and never substitutes an engine.
"""
import argparse
import asyncio
import json
from pathlib import Path
import urllib.request
import websockets

ROOT = Path(__file__).resolve().parents[2]


async def main(args):
    args.output.resolve().relative_to(ROOT)
    args.expression.resolve().relative_to(ROOT)
    expression = args.expression.read_text(encoding="utf-8")
    with urllib.request.urlopen("http://127.0.0.1:" + str(args.port) + "/json/list", timeout=10) as response:
        targets = json.load(response)
    matching = [p for p in targets if p.get("url") == "app://-/index.html" and p.get("type") == "page"]
    if len(matching) != 1:
        raise ValueError("Fold desktop UI must have exactly one known main page")
    async with websockets.connect(matching[0]["webSocketDebuggerUrl"], max_size=32 * 1024 * 1024) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": expression, "returnByValue": True, "awaitPromise": True}}))
        while True:
            result = json.loads(await asyncio.wait_for(ws.recv(), timeout=30))
            if result.get("id") == 1:
                break
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump({"targetId": matching[0]["id"], "expression": expression, "response": result}, stream, indent=2)
    if "error" in result or "exceptionDetails" in result.get("result", {}):
        raise RuntimeError("UI evaluation failed: " + json.dumps(result))
    print(json.dumps({"saved":str(args.output)} if args.quiet else result["result"]["result"].get("value")))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--expression", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--quiet", action="store_true", help="Save the complete receipt without echoing its payload")
    arguments = parser.parse_args()
    if not 1 <= arguments.port <= 65535:
        parser.error("Invalid explicit forwarded port")
    asyncio.run(main(arguments))
