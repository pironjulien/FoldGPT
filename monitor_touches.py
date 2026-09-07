import asyncio
import json
import urllib.request
import websockets

async def monitor():
    req = urllib.request.urlopen("http://127.0.0.1:9222/json/list")
    pages = json.loads(req.read().decode())
    target_ws = None
    for p in pages:
        if p.get("title") == "ChatGPT" and p.get("type") == "page" and "avatar-overlay" not in p.get("url", ""):
            target_ws = p.get("webSocketDebuggerUrl")
            break
    if not target_ws:
        target_ws = pages[0]["webSocketDebuggerUrl"]

    async with websockets.connect(target_ws) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await ws.recv()

        probe_js = """
        (() => {
            ['mousedown', 'pointerdown', 'click', 'focusin', 'focus'].forEach(evt => {
                document.addEventListener(evt, (e) => {
                    const tag = e.target ? (e.target.tagName + (e.target.id ? '#' + e.target.id : '') + (e.target.getAttribute('role') ? '[role=' + e.target.getAttribute('role') + ']' : '')) : 'unknown';
                    console.log(`[PROBE_EVENT] ${evt} on ${tag}`);
                }, true);
            });
            return "probe_armed";
        })()
        """
        await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": probe_js}}))
        res = await ws.recv()
        print("Probe response:", res)

        print("[*] Ready. Monitoring events...")
        while True:
            msg = await ws.recv()
            d = json.loads(msg)
            if d.get("method") == "Runtime.consoleAPICalled":
                for arg in d.get("params", {}).get("args", []):
                    val = arg.get("value", "")
                    if "[PROBE_EVENT]" in val or "FOCUS" in val:
                        print(val)

if __name__ == "__main__":
    asyncio.run(monitor())
