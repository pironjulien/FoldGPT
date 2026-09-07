"""Exercise a disposable existing IAB tab with real CSS/GPU pixel checks.

Only an explicit about:blank/example.com test target is accepted. The fixture is
served on a random guest loopback port and the original page is restored. No
client flags, files, profile settings or drivers are changed. Partial mode uses
transparent/translucent rows, fractional geometry, restricted state mutations,
and repeated captures before/after fixture subtree replacement. Host Pillow
checks background interiors, not the complete renderer or text/icon accuracy.
"""
import argparse
import base64
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import sys
import uuid
from PIL import Image

GUEST = r'''
import asyncio, base64, http.server, json, threading, urllib.request, websockets
HTML = base64.b64decode(__HTML__)
TARGET = __TARGET__
MODE = __MODE__
STEPS = __STEPS__
REPAINT_EVERY = __REPAINT_EVERY__
DEADLINE = __DEADLINE__
class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self,*args): pass
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type','text/html; charset=utf-8')
        self.send_header('Content-Length',str(len(HTML)))
        self.end_headers()
        self.wfile.write(HTML)
async def main():
    with urllib.request.urlopen('http://127.0.0.1:9223/json/list',timeout=3) as response:
        targets=json.load(response)
    target=next(t for t in targets if t['id']==TARGET)
    original=target['url']
    if target['type']!='page' or original not in ('about:blank','https://example.com/'):
        raise RuntimeError('Target is not a disposable diagnostic tab')
    if not target['webSocketDebuggerUrl'].startswith('ws://127.0.0.1:9223/devtools/page/'):
        raise RuntimeError('Unexpected CDP endpoint')
    server=http.server.HTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    sequence=0
    try:
        async with websockets.connect(target['webSocketDebuggerUrl'],open_timeout=4,max_size=16000000) as ws:
            async def call(method,params):
                nonlocal sequence
                sequence+=1
                ident=sequence
                await ws.send(json.dumps({'id':ident,'method':method,'params':params}))
                while True:
                    message=json.loads(await asyncio.wait_for(ws.recv(),10))
                    if message.get('id')==ident:
                        if 'error' in message: raise RuntimeError(message['error'])
                        return message['result']
            try:
                visible=await call('Runtime.evaluate',{'expression':'document.visibilityState','returnByValue':True})
                if visible.get('result',{}).get('value')!='visible':
                    raise RuntimeError('Open the diagnostic browser pane before starting the render test')
                result=await call('Page.navigate',{'url':f'http://127.0.0.1:{server.server_port}/renderer-patterns.html?mode={MODE}'})
                if result.get('errorText'): raise RuntimeError(result['errorText'])
                for _ in range(30):
                    ready=await call('Runtime.evaluate',{'expression':'!!window.foldgptRendererProbe','returnByValue':True})
                    if ready.get('result',{}).get('value') is True: break
                    await asyncio.sleep(.1)
                else: raise RuntimeError('Fixture did not load')
                async def capture(expression):
                    result=await call('Runtime.evaluate',{'expression':expression,'returnByValue':True,'awaitPromise':True})
                    if 'exceptionDetails' in result: raise RuntimeError('Fixture step failed')
                    metadata=result['result']['value']
                    screenshot=await call('Page.captureScreenshot',{'format':'png','fromSurface':True})
                    print(json.dumps({'metadata':metadata,'png':screenshot['data']}),flush=True)
                if MODE=='partial':
                    await capture('window.foldgptRendererProbe.snapshot(-1,"baseline")')
                for frame in range(STEPS):
                    await capture(f'window.foldgptRendererProbe.step({frame})')
                    if MODE=='partial':
                        await capture(f'window.foldgptRendererProbe.snapshot({frame},"repeat")')
                        if (frame+1)%REPAINT_EVERY==0 or frame==STEPS-1:
                            await capture(f'window.foldgptRendererProbe.repaint({frame})')
                            await capture(f'window.foldgptRendererProbe.snapshot({frame},"full-repeat")')
            finally:
                await call('Page.navigate',{'url':original})
    finally:
        server.shutdown()
        server.server_close()
asyncio.run(asyncio.wait_for(main(),DEADLINE))
'''

def expected_sequence(mode, steps, repaint_every):
    if mode == 'partial':
        yield -1, 'baseline'
    for frame in range(steps):
        yield frame, 'partial'
        if mode == 'partial':
            yield frame, 'repeat'
            if (frame + 1) % repaint_every == 0 or frame == steps - 1:
                yield frame, 'full'
                yield frame, 'full-repeat'


def sample_boxes(metadata, image):
    dpr = metadata['dpr']
    if not isinstance(dpr, (int, float)) or not math.isfinite(dpr) or dpr <= 0:
        raise ValueError('Invalid DPR')
    width, height = metadata['state']['viewport']
    if abs(image.width - width * dpr) > 1 or abs(image.height - height * dpr) > 1:
        raise ValueError('Screenshot dimensions do not match the recorded viewport and DPR')
    boxes = []
    for sample in metadata['samples']:
        x, y, w, h = (sample[k] * dpr for k in ('x', 'y', 'w', 'h'))
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            raise ValueError('Nonfinite sample geometry')
        # Exclude subpixel boundaries instead of allowing Pillow to pad a crop.
        box = (math.ceil(x) + 1, math.ceil(y) + 1, math.floor(x + w) - 1, math.floor(y + h) - 1)
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError('Empty or out-of-bounds sample')
        rgb = sample['rgb']
        if len(rgb) != 3 or any(type(v) is not int or not 0 <= v <= 255 for v in rgb):
            raise ValueError('Invalid expected RGB value')
        boxes.append((box, rgb))
    if not boxes:
        raise ValueError('No fixture pixels sampled')
    return boxes


def verify_samples(metadata, image):
    total = bad = 0
    for box, rgb in sample_boxes(metadata, image):
        pixels = list(image.crop(box).getdata())
        total += len(pixels)
        bad += sum(any(abs(a - b) > 1 for a, b in zip(pixel, rgb)) for pixel in pixels)
    return {'pixels': total, 'mismatched': bad}


def compare_captures(left, right):
    a, b = left['metadata'], right['metadata']
    label = {'frame': a['frame'], 'from': a['phase'], 'to': b['phase']}
    # Changed geometry/styles must never be reported as evidence of corruption.
    if a['state'] != b['state'] or a['samples'] != b['samples']:
        return {**label, 'comparable': False, 'reason': 'Final DOM, style, viewport, scroll or sample geometry changed'}
    first, second = left['image'], right['image']
    if first.size != second.size:
        return {**label, 'comparable': False, 'reason': 'Image dimensions changed'}
    total = changed = 0
    for box, _ in sample_boxes(a, first):
        x = list(first.crop(box).getdata())
        y = list(second.crop(box).getdata())
        total += len(x)
        changed += sum(any(abs(p - q) > 1 for p, q in zip(v, w)) for v, w in zip(x, y))
    return {**label, 'comparable': True, 'pixels': total, 'changed': changed,
            'fromMismatched': left['verification']['mismatched'],
            'toMismatched': right['verification']['mismatched']}


def positive_count(value):
    number = int(value)
    if not 1 <= number <= 128:
        raise argparse.ArgumentTypeError('Use a bounded count from 1 to 128')
    return number


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial',required=True)
    parser.add_argument('--target',required=True)
    parser.add_argument('--mode',choices=('basic','partial'),default='basic')
    parser.add_argument('--steps',type=positive_count,help='Default: 64 basic steps or 32 partial steps')
    parser.add_argument('--repaint-every',type=positive_count,default=8,
                        help='Partial mode: compare against a fresh fixture subtree every N steps and at the end')
    args=parser.parse_args()
    steps = args.steps if args.steps is not None else (64 if args.mode == 'basic' else 32)
    sequence = list(expected_sequence(args.mode, steps, args.repaint_every))
    # Each capture traverses ADB/PRoot/CDP. Keep the larger partial matrix bounded.
    deadline = 30 + 2 * len(sequence)
    root=Path(__file__).resolve().parents[2]
    destination=root/'downloads/gpu'/('raster-'+args.mode+'-'+uuid.uuid4().hex)
    destination.mkdir(parents=True)
    fixture = Path(__file__).with_name('renderer-patterns.html').read_bytes()
    values = {'__HTML__':repr(base64.b64encode(fixture).decode()),'__TARGET__':repr(args.target),
              '__MODE__':repr(args.mode),'__STEPS__':str(steps),
              '__REPAINT_EVERY__':str(args.repaint_every),'__DEADLINE__':str(deadline)}
    guest = GUEST
    for token, value in values.items():
        guest = guest.replace(token, value)
    errors = []
    try:
        process=subprocess.run([sys.executable,str(root/'tools/device-shell.py'),'--serial',args.serial,'python3','-'],
                               input=guest,text=True,encoding='utf-8',capture_output=True,timeout=deadline+25)
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, exit_code = error.stdout or '', error.stderr or '', None
        if isinstance(stdout, bytes): stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes): stderr = stderr.decode('utf-8', errors='replace')
        errors.append('Host deadline expired; guest completion and original-page restoration are unconfirmed')
    (destination/'stderr.log').write_text(stderr,encoding='utf-8')
    records, comparisons, observed = [], [], []
    current = {}
    with (destination/'metadata.jsonl').open('w', encoding='utf-8') as metadata_file:
        for line in stdout.splitlines():
            try:
                record=json.loads(line)
                data=base64.b64decode(record['png'],validate=True)
                frame=record['metadata']
                if frame.get('formatVersion') != 2 or frame.get('mode') != args.mode:
                    raise ValueError('Unexpected fixture format or mode')
                key=(frame['frame'],frame['phase'])
                if len(observed)>=len(sequence) or key!=sequence[len(observed)]:
                    raise ValueError('Missing, reordered or unexpected capture')
                im=Image.open(io.BytesIO(data)).convert('RGB')
                verification=verify_samples(frame,im)
                observed.append(key)
                summary={'frame':frame['frame'],'phase':frame['phase'],**verification,
                         'stateSha256':hashlib.sha256(json.dumps(frame['state'],sort_keys=True).encode()).hexdigest()}
                records.append(summary)
                name=f'frame-{frame["frame"]:03d}-{frame["phase"]}.png'
                if args.mode=='partial' or frame['frame']==0 or verification['mismatched']:
                    (destination/name).write_bytes(data)
                metadata_file.write(json.dumps({'metadata':frame,'pngSha256':hashlib.sha256(data).hexdigest()})+'\n')
                if frame['phase']=='partial': current={}
                current[frame['phase']]={'metadata':frame,'image':im,'verification':verification}
                if frame['phase']=='repeat': comparisons.append(compare_captures(current['partial'],current['repeat']))
                if frame['phase']=='full': comparisons.append(compare_captures(current['partial'],current['full']))
                if frame['phase']=='full-repeat': comparisons.append(compare_captures(current['full'],current['full-repeat']))
                print(json.dumps(summary),flush=True)
            except (ValueError,KeyError,TypeError,IndexError,OSError) as error:
                errors.append(f'Capture validation failed: {error}')
                break
    report={'mode':args.mode,'steps':steps,'repaintEvery':args.repaint_every,'expectedCaptures':len(sequence),
            'fixtureSha256':hashlib.sha256(fixture).hexdigest(),'frames':records,'comparisons':comparisons,
            'guestExit':exit_code,'errors':errors,'scope':'Sampled CSS row background interiors only; no GPU correction claim',
            'allFramesReceived':observed==sequence,'incomparablePairs':sum(not c['comparable'] for c in comparisons),
            'partialFailuresClearedByRepaint':sum(c['comparable'] and c['to']=='full' and c['fromMismatched']>0 and c['toMismatched']==0 for c in comparisons)}
    (destination/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Evidence: '+str(destination))
    if exit_code!=0 or errors or observed!=sequence or report['incomparablePairs']:
        return 2
    return 1 if any(r['mismatched'] for r in records) or any(c['comparable'] and c['changed'] for c in comparisons) else 0

if __name__=='__main__': raise SystemExit(main())
