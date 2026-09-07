import asyncio
import json
import urllib.request
import websockets

async def monitor():
    try:
        targets = json.loads(urllib.request.urlopen("http://127.0.0.1:9222/json").read())
    except Exception as e:
        print("Error fetching targets:", e, flush=True)
        return

    page = next((t for t in targets if t.get("type") == "page"), None)
    if not page:
        print("No page target found!", flush=True)
        return

    ws_url = page["webSocketDebuggerUrl"]
    print("Connecting to:", page["title"], "at", ws_url, flush=True)

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        
        hook = """
        (() => {
            window.addEventListener('focusin', (e) => {
                const tag = (e.target.tagName || '').toUpperCase();
                const role = e.target.getAttribute ? e.target.getAttribute('role') : '';
                const isEdit = e.target.isContentEditable || tag === 'INPUT' || tag === 'TEXTAREA' || role === 'textbox';
                if (isEdit) {
                    console.log('>>> FOLDGPT_EVENT:FOCUS_IN tag=' + tag + ' role=' + role + ' id=' + (e.target.id || 'none'));
                }
            }, true);

            window.addEventListener('focusout', (e) => {
                console.log('>>> FOLDGPT_EVENT:FOCUS_OUT');
            }, true);

            return 'HOOK_INSTALLED_OK';
        })()
        """
        await ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {"expression": hook, "returnByValue": True}
        }))

        print("Hook injected. Listening for events...", flush=True)
        try:
            while True:
                msg = await asyncio.wait_for(ws.recv(), timeout=12.0)
                data = json.loads(msg)
                if data.get("method") == "Runtime.consoleAPICalled":
                    args = data.get("params", {}).get("args", [])
                    text = " ".join([str(a.get("value", "")) for a in args])
                    if "FOLDGPT_EVENT" in text:
                        print("[EVENT-LIVE]", text, flush=True)
                elif data.get("id") == 2:
                    print("Hook result:", data.get("result", {}).get("result", {}).get("value"), flush=True)
        except asyncio.TimeoutError:
            print("Listening timeout reached (12s). Exiting cleanly.", flush=True)

if __name__ == "__main__":
    asyncio.run(monitor())
