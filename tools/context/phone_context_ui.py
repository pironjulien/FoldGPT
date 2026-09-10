"""Developer CDP inspection of the actual FoldGPT client for context verification.

Connect only through an explicit loopback ADB-forwarded port and current page ID.
Evaluated expressions are developer test code, never production model tools.
"""
import argparse
import asyncio
import json
import urllib.request
from pathlib import Path
import websockets

INSPECT = r'''(() => {
 if(location.href!=='app://-/index.html')throw Error('Unexpected application');
 const visible=e=>{const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden'};
 return {url:location.href,buttons:[...document.querySelectorAll('button,[role=button],a')].filter(visible).map(e=>({
  tag:e.tagName,label:e.getAttribute('aria-label'),title:e.getAttribute('title'),testid:e.getAttribute('data-testid'),
  text:e.innerText?.slice(0,90),disabled:e.disabled,rect:(()=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y,w:r.width,h:r.height}})()})),
  editors:[...document.querySelectorAll('input,textarea,[contenteditable=true]')].filter(visible).map(e=>({tag:e.tagName,id:e.id,
  placeholder:e.getAttribute('placeholder'),role:e.getAttribute('role'),testid:e.getAttribute('data-testid'),
  textLength:(e.value??e.innerText??'').length}))};
})()'''


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--expression', type=Path)
    parser.add_argument('--method', default='Runtime.evaluate', choices=('Runtime.evaluate', 'Input.insertText', 'Input.dispatchKeyEvent', 'Input.dispatchMouseEvent'))
    parser.add_argument('--params', type=Path)
    parser.add_argument('--click-selector', help='Click one visible observed DOM control using CDP pointer input')
    args = parser.parse_args()
    with urllib.request.urlopen(f'http://127.0.0.1:{args.port}/json/list', timeout=5) as response:
        targets = json.load(response)
    matches = [t for t in targets if t.get('id') == args.target and t.get('type') == 'page' and t.get('url') == 'app://-/index.html']
    if len(matches) != 1:
        raise RuntimeError('Explicit main application target is missing or ambiguous')
    expected = f'ws://127.0.0.1:{args.port}/devtools/page/' + args.target
    if matches[0].get('webSocketDebuggerUrl') != expected:
        raise RuntimeError('Unexpected debugger endpoint')
    params = json.loads(args.params.read_text(encoding='utf-8-sig')) if args.params else {
        'expression': args.expression.read_text(encoding='utf-8') if args.expression else INSPECT,
        'returnByValue': True, 'awaitPromise': True}
    async with websockets.connect(expected, open_timeout=5, max_size=4 * 1024 * 1024) as ws:
        request_id = 0

        async def request(method, payload):
            nonlocal request_id
            request_id += 1
            await ws.send(json.dumps({'id': request_id, 'method': method, 'params': payload}))
            while True:
                value = json.loads(await asyncio.wait_for(ws.recv(), 10))
                if value.get('id') == request_id:
                    if 'error' in value or 'exceptionDetails' in value.get('result', {}):
                        raise RuntimeError(value)
                    return value.get('result', {})

        if args.click_selector:
            expression = '''(() => {
              const a=[...document.querySelectorAll(SELECTOR)].filter(e=>{
                const r=e.getBoundingClientRect();return r.width>0&&r.height>0&&getComputedStyle(e).visibility!=='hidden';
              });
              if(a.length!==1||a[0].disabled||a[0].getAttribute('aria-disabled')==='true')throw Error('Ambiguous or unavailable click target');
              const r=a[0].getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2};
            })()'''.replace('SELECTOR', json.dumps(args.click_selector))
            position = (await request('Runtime.evaluate', {'expression': expression, 'returnByValue': True}))['result']['value']
            for phase in ('mousePressed', 'mouseReleased'):
                await request('Input.dispatchMouseEvent', dict(position, type=phase, button='left', clickCount=1))
            result = {'clicked': args.click_selector}
        else:
            result = await request(args.method, params)
        print(json.dumps(result, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
