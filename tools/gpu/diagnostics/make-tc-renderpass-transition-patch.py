#!/usr/bin/env python3
"""Generate a bounded candidate patch without editing production Mesa source."""
import argparse
import difflib
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--mesa', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
name = 'src/gallium/auxiliary/util/u_threaded_context.c'
original = (args.mesa / name).read_text()
old = '''         } else if (increment_rp_info_on_draw_clear) {
            switch (call->call_id) {
            case TC_CALL_clear:
            case TC_CALL_draw_single:
            case TC_CALL_draw_multi:
            case TC_CALL_draw_single_drawid:
            case TC_CALL_draw_vstate_multi:
               batch->tc->renderpass_info = incr_rp_info(batch->tc->renderpass_info);
               increment_rp_info_on_draw_clear = false;
               break;
            default:
               break;
            }
'''
assert original.count(old) == 1
changed = original.replace(old, '')
anchor = '''      TC_TRACE_SCOPE(call->call_id);

      /* This executes the call using a switch. */'''
replacement = '''      TC_TRACE_SCOPE(call->call_id);

      /* Match tc_parse_draw()/tc_clear(): the first draw or clear after a
       * terminating operation already belongs to the next render pass.
       * Drivers may query this metadata while executing that very call.
       */
      if (parsing && increment_rp_info_on_draw_clear) {
         switch (call->call_id) {
         case TC_CALL_clear:
         case TC_CALL_draw_single:
         case TC_CALL_draw_multi:
         case TC_CALL_draw_single_drawid:
         case TC_CALL_draw_indirect:
         case TC_CALL_draw_vstate_single:
         case TC_CALL_draw_vstate_multi:
            batch->tc->renderpass_info = incr_rp_info(batch->tc->renderpass_info);
            increment_rp_info_on_draw_clear = false;
            break;
         default:
            break;
         }
      }

      /* This executes the call using a switch. */'''
assert changed.count(anchor) == 1
changed = changed.replace(anchor, replacement)
patch = ''.join(difflib.unified_diff(original.splitlines(keepends=True),
    changed.splitlines(keepends=True), fromfile='a/' + name, tofile='b/' + name))
args.output.write_text(patch, newline='\n')
print(f'Wrote {args.output}; production source untouched')
