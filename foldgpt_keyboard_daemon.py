#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import time
import urllib.request
import websockets

def trigger_soft_keyboard():
    os.system("/system/bin/am broadcast -a com.termux.x11.ACTION_CUSTOM -p com.termux.x11 --es what swipeUp >/dev/null 2>&1")

async def monitor_focus():
    print("[*] FoldGPT Keyboard Daemon started.")
    sys.stdout.flush()

    while True:
        target_ws = None
        while not target_ws:
            try:
                req = urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=2)
                pages = json.loads(req.read().decode())
                for p in pages:
                    if p.get("title") == "ChatGPT" and p.get("type") == "page" and "avatar-overlay" not in p.get("url", ""):
                        target_ws = p.get("webSocketDebuggerUrl")
                        break
                if not target_ws and pages:
                    target_ws = pages[0].get("webSocketDebuggerUrl")
            except Exception:
                pass

            if not target_ws:
                await asyncio.sleep(1)

        print(f"[+] Connected to ChatGPT CDP: {target_ws}")
        sys.stdout.flush()

        keyboard_active = False

        try:
            async with websockets.connect(target_ws, ping_interval=10, ping_timeout=10) as ws:
                # Enable Runtime events
                await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
                await ws.recv()

                # Inject Universal DOM Focus Hook
                hook_code = """
                (() => {
                    if (window.__foldgpt_hooked) return "active";
                    window.__foldgpt_hooked = true;

                    function isTextInput(node) {
                        if (!node) return false;
                        const tag = node.tagName;
                        if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
                        if (node.isContentEditable) return true;
                        const role = node.getAttribute && node.getAttribute('role');
                        if (role === 'textbox' || role === 'searchbox') return true;
                        return false;
                    }

                    document.addEventListener('focusin', (e) => {
                        if (isTextInput(e.target)) {
                            console.log('__FOLDGPT_FOCUS_IN__');
                        }
                    }, true);

                    document.addEventListener('focusout', (e) => {
                        if (isTextInput(e.target)) {
                            console.log('__FOLDGPT_FOCUS_OUT__');
                        }
                    }, true);

                    return "ready";
                })()
                """
                await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": hook_code}}))
                await ws.recv()
                print("[+] Universal text focus hook successfully armed.")
                sys.stdout.flush()

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("method") == "Runtime.consoleAPICalled":
                        params = data.get("params", {})
                        args = params.get("args", [])
                        if args:
                            event_type = args[0].get("value")
                            if event_type == "__FOLDGPT_FOCUS_IN__":
                                if not keyboard_active:
                                    print("[⚡] Input focus detected -> Opening Samsung Keyboard")
                                    sys.stdout.flush()
                                    trigger_soft_keyboard()
                                    keyboard_active = True
                            elif event_type == "__FOLDGPT_FOCUS_OUT__":
                                if keyboard_active:
                                    # Grace period before closing
                                    await asyncio.sleep(0.15)
                                    print("[💤] Input blur detected -> Closing Samsung Keyboard")
                                    sys.stdout.flush()
                                    trigger_soft_keyboard()
                                    keyboard_active = False

        except Exception as e:
            print(f"[!] WebSocket disconnected: {e}. Reconnecting...")
            sys.stdout.flush()
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(monitor_focus())
