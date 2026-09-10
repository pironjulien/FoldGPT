import asyncio
import json
import websockets
from test_cdp_focus import get_ws_url

class CDPClient:
    def __init__(self, ws):
        self.ws = ws
        self.msg_id = 0
        self.pending = {}
        self.event_callbacks = []
        self._listener_task = asyncio.create_task(self._listen())

    async def _listen(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in self.pending:
                    self.pending[msg["id"]].set_result(msg)
                elif "method" in msg:
                    for cb in self.event_callbacks:
                        cb(msg)
        except Exception as e:
            pass

    async def send(self, method, params=None):
        self.msg_id += 1
        mid = self.msg_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        req = {"id": mid, "method": method, "params": params or {}}
        await self.ws.send(json.dumps(req))
        return await fut

async def main():
    ws_url = get_ws_url()
    print("Connecting to:", ws_url)
    async with websockets.connect(ws_url) as ws:
        cdp = CDPClient(ws)

        def on_event(ev):
            if ev.get("method") == "Runtime.consoleAPICalled":
                args = ev["params"]["args"]
                vals = [a.get("value") for a in args]
                print(">>> CONSOLE EVENT RECEIVED:", vals)

        cdp.event_callbacks.append(on_event)

        await cdp.send("Runtime.enable")
        await cdp.send("Console.enable")

        inject_js = """
        if (!window.__foldgpt_listener_installed) {
            window.__foldgpt_listener_installed = true;
            document.addEventListener('focusin', (e) => {
                const target = e.target;
                const isEditable = target.isContentEditable || 
                                   ['INPUT', 'TEXTAREA'].includes(target.tagName) || 
                                   target.getAttribute('role') === 'textbox';
                console.log('FOLDGPT_FOCUS_IN:editable=' + isEditable + ':tag=' + target.tagName + ':aria=' + (target.getAttribute('aria-label') || ''));
            }, true);
            document.addEventListener('focusout', (e) => {
                console.log('FOLDGPT_FOCUS_OUT:tag=' + e.target.tagName);
            }, true);
            'LISTENER_INSTALLED';
        } else {
            'ALREADY_INSTALLED';
        }
        """
        r = await cdp.send("Runtime.evaluate", {"expression": inject_js})
        print("Inject status:", r["result"]["result"]["value"])

        # Focus the prompt
        focus_js = """
        const el = document.querySelector('[contenteditable="true"], input, textarea');
        if (el) {
            el.focus();
            'FOCUSED';
        } else {
            'NOT_FOUND';
        }
        """
        r2 = await cdp.send("Runtime.evaluate", {"expression": focus_js})
        print("Focus result:", r2["result"]["result"]["value"])

        # Wait a bit for console event
        await asyncio.sleep(1)

        # Blur the prompt
        blur_js = "document.activeElement.blur(); 'BLURRED';"
        r3 = await cdp.send("Runtime.evaluate", {"expression": blur_js})
        print("Blur result:", r3["result"]["result"]["value"])

        await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
