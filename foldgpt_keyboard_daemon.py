#!/usr/bin/env python3
import asyncio
import json
import os
import sys
import time
import urllib.request
import websockets

def toggle_keyboard():
    os.system("/system/bin/am broadcast -a com.termux.x11.ACTION_CUSTOM -p com.termux.x11 --es what swipeUp >/dev/null 2>&1")

async def run():
    print("[*] Starting FoldGPT Keyboard Bridge (v2 - Debounced)...")
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

        print(f"[+] Connected to: {target_ws}")
        sys.stdout.flush()

        keyboard_state = False

        try:
            async with websockets.connect(target_ws, ping_interval=10, ping_timeout=10) as ws:
                await ws.send(json.dumps({"id": 1, "method": "Runtime.enable"}))
                await ws.recv()

                hook_code = """
                (() => {
                    function isTextInput(node) {
                        if (!node) return false;
                        const tag = node.tagName;
                        if (tag === 'INPUT' || tag === 'TEXTAREA') return true;
                        if (node.isContentEditable) return true;
                        const role = node.getAttribute && node.getAttribute('role');
                        if (role === 'textbox' || role === 'searchbox') return true;
                        return false;
                    }

                    let focusedInput = null;

                    document.addEventListener('focusin', (e) => {
                        if (isTextInput(e.target)) {
                            focusedInput = e.target;
                            console.log('__FOLDGPT_FOCUS_IN__');
                        }
                    }, true);

                    document.addEventListener('focusout', (e) => {
                        setTimeout(() => {
                            const current = document.activeElement;
                            if (!isTextInput(current)) {
                                focusedInput = null;
                                console.log('__FOLDGPT_FOCUS_OUT__');
                            }
                        }, 500);
                    }, true);

                    return "ready_v2";
                })()
                """
                await ws.send(json.dumps({"id": 2, "method": "Runtime.evaluate", "params": {"expression": hook_code}}))
                await ws.recv()
                print("[+] Debounced focus hook armed.")
                sys.stdout.flush()

                last_toggle_time = 0

                while True:
                    msg = await ws.recv()
                    data = json.loads(msg)
                    if data.get("method") == "Runtime.consoleAPICalled":
                        args = data.get("params", {}).get("args", [])
                        if args:
                            val = args[0].get("value")
                            now = time.time()
                            if val == "__FOLDGPT_FOCUS_IN__":
                                if not keyboard_state and (now - last_toggle_time > 1.0):
                                    print("[⚡] Real focus on text box -> Opening Keyboard")
                                    sys.stdout.flush()
                                    toggle_keyboard()
                                    keyboard_state = True
                                    last_toggle_time = now
                            elif val == "__FOLDGPT_FOCUS_OUT__":
                                if keyboard_state and (now - last_toggle_time > 1.0):
                                    print("[💤] Real blur -> Closing Keyboard")
                                    sys.stdout.flush()
                                    toggle_keyboard()
                                    keyboard_state = False
                                    last_toggle_time = now

        except Exception as e:
            print(f"[!] Reconnecting in 2s: {e}")
            sys.stdout.flush()
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(run())
