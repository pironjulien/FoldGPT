"""Run the isolated menu-effects fixture in an explicit disposable IAB target.

The existing raster harness supplies its bounded CDP transport and pixel
validators. Only this fixture is navigated; no official client CSS is changed.
Run with --serial USB_SERIAL --target CURRENT_DISPOSABLE_PAGE_ID. No phone
operation occurs on import or during --help.
"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import uuid

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("foldgpt_raster_common", Path(__file__).with_name("check-client-raster.py"))
common = importlib.util.module_from_spec(spec)
spec.loader.exec_module(common)


def make_guest(fixture, target, steps, repaint_every, deadline):
    guest = common.GUEST
    # Inspect the identical fixture state immediately after the screenshot as
    # well: resize/user navigation during capture must be inconclusive.
    needle = "print(json.dumps({'metadata':metadata,'png':screenshot['data']}),flush=True)"
    assert guest.count(needle) == 1, "Shared capture transport changed; review this adapter"
    guest = guest.replace(needle, """after=await call('Runtime.evaluate',{'expression':f'window.foldgptRendererProbe.snapshot({metadata["frame"]},"capture-after")','returnByValue':True,'awaitPromise':True})
                    if 'exceptionDetails' in after: raise RuntimeError('Post-capture fixture observation failed')
                    print(json.dumps({'metadata':metadata,'after':after['result']['value'],'png':screenshot['data']}),flush=True)""")
    for token, value in {
        '__HTML__': repr(base64.b64encode(fixture).decode()), '__TARGET__': repr(target),
        '__MODE__': repr('partial'), '__STEPS__': str(steps),
        '__REPAINT_EVERY__': str(repaint_every), '__DEADLINE__': str(deadline),
    }.items():
        guest = guest.replace(token, value)
    return guest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--target', required=True)
    parser.add_argument('--steps', type=common.positive_count, default=32,
                        help='Default 32: eight operations at each of four fractional geometries')
    parser.add_argument('--repaint-every', type=common.positive_count, default=4)
    args = parser.parse_args()
    sequence = list(common.expected_sequence('partial', args.steps, args.repaint_every))
    deadline = 30+3*len(sequence)
    fixture = Path(__file__).with_name('menu-effects-patterns.html').read_bytes()
    guest = make_guest(fixture, args.target, args.steps, args.repaint_every, deadline)
    output = ROOT/'downloads/gpu'/('menu-effects-'+uuid.uuid4().hex)
    output.mkdir(parents=True)
    errors = []
    try:
        process = subprocess.run([sys.executable, str(ROOT/'tools/device-shell.py'), '--serial', args.serial, 'python3', '-'],
                                 input=guest, text=True, encoding='utf-8', capture_output=True, timeout=deadline+25)
        stdout, stderr, exit_code = process.stdout, process.stderr, process.returncode
    except subprocess.TimeoutExpired as error:
        stdout, stderr, exit_code = error.stdout or '', error.stderr or '', None
        if isinstance(stdout, bytes): stdout = stdout.decode('utf-8', errors='replace')
        if isinstance(stderr, bytes): stderr = stderr.decode('utf-8', errors='replace')
        errors.append('Deadline expired; original-page restoration is unconfirmed')
    (output/'stderr.log').write_text(stderr, encoding='utf-8')
    observed, frames, comparisons, stable_references = [], [], [], []
    current = {}
    with (output/'metadata.jsonl').open('w', encoding='utf-8') as stream:
        for line in stdout.splitlines():
            try:
                record = json.loads(line)
                metadata, after = record['metadata'], record['after']
                if metadata.get('fixture') != 'menu-effects' or metadata.get('formatVersion') != 2:
                    raise ValueError('Unexpected fixture identity or format')
                key = (metadata['frame'], metadata['phase'])
                if len(observed) >= len(sequence) or key != sequence[len(observed)]:
                    raise ValueError('Missing, reordered or unexpected capture')
                data = base64.b64decode(record['png'], validate=True)
                name = f'frame-{metadata["frame"]:03d}-{metadata["phase"]}.png'
                # Preserve a frame even when the post-capture state is unstable.
                (output/name).write_bytes(data)
                stream.write(json.dumps({'metadata':metadata, 'after':after, 'pngSha256':hashlib.sha256(data).hexdigest()})+'\n')
                if metadata['state'] != after['state'] or metadata['samples'] != after['samples']:
                    raise ValueError('Fixture geometry or style changed during capture')
                image = Image.open(io.BytesIO(data)).convert('RGB')
                verification = common.verify_samples(metadata, image)
                observed.append(key)
                frames.append({'frame':key[0], 'phase':key[1], 'dpr':metadata['dpr'], **verification})
                if key[1] == 'partial': current = {}
                current[key[1]] = {'metadata':metadata, 'image':image, 'verification':verification}
                if key[1] == 'repeat': comparisons.append(common.compare_captures(current['partial'], current['repeat']))
                if key[1] == 'full': comparisons.append(common.compare_captures(current['partial'], current['full']))
                if key[1] == 'full-repeat':
                    comparison = common.compare_captures(current['full'], current['full-repeat'])
                    comparisons.append(comparison)
                    stable = comparison['comparable'] and comparison['changed'] == 0 and comparison['fromMismatched'] == comparison['toMismatched'] == 0
                    partial = common.compare_captures(current['partial'], current['full'])
                    stable_references.append({'frame':key[0], 'stableAndCorrect':stable,
                        'partialFailureCleared':stable and partial['comparable'] and partial['fromMismatched'] > 0})
                print(json.dumps(frames[-1]), flush=True)
            except (ValueError, KeyError, TypeError, IndexError, OSError) as error:
                errors.append('Capture validation failed: '+str(error))
                break
    report = {'fixture':'menu-effects', 'fixtureSha256':hashlib.sha256(fixture).hexdigest(),
        'steps':args.steps, 'expectedCaptures':len(sequence), 'allFramesReceived':observed == sequence,
        'guestExit':exit_code, 'errors':errors, 'frames':frames, 'comparisons':comparisons,
        'references':stable_references, 'actualDprs':sorted(set(frame['dpr'] for frame in frames)),
        'scope':'Uniform interior strips under real menu effects; no exact oracle for blur transition, shadow, text, icon or rounded-edge pixels; no GPU correction claim'}
    (output/'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('Evidence: '+str(output), flush=True)
    if exit_code != 0 or errors or observed != sequence or any(not item['comparable'] for item in comparisons):
        return 2
    return 1 if any(frame['mismatched'] for frame in frames) or any(item['changed'] for item in comparisons) else 0


if __name__ == '__main__':
    raise SystemExit(main())
