import asyncio
import json
import urllib.request
import websockets

async def clear():
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
            const el = document.querySelector('#prompt-textarea, [contenteditable="true"], [role="textbox"], p');
            if (el) {
                el.innerText = '';
                el.blur();
                return 'CLEARED';
            }
            return 'NOT_FOUND';
        })()
        """
        await ws.send(json.dumps({
            "id": 401,
            "method": "Runtime.evaluate",
            "params": {"expression": js}
        }))
        res = await ws.recv()
        print(res)

if __name__ == "__main__":
    asyncio.run(clear())
