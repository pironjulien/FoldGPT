import asyncio
import json
import os
import urllib.request
import websockets

def send_keyboard_toggle():
    os.system("/system/bin/am broadcast -a com.termux.x11.ACTION_CUSTOM -p com.termux.x11 --es what swipeUp >/dev/null 2>&1")

async def main():
    print("[*] Discovering ChatGPT page on port 9222...")
    req = urllib.request.urlopen("http://127.0.0.1:9222/json/list")
    pages = json.loads(req.read().decode())
    
    target_ws = None
    for p in pages:
        if p.get("title") == "ChatGPT" and p.get("type") == "page" and "avatar-overlay" not in p.get("url", ""):
            target_ws = p.get("webSocketDebuggerUrl")
            break
            
    if not target_ws and pages:
        target_ws = pages[0].get("webSocketDebuggerUrl")
        
    if not target_ws:
        print("[-] No WebSocket target found.")
        return

    print(f"[+] Connecting to {target_ws}...")
    keyboard_visible = False

    async with websockets.connect(target_ws) as ws:
        await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
        await ws.recv()
        print("[+] Runtime enabled.")

        hook_js = """
        (() => {
            if (window.__foldgpt_hooked) return "already_hooked";
            window.__foldgpt_hooked = true;
            
            function isEditable(el) {
                if (!el) return false;
                const tag = el.tagName;
                if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
                if (el.isContentEditable) return true;
                if (el.getAttribute && (el.getAttribute('role') === 'textbox' || el.getAttribute('contenteditable') === 'true')) return true;
                return false;
            }

            document.addEventListener('focusin', (e) => {
                if (isEditable(e.target)) {
                    console.log('__FOLDGPT_FOCUS_IN__');
                }
            }, true);

            document.addEventListener('focusout', (e) => {
                if (isEditable(e.target)) {
                    console.log('__FOLDGPT_FOCUS_OUT__');
                }
            }, true);

            return "hook_installed";
        })()
        """
        await ws.send(json.dumps({
            "id": 2,
            "method": "Runtime.evaluate",
            "params": {"expression": hook_js}
        }))
        await ws.recv()
        print("[+] Universal text focus hook installed!")
        print("[*] Ready. Touch any text input or search bar on your Fold.")

        while True:
            msg = await ws.recv()
            data = json.loads(msg)
            if data.get("method") == "Runtime.consoleAPICalled":
                params = data.get("params", {})
                args = params.get("args", [])
                if args:
                    val = args[0].get("value")
                    if val == "__FOLDGPT_FOCUS_IN__":
                        print("[⚡] Focus received on text element.")
                        if not keyboard_visible:
                            print("[>>>] AUTO-OPENING Samsung Soft Keyboard...")
                            send_keyboard_toggle()
                            keyboard_visible = True
                    elif val == "__FOLDGPT_FOCUS_OUT__":
                        print("[💤] Focus lost on text element.")
                        if keyboard_visible:
                            print("[<<<] AUTO-CLOSING Samsung Soft Keyboard...")
                            send_keyboard_toggle()
                            keyboard_visible = False

if __name__ == "__main__":
    asyncio.run(main())
