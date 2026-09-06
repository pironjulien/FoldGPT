"""Collect bounded evidence from one explicitly identified new Desktop test turn.

Reads only the selected guest identity, its global instructions and this exact
rollout through authorized ADB. Saves a compact report, not private history or
credentials. This is context loading evidence, not command execution proof.
"""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--rollout', required=True, help='Exact sessions/YYYY/MM/DD/rollout filename')
    parser.add_argument('--agents-sha256', required=True)
    parser.add_argument('--expected-model', required=True)
    parser.add_argument('--prompt-json', required=True, type=Path)
    args = parser.parse_args()
    require(re.fullmatch(r'sessions/\d{4}/\d{2}/\d{2}/rollout-[\dT-]+-[a-f0-9-]{36}\.jsonl', args.rollout), 'Invalid explicit rollout path')
    require(re.fullmatch(r'[a-f0-9]{64}', args.agents_sha256), 'Invalid instructions identity')
    prefix = ['adb', '-s', args.serial, 'exec-out', 'run-as', 'app.foldgpt', 'cat']

    def read(path, limit):
        data = subprocess.check_output(prefix + [path], timeout=30)
        require(len(data) <= limit, 'Evidence exceeds its bounded size')
        return data

    user = read('files/debian/etc/foldgpt-user', 128).decode().strip()
    require(re.fullmatch(r'[a-z_][a-z0-9_-]{0,31}', user) and user != 'root', 'Invalid selected guest')
    rows = [line.split(':') for line in read('files/debian/etc/passwd', 128 * 1024).decode().splitlines()]
    account = [r for r in rows if len(r) == 7 and r[0] == user]
    require(len(account) == 1, 'Ambiguous selected account')
    account = account[0]
    require(account[5] == '/home/' + user and int(account[2]) > 0, 'Unexpected selected account home or UID')
    codex_home = account[5] + '/.codex'
    # This collector is deliberately limited to the observed default CODEX_HOME.
    # An alternate profile needs its own explicit evidence contract.
    base = 'files/debian' + codex_home + '/'
    instructions = read(base + 'AGENTS.md', 128 * 1024)
    require(sha(instructions) == args.agents_sha256, 'Instructions changed since deployment')
    begin, end = b'<!-- foldgpt:environment:v1 begin -->', b'<!-- foldgpt:environment:v1 end -->'
    require(instructions.count(begin) == instructions.count(end) == 1, 'Missing unique context block')
    block = instructions[instructions.index(begin):instructions.index(end) + len(end)].decode()
    prompt = json.loads(args.prompt_json.read_text(encoding='utf-8-sig'))['text']
    raw = read(base + args.rollout, 8 * 1024 * 1024)
    loaded, prompts, answers, models, events, item_types = [], [], [], [], Counter(), Counter()
    for line_number, line in enumerate(raw.splitlines(), 1):
        event = json.loads(line)
        kind, payload = event.get('type'), event.get('payload', {})
        if kind == 'turn_context':
            models.append(payload.get('model'))
        if kind == 'event_msg':
            events[payload.get('type', '')] += 1
        if kind == 'response_item':
            item_types[payload.get('type', '')] += 1
            if payload.get('type') != 'message':
                continue
            for content in payload.get('content', []):
                text = content.get('text', '')
                if block in text:
                    loaded.append({'line': line_number, 'role': payload.get('role'),
                                   'blockSha256': sha(block.encode()), 'messageSha256': sha(text.encode())})
                if payload.get('role') == 'user' and text in (prompt, prompt + '\n'):
                    prompts.append(line_number)
                if payload.get('role') == 'assistant' and payload.get('phase') in ('final', 'final_answer'):
                    answers.append(text)
    report = {'schema': 'foldgpt.official-context-desktop.v1', 'status': 'FAIL',
              'modelDeliveryVerified': False, 'rolloutPath': codex_home + '/' + args.rollout,
              'rolloutSha256': sha(raw), 'rolloutBytes': len(raw), 'models': models,
              'agentsSha256': sha(instructions), 'loadedContextMessages': loaded,
              'promptLines': prompts, 'promptSha256': sha(prompt.encode()),
              'eventCounts': dict(events), 'responseItemCounts': dict(item_types),
              'answer': answers[-1] if answers else None,
              'scope': 'One actual Desktop context-only turn. No command, sandbox, project or update qualification.'}
    try:
        require(loaded and all(i['role'] == 'user' for i in loaded), 'Exact global block absent from actual context')
        require(len(prompts) == 1 and len(models) == 1 and models[0] == args.expected_model, 'Unexpected prompt or model turn')
        require(events['task_complete'] == 1 and len(answers) == 1, 'Actual turn has no unique final completion')
        require(not any(t in item_types for t in ('function_call', 'custom_tool_call', 'web_search_call')), 'Context-only turn used a tool')
        answer = answers[0].lower()
        require('android' in answer and 'linux' in answer and 'environment-' in answer, 'Answer does not identify host, guest and manifest')
        report['status'] = 'PASS'
        report['modelDeliveryVerified'] = True
    except Exception as error:
        report['error'] = str(error)
    repo = Path(__file__).resolve().parents[2]
    destination = repo / 'downloads/context' / ('desktop-' + uuid.uuid4().hex)
    destination.mkdir(parents=True)
    (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (destination / 'collector.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(dict(report, evidence=str(destination)), ensure_ascii=True, indent=2))
    raise SystemExit(0 if report['status'] == 'PASS' else 1)


if __name__ == '__main__':
    main()
