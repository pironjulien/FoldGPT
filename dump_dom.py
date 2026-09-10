import asyncio
import json
import urllib.request
import websockets

async def check():
    targets = json.loads(urllib.request.urlopen('http://127.0.0.1:9222/json').read())
    # Find the main app page, not the avatar-overlay
    page = next((t for t in targets if t.get('url') == 'app://-/index.html'), None)
    if not page:
        print("Main page app://-/index.html not found!")
        return

    print("Target found:", page["id"], page["url"])
    async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
        await ws.send(json.dumps({'id': 1, 'method': 'Runtime.enable'}))
        
        js = """
        (() => {
            const inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable="true"], [role="textbox"], [id="prompt-textarea"], [placeholder]'));
            return inputs.map(el => {
                const r = el.getBoundingClientRect();
                return {
                    tag: el.tagName,
                    id: el.id,
                    placeholder: el.getAttribute('placeholder'),
                    role: el.getAttribute('role'),
                    rect: { x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) }
                };
            });
        })()
        """
        await ws.send(json.dumps({'id': 2, 'method': 'Runtime.evaluate', 'params': {'expression': js, 'returnByValue': True}}))
        while True:
            resp = json.loads(await ws.recv())
            if resp.get('id') == 2:
                print(json.dumps(resp['result']['result']['value'], indent=2), flush=True)
                break

if __name__ == '__main__':
    asyncio.run(check())
