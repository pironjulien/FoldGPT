import asyncio
import json
import os
import subprocess
import urllib.request
import websockets

class KeyboardBridge:
    def __init__(self):
        self.keyboard_showing = False
        self.msg_id = 0
        self.pending = {}

    def get_ws_url(self):
        try:
            req = urllib.request.urlopen("http://127.0.0.1:9222/json", timeout=2)
            targets = json.loads(req.read().decode("utf-8"))
            for t in targets:
                if t.get("url") == "app://-/index.html":
                    return t["webSocketDebuggerUrl"]
        except Exception as e:
            print("Failed to get WS url:", e)
        return None

    def trigger_keyboard(self, target_state):
        if target_state != self.keyboard_showing:
            print(f"[*] IME state transition: {self.keyboard_showing} -> {target_state}")
            subprocess.run([
                "am", "broadcast",
                "-a", "com.termux.x11.ACTION_CUSTOM",
                "-p", "com.termux.x11",
                "--es", "what", "toggle soft keyboard"
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            self.keyboard_showing = target_state

    async def run(self):
        while True:
            ws_url = self.get_ws_url()
            if not ws_url:
                await asyncio.sleep(2)
                continue
            
            print("[+] Connected to ChatGPT CDP at:", ws_url)
            try:
                async with websockets.connect(ws_url) as ws:
                    self.ws = ws
                    asyncio.create_task(self._listener())

                    # Enable Console & Runtime
                    await self._send("Runtime.enable")
                    await self._send("Console.enable")

                    # Inject DOM Focus / Blur listener
                    inject_js = """
                    (function() {
                        if (window.__foldgpt_ime_bridge) return 'ALREADY_ACTIVE';
                        window.__foldgpt_ime_bridge = true;

                        function isTextInput(el) {
                            if (!el) return false;
                            if (el.isContentEditable) return true;
                            if (['INPUT', 'TEXTAREA'].includes(el.tagName)) return true;
                            if (el.getAttribute('role') === 'textbox') return true;
                            return false;
                        }

                        document.addEventListener('focusin', function(e) {
                            if (isTextInput(e.target)) {
                                console.log('FOLDGPT_IME:IN:' + e.target.tagName);
                            }
                        }, true);

                        document.addEventListener('focusout', function(e) {
                            console.log('FOLDGPT_IME:OUT:' + e.target.tagName);
                        }, true);

                        return 'INITIALIZED';
                    })()
                    """
                    res = await self._send("Runtime.evaluate", {"expression": inject_js})
                    print("[+] Bridge script status:", res.get("result", {}).get("result", {}).get("value"))

                    # Keep alive and handle events
                    while not ws.closed:
                        await asyncio.sleep(1)

            except Exception as e:
                print("[-] Connection lost or error:", e)
                await asyncio.sleep(2)

    async def _listener(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                if "id" in msg and msg["id"] in self.pending:
                    self.pending[msg["id"]].set_result(msg)
                elif msg.get("method") == "Runtime.consoleAPICalled":
                    args = msg.get("params", {}).get("args", [])
                    if args:
                        val = str(args[0].get("value", ""))
                        if val.startswith("FOLDGPT_IME:IN:"):
                            self.trigger_keyboard(True)
                        elif val.startswith("FOLDGPT_IME:OUT:"):
                            self.trigger_keyboard(False)
        except Exception:
            pass

    async def _send(self, method, params=None):
        self.msg_id += 1
        mid = self.msg_id
        fut = asyncio.get_running_loop().create_future()
        self.pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params or {}}))
        return await fut

if __name__ == "__main__":
    bridge = KeyboardBridge()
    asyncio.run(bridge.run())
