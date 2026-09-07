import asyncio
import json
import websockets
from test_focus_event import CDPClient
from test_cdp_focus import get_ws_url

async def test():
    ws_url = get_ws_url()
    async with websockets.connect(ws_url) as ws:
        cdp = CDPClient(ws)
        def on_console(ev):
            if ev.get("method") == "Runtime.consoleAPICalled":
                for arg in ev["params"]["args"]:
                    val = str(arg.get("value", ""))
                    if "FOLDGPT" in val:
                        print(">>>", val)

        cdp.event_callbacks.append(on_console)
        await cdp.send("Runtime.enable")
        await cdp.send("Console.enable")
        
        print("--- Step 1: Blurring active element ---")
        await cdp.send("Runtime.evaluate", {"expression": "document.activeElement.blur()"})
        await asyncio.sleep(0.5)

        print("--- Step 2: Focusing prompt input ---")
        await cdp.send("Runtime.evaluate", {"expression": "document.querySelector('div[contenteditable]').focus()"})
        await asyncio.sleep(0.5)

        print("--- Step 3: Blurring again ---")
        await cdp.send("Runtime.evaluate", {"expression": "document.activeElement.blur()"})
        await asyncio.sleep(0.5)

if __name__ == "__main__":
    asyncio.run(test())
