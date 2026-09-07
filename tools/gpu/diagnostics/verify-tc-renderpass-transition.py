#!/usr/bin/env python3
"""Compile the candidate and exercise the real batch_execute with fake pipe callbacks.

Run in WSL. Never edits the working Mesa tree or links/deploys a driver.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--repo', type=Path, required=True)
args = parser.parse_args()
repo = args.repo.resolve()
source = repo / 'downloads/gpu/src/mesa-26.2.2'
build = repo / 'downloads/gpu/build-26.2.2'
relative = Path('src/gallium/auxiliary/util/u_threaded_context.c')
original = source / relative
before = hashlib.sha256(original.read_bytes()).hexdigest()
stage = Path(tempfile.mkdtemp(prefix='foldgpt-tc-transition-', dir='/var/tmp'))
candidate = stage / relative
candidate.parent.mkdir(parents=True)
candidate.write_bytes(original.read_bytes())
with (repo / 'tools/gpu/diagnostics/mesa-tc-renderpass-transition.patch').open('rb') as patch:
    subprocess.run(['patch', '--fuzz=0', '-p1', '-d', str(stage)], stdin=patch, check=True)

commands = json.loads((build / 'compile_commands.json').read_text())
cmd = shlex.split(next(c for c in commands if c['file'].endswith('/u_threaded_context.c'))['command'])
filtered = []
i = 0
while i < len(cmd):
    if cmd[i] in ('-o', '-MQ', '-MF'):
        i += 2
        continue
    if cmd[i] in ('-c', '-MD') or cmd[i].endswith('/u_threaded_context.c'):
        i += 1
        continue
    filtered.append(cmd[i])
    i += 1
filtered[1:1] = ['-I' + str(original.parent)]
filtered += ['-fsyntax-only', str(candidate)]
syntax = subprocess.run(filtered, cwd=build, capture_output=True, text=True)
(stage / 'arm64-syntax.log').write_text(syntax.stdout + syntax.stderr)
print('ARM64 source syntax', syntax.returncode, flush=True)

# Extract production batch_execute verbatim. Only its surrounding Mesa types,
# queue/callback implementation and fence lookup are replaced with small fakes.
def batch_body(text):
    start = text.index('ALWAYS_INLINE static void\nbatch_execute(')
    end = text.index('\nstatic void\ntc_batch_execute(', start)
    return text[start:end]

call_header = (original.parent / 'u_threaded_context_calls.h').read_text()
(stage / 'u_threaded_context_calls.h').write_text(call_header)
names = re.findall(r'^CALL\((\w+)\)', call_header, re.M)
prefix = '''#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
#define ALWAYS_INLINE
#define TC_DEBUG 0
#define TC_TRACE_SCOPE(x)
#define tc_assert(x) assert(x)
#define TC_SENTINEL 51
enum { TC_END_BATCH,
'''
prefix += '\n'.join('TC_CALL_' + name + ',' for name in names) + '\n};\n'
prefix += '''
struct tc_call_base { uint16_t call_id, sentinel; int32_t expected_info; };
struct tc_renderpass_info { unsigned number; };
struct tc_batch_rp_info { struct tc_renderpass_info info; void *end_call; };
struct threaded_context { struct tc_renderpass_info *renderpass_info; };
struct tc_batch { bool increment_rp_info_on_fb; uint64_t *slots; struct threaded_context *tc; };
struct pipe_context { struct threaded_context *tc; unsigned errors, callbacks; };
static struct tc_batch_rp_info *tc_batch_rp_info(struct tc_renderpass_info *info) {
   return (struct tc_batch_rp_info *)info;
}
static struct tc_renderpass_info *incr_rp_info(struct tc_renderpass_info *info) {
   return &((struct tc_batch_rp_info *)info)[1].info;
}
static uint16_t callback(struct pipe_context *pipe, void *ptr, const char *name) {
   struct tc_call_base *call = ptr;
   ++pipe->callbacks;
   if (call->expected_info >= 0 && pipe->tc->renderpass_info->number != (unsigned)call->expected_info) {
      fprintf(stderr, "%s observed pass %u; expected %d\\n", name,
         pipe->tc->renderpass_info->number, call->expected_info);
      ++pipe->errors;
   }
   return 1;
}
'''
prefix += '\n'.join(f'static uint16_t tc_call_{name}(struct pipe_context *p, void *c) '
    f'{{ return callback(p,c,"{name}"); }}' for name in names) + '\n'
suffix = '''
static unsigned run(unsigned first, bool with_intervening_invalidate) {
   struct tc_call_base calls[8];
   unsigned count = 0;
   calls[count++] = (struct tc_call_base){TC_CALL_resolve, TC_SENTINEL, 0};
   if (with_intervening_invalidate)
      calls[count++] = (struct tc_call_base){TC_CALL_invalidate_resource, TC_SENTINEL, 0};
   calls[count++] = (struct tc_call_base){first, TC_SENTINEL, 1};
   calls[count++] = (struct tc_call_base){TC_CALL_draw_single, TC_SENTINEL, 1};
   unsigned second_resolve = count;
   calls[count++] = (struct tc_call_base){TC_CALL_resolve, TC_SENTINEL, 1};
   calls[count++] = (struct tc_call_base){TC_CALL_clear, TC_SENTINEL, 2};
   calls[count++] = (struct tc_call_base){TC_CALL_draw_single, TC_SENTINEL, 2};
   calls[count++] = (struct tc_call_base){TC_END_BATCH, TC_SENTINEL, -1};
   struct tc_batch_rp_info infos[3] = {{{0}, &calls[0]}, {{1}, &calls[second_resolve]}, {{2}, NULL}};
   struct threaded_context tc = {&infos[0].info};
   struct pipe_context pipe = {&tc,0,0};
   struct tc_batch batch = {false, (uint64_t *)calls, &tc};
   batch_execute(&batch, &pipe, true);
   assert(pipe.callbacks == count - 1);
   return pipe.errors;
}
int main(void) {
   unsigned variants[] = {TC_CALL_clear, TC_CALL_draw_single, TC_CALL_draw_multi,
      TC_CALL_draw_single_drawid, TC_CALL_draw_indirect, TC_CALL_draw_vstate_single,
      TC_CALL_draw_vstate_multi};
   unsigned errors = 0;
   for (unsigned i = 0; i < sizeof(variants)/sizeof(variants[0]); ++i) {
      errors += run(variants[i], false);
      errors += run(variants[i], true);
   }
   printf("14 callback transition cases; metadata mismatches: %u\\n", errors);
   return errors != 0;
}
'''
results = {}
for label, text in [('baseline', original.read_text()), ('candidate', candidate.read_text())]:
    fixture = stage / (label + '-callbacks.c')
    fixture.write_text(prefix + batch_body(text) + suffix)
    binary = stage / (label + '-callbacks')
    subprocess.run(['cc', '-std=c11', '-O0', '-I', str(stage), str(fixture), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], capture_output=True, text=True)
    (stage / (label + '-callbacks.log')).write_text(result.stdout + result.stderr)
    results[label] = {'exitCode': result.returncode, 'stdout': result.stdout}
    print(label, result.stdout.strip(), flush=True)

after = hashlib.sha256(original.read_bytes()).hexdigest()
report = {'stage': str(stage), 'arm64SyntaxExitCode': syntax.returncode,
    'callbackChecks': results, 'sourceBefore': before, 'sourceAfter': after,
    'sourceUnchanged': before == after,
    'note': 'Real batch_execute, mocked callback/fence/queue surroundings; no driver link or device test.'}
(stage / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps(report), flush=True)
raise SystemExit(not (syntax.returncode == 0 and results['baseline']['exitCode'] != 0
    and results['candidate']['exitCode'] == 0 and before == after))
