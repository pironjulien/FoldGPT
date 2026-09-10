"""Observe the real settings sidebar while changing three known sections.

Requires an explicit current app://-/index.html CDP target with settings open
and General, Plugins or Browser selected (French UI labels below). Only those
section buttons are clicked. No DOM, CSS, client files or launch flags change.
PNG evidence is cropped to their sidebar rectangle and saved under downloads.
Exit 0 means this bounded sample found no anomalies; 1 means a pixel anomaly;
2 means incomplete, unstable, unsupported or incomparable evidence.
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


# This expression returns only geometry/styles for the three allowed buttons,
# their descendants and ancestors. It does not read page text or account data.
OBSERVE = r'''(() => {
  if (location.href !== 'app://-/index.html' || document.visibilityState !== 'visible')
    throw new Error('Expected visible main application target');
  const names = ['Plugins', 'Navigateur', 'Général'];
  const rect = e => { const r=e.getBoundingClientRect(); return {x:r.x,y:r.y,w:r.width,h:r.height}; };
  const props = ['background-color','background-image','background-clip','opacity',
    'filter','backdrop-filter','transform','mix-blend-mode','mask-image','box-shadow',
    'border-top-width','border-right-width','border-bottom-width','border-left-width',
    'border-top-left-radius','border-top-right-radius','border-bottom-left-radius','border-bottom-right-radius',
    'outline-width','outline-style','outline-color','color','display','visibility',
    'font-family','font-size','font-weight','line-height','text-shadow','overflow-x','overflow-y'];
  const style = e => {const s=getComputedStyle(e);return Object.fromEntries(props.map(p=>[p,s.getPropertyValue(p)]));};
  const pseudo = (e,p) => {const s=getComputedStyle(e,p);return {content:s.content,display:s.display,
    background:s.backgroundImage,color:s.backgroundColor,shadow:s.boxShadow};};
  const found = names.map(name => {
    const matches=[...document.querySelectorAll('button[data-settings-panel-slug]')]
      .filter(e=>e.getAttribute('aria-label')===name);
    if(matches.length!==1)throw new Error('Missing or ambiguous allowed section: '+name);
    const e=matches[0],r=rect(e),s=style(e),slug=e.getAttribute('data-settings-panel-slug');
    if(name==='Plugins' && slug!=='plugins-settings' || name==='Navigateur' && slug!=='browser-use')
      throw new Error('Unexpected allowed section slug');
    if(e.disabled || r.w<=0 || r.h<=0 || r.x<0 || r.y<0 || r.x+r.w>innerWidth || r.y+r.h>innerHeight ||
       s.display==='none' || s.visibility!=='visible')throw new Error('Allowed section is not fully visible');
    const ancestors=[];
    for(let p=e.parentElement;p;p=p.parentElement)ancestors.push({rect:rect(p),style:style(p),
      scroll:[p.scrollLeft,p.scrollTop],before:pseudo(p,'::before'),after:pseudo(p,'::after')});
    const children=[...e.querySelectorAll('*')].map(c=>({tag:c.tagName,rect:rect(c),style:style(c),
      before:pseudo(c,'::before'),after:pseudo(c,'::after')}));
    const exclusions=[...e.querySelectorAll('svg,img,canvas,video,input')].map(rect);
    const walker=document.createTreeWalker(e,NodeFilter.SHOW_TEXT);
    for(let n=walker.nextNode();n;n=walker.nextNode())if(n.textContent.trim()){
      const range=document.createRange();range.selectNodeContents(n);
      for(const q of range.getClientRects())exclusions.push({x:q.x,y:q.y,w:q.width,h:q.height});
    }
    const right=Math.max(r.x+8,...exclusions.map(q=>q.x+q.w+6));
    const sample={x:right,y:r.y+6,w:r.x+r.w-8-right,h:r.h-12};
    if(sample.w<8 || sample.h<4)throw new Error('No safe blank interior in '+name);
    const hits=[];
    for(const fx of [.1,.5,.9])for(const fy of [.1,.5,.9]){
      const hit=document.elementFromPoint(sample.x+fx*sample.w,sample.y+fy*sample.h);
      hits.push(!!hit && (hit===e || e.contains(hit)));
    }
    if(hits.some(v=>!v))throw new Error('Blank sample is covered by another element');
    const clickPoint={x:sample.x+sample.w/2,y:sample.y+sample.h/2};
    return {name,slug,current:e.getAttribute('aria-current'),rect:r,style:s,ancestors,children,exclusions,sample,clickPoint,
      hover:e.matches(':hover'),focus:e.matches(':focus'),focusVisible:e.matches(':focus-visible'),
      before:pseudo(e,'::before'),after:pseudo(e,'::after'),
      activeAnimations:e.getAnimations({subtree:true}).filter(a=>a.playState==='running').length};
  });
  const selected=found.filter(b=>b.current==='page');
  if(selected.length!==1)throw new Error('Select General, Plugins or Browser before this diagnostic');
  if(found.some(b=>Math.abs(b.rect.x-found[0].rect.x)>1 || Math.abs(b.rect.w-found[0].rect.w)>1))
    throw new Error('Allowed sections do not share one sidebar column');
  const dpr=devicePixelRatio;
  // Integral CSS clip edges avoid CDP's second rounding of fractional clips
  // after the device-scale conversion. Sample interiors still use real DPR.
  const x=Math.floor(Math.min(...found.map(b=>b.rect.x)));
  const y=Math.floor(Math.min(...found.map(b=>b.rect.y)));
  const right=Math.ceil(Math.max(...found.map(b=>b.rect.x+b.rect.w)));
  const bottom=Math.ceil(Math.max(...found.map(b=>b.rect.y+b.rect.h)));
  return {formatVersion:1,selected:selected[0].name,buttons:found,dpr,
    viewport:[innerWidth,innerHeight],scroll:[scrollX,scrollY],
    visualViewport:visualViewport ? [visualViewport.offsetLeft,visualViewport.offsetTop,visualViewport.scale] : null,
    clip:{x,y,w:right-x,h:bottom-y}};
})()'''


GUEST = r'''
import asyncio, json, urllib.request, websockets
TARGET=__TARGET__
CYCLES=__CYCLES__
REPEATS=__REPEATS__
DEADLINE=__DEADLINE__
OBSERVE=__OBSERVE__
async def main():
    with urllib.request.urlopen('http://127.0.0.1:9223/json/list',timeout=3) as response:
        targets=json.load(response)
    matches=[t for t in targets if t['id']==TARGET]
    if len(matches)!=1: raise RuntimeError('Explicit CDP target is missing or ambiguous')
    target=matches[0]
    if target['type']!='page' or target['url']!='app://-/index.html':
        raise RuntimeError('Explicit target is not the main application page')
    if not target['webSocketDebuggerUrl'].startswith('ws://127.0.0.1:9223/devtools/page/'):
        raise RuntimeError('Unexpected CDP endpoint')
    seq=0
    async with websockets.connect(target['webSocketDebuggerUrl'],open_timeout=4,max_size=16000000) as ws:
        async def call(method,params):
            nonlocal seq
            seq+=1
            ident=seq
            await ws.send(json.dumps({'id':ident,'method':method,'params':params}))
            while True:
                reply=json.loads(await asyncio.wait_for(ws.recv(),8))
                if reply.get('id')==ident:
                    if 'error' in reply: raise RuntimeError(reply['error'])
                    return reply['result']
        async def observe():
            reply=await call('Runtime.evaluate',{'expression':OBSERVE,'returnByValue':True})
            if 'exceptionDetails' in reply: raise RuntimeError('Allowed sidebar observation failed')
            return reply['result']['value']
        async def select(name):
            before=await observe()
            b=next(b for b in before['buttons'] if b['name']==name)
            point=b['clickPoint']
            # Real input reproduces selection/hover/focus behavior. The point was
            # checked live against an explicit allowed section button.
            for kind in ['mouseMoved','mousePressed','mouseReleased']:
                params={'type':kind,**point,'button':'none' if kind=='mouseMoved' else 'left',
                        'buttons':1 if kind=='mousePressed' else 0}
                if kind!='mouseMoved': params['clickCount']=1
                await call('Input.dispatchMouseEvent',params)
            for _ in range(30):
                current=await observe()
                if current['selected']==name:return
                await asyncio.sleep(.05)
            raise RuntimeError('Allowed section click did not select requested section')
        async def capture(step,repeat,name):
            before=await observe()
            if before['selected']!=name: raise RuntimeError('Section changed unexpectedly')
            c=before['clip']
            screenshot=await call('Page.captureScreenshot',{'format':'png','fromSurface':True,
                'captureBeyondViewport':False,'clip':{'x':c['x']+before['scroll'][0],
                    'y':c['y']+before['scroll'][1],'width':c['w'],'height':c['h'],'scale':1}})
            after=await observe()
            print(json.dumps({'type':'capture','step':step,'repeat':repeat,'selected':name,
                'before':before,'after':after,'png':screenshot['data']}),flush=True)
        initial=(await observe())['selected']
        completed=False
        try:
            for repeat in range(REPEATS):
                if repeat: await asyncio.sleep(.08)
                await capture(-1,repeat,initial)
            for step,name in enumerate(['Plugins','Navigateur','Général']*CYCLES):
                await select(name)
                for repeat in range(REPEATS):
                    if repeat: await asyncio.sleep(.08)
                    await capture(step,repeat,name)
            completed=True
        finally:
            restored=False
            try:
                if (await observe())['selected']!=initial: await select(initial)
                restored=(await observe())['selected']==initial
            finally:
                print(json.dumps({'type':'completion','completed':completed,'restored':restored}),flush=True)
asyncio.run(asyncio.wait_for(main(),DEADLINE))
'''


def rgba(value):
    """Parse computed legacy CSS rgb/rgba; unsupported color spaces stay explicit."""
    import re
    match = re.fullmatch(r'rgba?\(([^)]+)\)', value)
    if not match:
        raise ValueError('Unsupported computed background color: ' + value)
    channels = [float(v.strip()) for v in match[1].split(',')]
    if len(channels) == 3:
        channels.append(1)
    if len(channels) != 4 or not all(math.isfinite(v) for v in channels):
        raise ValueError('Invalid computed background color')
    if any(not 0 <= v <= 255 for v in channels[:3]) or not 0 <= channels[3] <= 1:
        raise ValueError('Out-of-range computed background color')
    return channels


def expected_background(button):
    """Compose only demonstrably plain backgrounds; reject unsupported effects."""
    layers = [*reversed(button['ancestors']), button]
    rgb = None
    for layer in layers:
        s = layer['style']
        for prop, allowed in [('background-image', 'none'), ('filter', 'none'),
                              ('backdrop-filter', 'none'), ('transform', 'none'),
                              ('mix-blend-mode', 'normal'), ('mask-image', 'none'),
                              ('box-shadow', 'none'), ('opacity', '1')]:
            if s[prop] != allowed:
                raise ValueError('Unsupported background effect: ' + prop)
        for key in ('before', 'after'):
            pseudo = layer[key]
            if pseudo['display'] != 'none' and pseudo['content'] not in ('none', 'normal'):
                raise ValueError('Pseudo-element requires manual pixel assessment')
        color = rgba(s['background-color'])
        if color[3] == 1:
            rgb = color[:3]
        elif color[3] > 0:
            if rgb is None:
                raise ValueError('No known opaque ancestor background')
            rgb = [c * color[3] + old * (1 - color[3]) for c, old in zip(color, rgb)]
    if rgb is None:
        raise ValueError('No known opaque ancestor background')
    # Descendants can span the blank area, but must be transparent and plain.
    p = button['sample']
    for child in button['children']:
        r = child['rect']
        if r['x'] >= p['x'] + p['w'] or r['x'] + r['w'] <= p['x'] or r['y'] >= p['y'] + p['h'] or r['y'] + r['h'] <= p['y']:
            continue
        s = child['style']
        if rgba(s['background-color'])[3] or any(s[k] != 'none' for k in ('background-image', 'filter', 'backdrop-filter', 'mask-image', 'box-shadow')):
            raise ValueError('Painted descendant overlaps the blank sample')
        for key in ('before', 'after'):
            if child[key]['display'] != 'none' and child[key]['content'] not in ('none', 'normal'):
                raise ValueError('Descendant pseudo-element overlaps sample')
    return rgb


def sample_boxes(state, image):
    dpr, clip = state['dpr'], state['clip']
    if not isinstance(dpr, (int, float)) or not math.isfinite(dpr) or dpr <= 0:
        raise ValueError('Invalid DPR')
    if state['visualViewport'] not in (None, [0, 0, 1]):
        raise ValueError('Visual viewport is scaled or offset')
    if abs(image.width - clip['w'] * dpr) > .51 or abs(image.height - clip['h'] * dpr) > .51:
        raise ValueError('Cropped PNG dimensions do not match geometry and DPR')
    boxes = []
    for button in state['buttons']:
        p = button['sample']
        x, y, w, h = (p['x'] - clip['x']) * dpr, (p['y'] - clip['y']) * dpr, p['w'] * dpr, p['h'] * dpr
        if not all(math.isfinite(v) for v in (x, y, w, h)):
            raise ValueError('Invalid sample geometry')
        box = math.ceil(x) + 1, math.ceil(y) + 1, math.floor(x + w) - 1, math.floor(y + h) - 1
        if not (0 <= box[0] < box[2] <= image.width and 0 <= box[1] < box[3] <= image.height):
            raise ValueError('Empty or out-of-bounds blank sample')
        boxes.append((button['name'], box))
    if len(boxes) != 3:
        raise ValueError('Expected exactly three blank samples')
    return boxes


def verify_capture(record, image):
    state = record['before']
    result = {'stableDuringCapture': state == record['after'], 'samples': [], 'unsupported': []}
    for button, (name, box) in zip(state['buttons'], sample_boxes(state, image)):
        try:
            if button['activeAnimations']:
                raise ValueError('Button has a running animation')
            rgb = expected_background(button)
        except ValueError as error:
            result['unsupported'].append({'name': name, 'reason': str(error)})
            continue
        pixels = list(image.crop(box).getdata())
        # Two levels cover round-to-byte and alpha quantization, while black or
        # colored corruption remains visible. Expected colors are not hardcoded.
        bad = sum(any(abs(a - b) > 2 for a, b in zip(pixel, rgb)) for pixel in pixels)
        result['samples'].append({'name': name, 'pixels': len(pixels), 'mismatched': bad, 'expectedRgb': rgb})
    return result


def compare(left, right, kind):
    result = {'kind': kind, 'from': [left['record']['step'], left['record']['repeat']],
              'to': [right['record']['step'], right['record']['repeat']], 'comparable': False}
    if not left['verification']['stableDuringCapture'] or not right['verification']['stableDuringCapture']:
        return {**result, 'reason': 'Button state changed during capture'}
    a, b = left['record']['before'], right['record']['before']
    if a != b or left['image'].size != right['image'].size:
        return {**result, 'reason': 'Button style, focus, hover, geometry, scroll or viewport changed'}
    total = changed = 0
    for _, box in sample_boxes(a, left['image']):
        first = list(left['image'].crop(box).getdata())
        second = list(right['image'].crop(box).getdata())
        total += len(first)
        changed += sum(any(abs(p - q) > 1 for p, q in zip(x, y)) for x, y in zip(first, second))
    return {**result, 'comparable': True, 'pixels': total, 'changed': changed}


def bounded_count(value):
    count = int(value)
    if not 2 <= count <= 16:
        raise argparse.ArgumentTypeError('Use a count from 2 to 16')
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--target', required=True, help='Explicit current main-page CDP target ID')
    parser.add_argument('--cycles', type=bounded_count, default=6)
    parser.add_argument('--repeats', type=bounded_count, default=3)
    args = parser.parse_args()
    sequence = [(step, repeat) for step in range(-1, 3 * args.cycles) for repeat in range(args.repeats)]
    deadline = 30 + 2 * len(sequence)
    root = Path(__file__).resolve().parents[2]
    output = root / 'downloads/gpu' / ('settings-menu-' + uuid.uuid4().hex)
    output.mkdir(parents=True)
    replacements = {'__TARGET__': repr(args.target), '__CYCLES__': str(args.cycles),
                    '__REPEATS__': str(args.repeats), '__DEADLINE__': str(deadline), '__OBSERVE__': repr(OBSERVE)}
    guest = GUEST
    for key, value in replacements.items():
        guest = guest.replace(key, value)
    errors = []
    try:
        process = subprocess.run([sys.executable, str(root / 'tools/device-shell.py'), '--serial', args.serial, 'python3', '-'],
                                 input=guest, text=True, encoding='utf-8', capture_output=True, timeout=deadline + 20)
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, exit_code = error.stdout or '', error.stderr or '', None
        if isinstance(stdout, bytes): stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes): stderr = stderr.decode('utf-8', errors='replace')
        errors.append('Host deadline expired; initial-section restoration is unconfirmed')
    (output / 'stderr.log').write_text(stderr, encoding='utf-8')
    observed, records, comparisons, latest = [], [], [], {}
    previous = completion = None
    with (output / 'metadata.jsonl').open('w', encoding='utf-8') as metadata:
        for line in stdout.splitlines():
            try:
                record = json.loads(line)
                if record['type'] == 'completion':
                    if completion is not None:
                        raise ValueError('Duplicate completion')
                    completion = record
                    continue
                if completion is not None or record['type'] != 'capture':
                    raise ValueError('Unexpected record after completion')
                key = record['step'], record['repeat']
                if len(observed) >= len(sequence) or key != sequence[len(observed)]:
                    raise ValueError('Missing, reordered or unexpected capture')
                if record['before']['formatVersion'] != 1 or record['before']['selected'] != record['selected']:
                    raise ValueError('Unexpected observation format or selection')
                if record['step'] >= 0 and record['selected'] != ['Plugins', 'Navigateur', 'Général'][record['step'] % 3]:
                    raise ValueError('Unexpected selected section')
                png = base64.b64decode(record.pop('png'), validate=True)
                image = Image.open(io.BytesIO(png)).convert('RGB')
                name = f'step-{record["step"]:03d}-repeat-{record["repeat"]}.png'
                (output / name).write_bytes(png)
                metadata.write(json.dumps({**record, 'file': name, 'pngSha256': hashlib.sha256(png).hexdigest()}) + '\n')
                verification = verify_capture(record, image)
                item = {'record': record, 'image': image, 'verification': verification}
                summary = {'step': record['step'], 'repeat': record['repeat'], 'selected': record['selected'], **verification}
                records.append(summary)
                observed.append(key)
                if record['repeat'] and previous is not None:
                    comparisons.append(compare(previous, item, 'no-input-repeat'))
                if record['repeat'] == 0:
                    # Initial hover/focus may differ: return comparisons begin
                    # after the first real click on each section.
                    prior = latest.get(record['selected'])
                    if prior is not None:
                        comparisons.append(compare(prior, item, 'return-to-section'))
                if record['step'] >= 0:
                    latest[record['selected']] = item
                previous = item
            except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
                errors.append('Capture validation failed: ' + str(error))
                break
    report = {'cycles': args.cycles, 'repeats': args.repeats, 'expectedCaptures': len(sequence),
              'receivedCaptures': len(observed), 'completeSequence': observed == sequence,
              'guestExit': exit_code, 'completion': completion, 'errors': errors,
              'records': records, 'comparisons': comparisons,
              'incomparablePairs': sum(not c['comparable'] for c in comparisons),
              'unsupportedSamples': sum(len(r['unsupported']) for r in records),
              'unstableCaptures': sum(not r['stableDuringCapture'] for r in records),
              'sampledPixels': sum(s['pixels'] for r in records for s in r['samples']),
              'mismatchedPixels': sum(s['mismatched'] for r in records for s in r['samples']),
              'changedPixels': sum(c.get('changed', 0) for c in comparisons),
              'scope': 'Only blank interiors of three real settings-section buttons; cropped menu images retained for manual inspection. No whole-UI or GPU correctness claim.'}
    invalid = exit_code != 0 or errors or observed != sequence or not completion or not completion.get('completed') or not completion.get('restored') or report['incomparablePairs'] or report['unsupportedSamples'] or report['unstableCaptures']
    report['exitCode'] = 2 if invalid else (1 if report['mismatchedPixels'] or report['changedPixels'] else 0)
    (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: v for k, v in report.items() if k not in ('records', 'comparisons')}, ensure_ascii=False))
    print('Evidence: ' + str(output))
    return report['exitCode']


if __name__ == '__main__':
    raise SystemExit(main())
