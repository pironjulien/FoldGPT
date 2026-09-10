import asyncio
import json
import websockets
from test_cdp_focus import get_ws_url

async def inspect():
    ws_url = get_ws_url()
    async with websockets.connect(ws_url) as ws:
        expr = """
        JSON.stringify(Array.from(document.querySelectorAll('input, textarea, [contenteditable], [role="textbox"]')).map(el => ({
            tag: el.tagName,
            id: el.id,
            placeholder: el.getAttribute('placeholder'),
            contenteditable: el.getAttribute('contenteditable'),
            ariaLabel: el.getAttribute('aria-label')
        })))
        """
        req = {
            "id": 10,
            "method": "Runtime.evaluate",
            "params": {
                "expression": expr
            }
        }
        await ws.send(json.dumps(req))
        res = json.loads(await ws.recv())
        print("Elements detail:\n", json.dumps(json.loads(res["result"]["result"]["value"]), indent=2))

if __name__ == "__main__":
    asyncio.run(inspect())
