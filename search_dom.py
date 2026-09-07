import asyncio
import json
import urllib.request
import websockets

async def search_text():
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
        js = """
        (() => {
            const text = document.body.innerText;
            const lines = text.split('\\n').filter(l => l.trim().length > 0);
            return JSON.stringify(lines.slice(0, 30));
        })()
        """
        await ws.send(json.dumps({
            "id": 301,
            "method": "Runtime.evaluate",
            "params": {"expression": js}
        }))
        res = await ws.recv()
        data = json.loads(res)
        val = data.get("result", {}).get("result", {}).get("value")
        print("DOM Text:", val)

if __name__ == "__main__":
    asyncio.run(search_text())
