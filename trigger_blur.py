import asyncio
import json
import urllib.request
import websockets

async def blur():
    req = urllib.request.urlopen("http://127.0.0.1:9222/json/list")
    pages = json.loads(req.read().decode())
    target_ws = pages[0]["webSocketDebuggerUrl"]
    async with websockets.connect(target_ws) as ws:
        await ws.send(json.dumps({
            "id": 101,
            "method": "Runtime.evaluate",
            "params": {"expression": "document.activeElement.blur()"}
        }))
        await ws.recv()

if __name__ == "__main__":
    asyncio.run(blur())
