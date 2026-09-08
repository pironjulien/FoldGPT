import pathlib, re, json, collections, hashlib
ROOT = pathlib.Path(__file__).resolve().parents[2]
BASE = ROOT / 'work/ci-results'
HEADER = re.compile(r'^\s*(?P<status>(?:TRY \d+ )?(?:FAIL|ABRT|TMT)|PASS|FLAKY \d+/\d+|SLOW|RETRY \d+/\d+)\s+\[\s*[^]]+\]\s+\([^)]+\)\s+(?P<binary>\S+)\s+(?P<test>\S+)')
read_json = lambda path: json.loads(path.read_bytes())

def parse(run):
    path = BASE/run/'engine/evidence/engine-full-tests.log'
    data = path.read_bytes()
    lines = data.decode('utf-8').splitlines()
    summary = max(i for i,line in enumerate(lines) if line.startswith('     Summary ['))
    finals, headers, blocks = {}, [], {}
    for i,line in enumerate(lines):
        match = HEADER.match(line)
        if not match:
            continue
        if i < summary:
            headers.append((i, match.groupdict()))
        elif match['status'].endswith(('FAIL','ABRT','TMT')):
            finals[(match['binary'],match['test'])] = {'summaryLine':i+1,'status':match['status'].split()[-1]}
    for index,(start,head) in enumerate(headers):
        end = headers[index+1][0] if index+1<len(headers) else summary
        key = head['binary'],head['test']
        if key in finals and head['status'].startswith('TRY 2 '):
            blocks[key] = (start,end,lines[start:end])
    assert len(finals) == len(blocks)
    cases = []
    for key,final in finals.items():
        start,end,chunk = blocks[key]
        text = '\n'.join(chunk)
        if 'overflowed its stack' in text: category='stack_overflow'
        elif 'Snapshot Summary' in text: category='snapshot_difference'
        elif key[0]=='codex-http-client': category='tls_assertion'
        elif key[0]=='codex-v8-poc': category='v8_feature_assertion'
        elif final['status']=='TMT': category='runner_timeout_60s'
        elif 'bwrap:' in text and any(word in text for word in ('Operation not permitted','Permission denied')):
            category='explicit_bwrap_permission_error'
        else: category='other_assertion_or_wait'
        excerpts = []
        for j,line in enumerate(chunk):
            if any(token in line for token in ('bwrap:','panicked at','overflowed its stack','fatal runtime error','Snapshot Summary','Error:','timeout waiting for event','assertion failed')):
                for k in range(j,min(j+3,len(chunk))):
                    entry = {'line':start+k+1,'text':chunk[k][:900],'lineTruncated':len(chunk[k])>900}
                    if entry not in excerpts: excerpts.append(entry)
        cases.append({'binary':key[0],'test':key[1],**final,'category':category,'startLine':start+1,'endLine':end,
            'excerpts':excerpts[:15],'blockSha256':hashlib.sha256(text.encode()).hexdigest(),
            'bwrapMentionWithoutExplicitPermissionError':category=='other_assertion_or_wait' and 'bwrap' in text.lower()})
    return {'run':run,'log':str(path.relative_to(ROOT)),'logSha256':hashlib.sha256(data).hexdigest(),
        'logLines':len(lines),'summary':lines[summary].strip(),'summaryLine':summary+1,'cases':cases,'lines':lines}

new,old = parse('34192652057'),parse('34190100825')
assert len(new['cases'])==240 and len(old['cases'])==239
counts = lambda cases:dict(collections.Counter(case['category'] for case in cases))
keys = lambda report:{(case['binary'],case['test']) for case in report['cases']}
new['comparison'] = {'previousRun':old['run'],'previousSummary':old['summary'],
    'previousCategoryCountsRecounted':counts(old['cases']),
    'sameFailedOrTimedOutCases':len(keys(new)&keys(old)),
    'newFailedOrTimedOutCases':[{'binary':p,'test':t} for p,t in sorted(keys(new)-keys(old))],
    'previousFailedCasesNoLongerFailing':[{'binary':p,'test':t} for p,t in sorted(keys(old)-keys(new))],
    'previousTriage':read_json(BASE/'34190100825/failure-triage.json')['observationCounts'],
    'methodDifference':'Final TRY 2 capture only; exact bwrap colon and permission diagnostic. Prior broad counts not copied or equated with root causes.'}
new['categoryCounts'] = counts(new['cases'])
new['byPackage'] = dict(collections.Counter(case['binary'].split('::')[0] for case in new['cases']))
new['byStatus'] = dict(collections.Counter(case['status'] for case in new['cases']))
new['method'] = '240 distinct footer cases joined to their final TRY 2 block; retries/footer repeats counted once. Mutually exclusive observed-symptom categories add to240, not causal totals.'
new['otherFamilies'] = dict(collections.Counter('::'.join(case['test'].split('::')[:3]) if case['test'].startswith('suite::v2::') else '::'.join(case['test'].split('::')[:2]) for case in new['cases'] if case['category']=='other_assertion_or_wait'))
analysis = read_json(BASE/'34192652057/analysis.json')
new['selected'] = {name:{'exitCode':value.get('exitCode'),'summaries':[line for line in value.get('summaries',[]) if 'tests run:' in line or 'test run:' in line]} for name,value in analysis['stages'].items() if name!='engine-full-tests'}
new['scope'] = {'androidExecution':False,'phoneUiTested':False,'fullSuitePassed':False,
    'selectedNativeTestsPassed':analysis['selected']['success'],'fullSuiteCommit':analysis['commit'],
    'r21OrdinaryUidCodeIncluded':False,'sameEnvironmentAllFailuresClaim':False,
    'fullAggregateLogRetained':True,'rawEveryProcessOutputCompleteClaim':False,
    'note':'Some tested commands cap their own output (stderr=bwrap observed); aggregate cannot recover discarded bytes. No r21 Android execution trace exists.'}
new['observations'] = {'bwrapExecServerCases':sum(case['binary'].startswith('codex-exec-server') and case['category']=='explicit_bwrap_permission_error' for case in new['cases']),
    'tuiAbortCount':sum(case['status']=='ABRT' for case in new['cases']),
    'linkedProductV8PassLines':[i+1 for i,line in enumerate(new['lines']) if 'PASS' in line and 'linked_v8_has_sandbox_enabled' in line],
    'nextestStackSetting':new['lines'][0],
    'remainingDiskBytes':read_json(BASE/'34192652057/engine/evidence/engine-full-tests.result.json')['diskAfter']['free']}
new['categoryInterpretation'] = {
    'explicit_bwrap_permission_error': {'proven':'Explicit Linux bubblewrap permission error in final failing output, including every one of48 exec-server failures.', 'notProven':'Underlying runner policy or host kernel setting responsible; not an Android direct-runner execution.', 'impact':'Blocks these Linux sandbox tests. Does not demonstrate a missing bwrap prerequisite for the separate r21 ordinary UID executor.'},
    'stack_overflow': {'proven':'35 TUI test processes really overflowed their stack and aborted under RUST_MIN_STACK=8388608.', 'notProven':'Root code/recursion/frame cause or whether a larger test stack suffices; no such rerun occurred.', 'impact':'Real crash failures, not cosmetic. No observed Android crash can be inferred from these Linux TUI fixtures.'},
    'snapshot_difference': {'proven':'28 TUI rendered-output snapshot mismatches. Same failed cases as previous triage; version metadata and computed widths implicated by exact diffs.', 'notProven':'A correction passing all render cases; snapshots not updated.', 'impact':'Rendering/test-metadata scope rather than direct process admission.'},
    'tls_assertion': {'proven':'6 HTTP client assertions fail on certificate/protocol error classification and retry/fallback.', 'notProven':'Environment-only explanation or all real HTTP behavior defective.', 'impact':'Shared HTTP client behavior merits investigation; cannot discard as cosmetic or attribute to native executor.'},
    'v8_feature_assertion': {'proven':'POC expects false while linked sandbox is true; actual product linked_v8_has_sandbox_enabled test passes. Same feature mismatch documented in previous source review.', 'notProven':'Corrected invocation passing full suite.', 'impact':'POC/workspace feature selection consistency; not evidence that product V8 sandbox is missing.'},
    'runner_timeout_60s': {'proven':'Image-budget and feedback-upload tests terminated after about60s on both attempts.', 'notProven':'Cause of their delay or product freeze on Android.', 'impact':'Two tests unvalidated; investigate slow/blocking operations.'},
    'other_assertion_or_wait': {'proven':'66 other final assertions/waits fail; includes15 network approval cases and the newly failing rollback-budget event wait.', 'notProven':'Root cause for each case or common environmental cause. A generic bwrap startup warning is insufficient evidence.', 'impact':'Core/app-server/MCP behavior remains globally unqualified, including lifecycle, permissions and history paths.'},
}
new.pop('lines')
path = pathlib.Path(__file__).with_name('r5-failure-audit.json')
path.write_text(json.dumps(new,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
print(json.dumps({key:new[key] for key in ('categoryCounts','byPackage','byStatus','comparison','otherFamilies','observations')},indent=2))
