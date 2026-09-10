#!/usr/bin/env python3
"""Generate an isolated diagnostic patch; never edits the Mesa source tree."""
import argparse
import difflib
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mesa', required=True, type=Path)
parser.add_argument('--output', required=True, type=Path)
args = parser.parse_args()
changes = {}


def replace(path, before, after):
    text = changes.get(path, (args.mesa / path).read_text())
    if text.count(before) != 1:
        raise SystemExit(f'Expected exactly one source anchor in {path}: {before[:80]!r}')
    changes[path] = text.replace(before, after)


root = 'src/freedreno/vulkan/'
replace(root + 'tu_util.h', '   TU_DEBUG_COMPUTE_ROUND_ROBIN      = BITFIELD64_BIT(37),',
        '   TU_DEBUG_COMPUTE_ROUND_ROBIN      = BITFIELD64_BIT(37),\n'
        '   TU_DEBUG_FOLDGPT_GMEM_TRACE      = BITFIELD64_BIT(38),\n'
        '   TU_DEBUG_FOLDGPT_GMEM_DUMP       = BITFIELD64_BIT(39),')
replace(root + 'tu_util.h', 'extern struct tu_env tu_env;',
        'extern struct tu_env tu_env;\n\n'
        'void tu_foldgpt_dump_gmem_trace(void);\n'
        'void tu_foldgpt_trace_clear(struct tu_cmd_buffer *cmd, uint32_t attachment_count,\n'
        '                          const VkClearAttachment *attachments,\n'
        '                          uint32_t rect_count, const VkClearRect *rects);')
replace(root + 'tu_util.cc', '   { "computeroundrobin", TU_DEBUG_COMPUTE_ROUND_ROBIN },',
        '   { "computeroundrobin", TU_DEBUG_COMPUTE_ROUND_ROBIN },\n'
        '   { "gmemtrace", TU_DEBUG_FOLDGPT_GMEM_TRACE },\n'
        '   { "gmemdump", TU_DEBUG_FOLDGPT_GMEM_DUMP },')
replace(root + 'tu_util.cc', '   TU_DEBUG_NO_BIN_MERGING;',
        '   TU_DEBUG_NO_BIN_MERGING |\n'
        '   TU_DEBUG_FOLDGPT_GMEM_TRACE | TU_DEBUG_FOLDGPT_GMEM_DUMP;')
replace(root + 'tu_util.cc', '   tu_env.debug.store(runtime_flags | tu_env.start_debug, std::memory_order_release);',
        '   uint64_t old_flags = tu_env.debug.load(std::memory_order_acquire);\n'
        '   tu_env.debug.store(runtime_flags | tu_env.start_debug, std::memory_order_release);\n'
        '   if ((runtime_flags & TU_DEBUG_FOLDGPT_GMEM_DUMP) &&\n'
        '       !(old_flags & TU_DEBUG_FOLDGPT_GMEM_DUMP))\n'
        '      tu_foldgpt_dump_gmem_trace();')
replace(root + 'tu_cmd_buffer.cc', '#include "tu_trace_bin_layout.h"',
        '#include "tu_trace_bin_layout.h"\n#include "tu_foldgpt_gmem_trace.h"')
replace(root + 'tu_cmd_buffer.cc',
        '   if (use_sysmem_rendering(cmd_buffer, &rp_ctx, rp_key))\n'
        '      tu_cmd_render_sysmem<CHIP>(cmd_buffer, rp_ctx);\n'
        '   else\n'
        '      tu_cmd_render_tiles<CHIP>(cmd_buffer, rp_ctx, fdm_offsets);',
        '   bool sysmem = use_sysmem_rendering(cmd_buffer, &rp_ctx, rp_key);\n'
        '   bool binning = !sysmem && use_hw_binning(cmd_buffer);\n'
        '   if (sysmem)\n'
        '      tu_cmd_render_sysmem<CHIP>(cmd_buffer, rp_ctx);\n'
        '   else\n'
        '      tu_cmd_render_tiles<CHIP>(cmd_buffer, rp_ctx, fdm_offsets);\n'
        '   fg_trace_render_pass(cmd_buffer, sysmem, binning);')
clear = (args.mesa / (root + 'tu_clear_blit.cc')).read_text()
start = clear.index('tu_CmdClearAttachments(')
anchor = '   VK_FROM_HANDLE(tu_cmd_buffer, cmd, commandBuffer);'
idx = clear.index(anchor, start)
clear = clear[:idx] + clear[idx:].replace(anchor,
    anchor + '\n\n   tu_foldgpt_trace_clear(cmd, attachmentCount, pAttachments, rectCount, pRects);', 1)
changes[root + 'tu_clear_blit.cc'] = clear
changes[root + 'tu_foldgpt_gmem_trace.h'] = Path(__file__).with_name('tu_foldgpt_gmem_trace.h').read_text()
patch = []
for name, changed in changes.items():
    source = args.mesa / name
    original = source.read_text() if source.exists() else ''
    patch.extend(difflib.unified_diff(original.splitlines(keepends=True),
        changed.splitlines(keepends=True), fromfile='a/' + name if source.exists() else '/dev/null',
        tofile='b/' + name))
args.output.write_text(''.join(patch), newline='\n')
print(f'Wrote {args.output}; {len(changes)} files in diagnostic patch; source tree untouched')
