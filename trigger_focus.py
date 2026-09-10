import asyncio
import json
import urllib.request
import websockets

async def trigger():
    req = urllib.request.urlopen("http://127.0.0.1:9222/json/list")
    pages = json.loads(req.read().decode())
    target_ws = None
    for p in pages:
        if p.get("title") == "ChatGPT" and p.get("type") == "page" and "avatar-overlay" not in p.get("url", ""):
            target_ws = p.get("webSocketDebuggerUrl")
            break
            
    if not target_ws:
        print("[-] Target not found")
        return

    print(f"Connecting to {target_ws}...")
    async with websockets.connect(target_ws) as ws:
        js = """
        (() => {
            const el = document.querySelector('textarea, [contenteditable="true"], #prompt-textarea, [role="textbox"], input');
            if (el) {
                el.focus();
                return "FOCUSED: " + el.tagName + " (id=" + el.id + ", role=" + el.getAttribute("role") + ")";
            }
            return "NO_ELEMENT";
        })()
        """
        await ws.send(json.dumps({
            "id": 100,
            "method": "Runtime.evaluate",
            "params": {"expression": js}
        }))
        res = await ws.recv()
        print("Result:", res)

if __name__ == "__main__":
    asyncio.run(trigger())
