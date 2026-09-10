import asyncio
import json
import urllib.request
import websockets

def get_ws_url():
    resp = urllib.request.urlopen("http://127.0.0.1:19222/json")
    targets = json.loads(resp.read().decode("utf-8"))
    for t in targets:
        if t.get("url") == "app://-/index.html":
            return t["webSocketDebuggerUrl"]
    return None

async def run():
    ws_url = get_ws_url()
    print("Found page WS:", ws_url)
    async with websockets.connect(ws_url) as ws:
        # Evaluate active element
        req = {
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {
                "expression": "document.title + ' | ' + (document.activeElement ? document.activeElement.tagName : 'none')"
            }
        }
        await ws.send(json.dumps(req))
        res = await ws.recv()
        print("DOM State:", res)

        # Inspect all editable / input elements in the page
        req2 = {
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {
                "expression": "Array.from(document.querySelectorAll('input, textarea, [contenteditable=\"true\"], [role=\"textbox\"]')).map(el => el.tagName + ' (id=' + el.id + ', placeholder=' + el.placeholder + ')')"
            }
        }
        await ws.send(json.dumps(req2))
        res2 = await ws.recv()
        print("Editable Elements Found:", res2)

if __name__ == "__main__":
    asyncio.run(run())
