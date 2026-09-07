#!/usr/bin/env python3
"""Validate and decode FoldGPT's bounded GMEM metadata ring (no pixels)."""
import argparse
from collections import Counter
import json
from pathlib import Path

SCHEMA = {
    0: ('invalid_state', 'cmd reason'),
    1: ('render_pass', 'cmd debug_flags sysmem binning concurrent_binning_disabled draw_count '
        'attachment_count user_attachment_count subpass_count gmem_layout gmem_layout_divisor '
        'fb_width fb_height fb_layers tile_width tile_height tile_count_x tile_count_y '
        'has_msrtss has_fdm allow_ib2_skipping has_cond_load_store render_area_count '
        'gmem_pixels_layout_0 gmem_pixels_layout_1 fdm_enabled fdm_subsampled '
        'flush_bits pending_flush_bits'),
    2: ('render_area', 'pass_id index x y width height'),
    3: ('attachment', 'pass_id index format samples cpp clear_mask load store load_stencil '
        'store_stencil gmem gmem_offset_0 gmem_offset_1 gmem_stencil_offset_0 '
        'gmem_stencil_offset_1 will_be_resolved first_subpass last_subpass cond_load_allowed '
        'cond_store_allowed user_attachment remapped_clear_attachment image_view image '
        'view_width view_height view_depth ubwc_enabled mutable used_views resolve_views'),
    4: ('subpass', 'pass_id index samples color_count input_count resolve_count unresolve_count '
        'depth_stencil_attachment depth_used stencil_used multiview_mask feedback_loop_color '
        'feedback_loop_ds raster_order_attachment_access custom_resolve'),
    5: ('clear', 'cmd debug_flags attachment_count rect_count subpass_index'),
    6: ('clear_attachment', 'clear_id index aspect_mask color_attachment'),
    7: ('clear_rect', 'clear_id index x y width height base_array_layer layer_count'),
}
SCHEMA = {kind: (name, fields.split()) for kind, (name, fields) in SCHEMA.items()}


def decode(path):
    with path.open(encoding='utf-8') as stream:
        header = json.loads(next(stream))
        if header.get('schema') != 'foldgpt-gmem-metadata-v1':
            raise ValueError('Unsupported metadata schema')
        events = []
        previous = header['overwritten'] - 1
        for line_no, line in enumerate(stream, 2):
            event = json.loads(line)
            name, fields = SCHEMA[event['kind']]
            if len(event['v']) != len(fields):
                raise ValueError(f'Line {line_no}: {name} field count mismatch')
            if event['seq'] != previous + 1:
                raise ValueError(f'Line {line_no}: nonconsecutive event sequence')
            if not all(type(value) is int for value in event['v']):
                raise ValueError(f'Line {line_no}: noninteger metadata')
            previous = event['seq']
            events.append({'seq': event['seq'], 'event': name, **dict(zip(fields, event['v']))})
        if len(events) != header['total'] - header['overwritten']:
            raise ValueError('Truncated metadata dump')
        if len(events) > header['capacity']:
            raise ValueError('Dump exceeds bounded ring capacity')
    return header, events


def summarize(header, events):
    counts = Counter(event['event'] for event in events)
    passes = [event for event in events if event['event'] == 'render_pass']
    attachments = [event for event in events if event['event'] == 'attachment']
    rects = [event for event in events if event['event'] == 'clear_rect']
    # Counts describe recorded command construction, not confirmed GPU execution.
    return {
        'header': header,
        'counts': dict(counts),
        'render_modes': dict(Counter('sysmem' if event['sysmem'] else 'gmem' for event in passes)),
        'gmem_binning_modes': dict(Counter('binning' if event['binning'] else 'no_binning'
            for event in passes if not event['sysmem'])),
        'framebuffer_sizes': dict(Counter(f"{event['fb_width']}x{event['fb_height']}x{event['fb_layers']}"
            for event in passes)),
        'attachment_formats_samples': dict(Counter(f"VkFormat={event['format']},samples={event['samples']}"
            for event in attachments)),
        'attachments_with_loadop_clear': sum(bool(event['clear_mask']) for event in attachments),
        'explicit_clear_rectangles': len(rects),
        'nonpositive_clear_rectangles': [event['seq'] for event in rects
            if event['width'] <= 0 or event['height'] <= 0 or event['layer_count'] <= 0],
        'negative_clear_offsets': [event['seq'] for event in rects if event['x'] < 0 or event['y'] < 0],
        'capture_complete': header['overwritten'] == 0 and header['dropped_lock_groups'] == 0,
        'note': 'Command metadata only; this capture does not identify corrupt pixels or prove GPU completion.',
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('trace', type=Path)
    parser.add_argument('--decoded', type=Path, help='Optional named-field NDJSON output')
    args = parser.parse_args()
    header, events = decode(args.trace)
    if args.decoded:
        with args.decoded.open('x', encoding='utf-8', newline='\n') as out:
            for event in events:
                out.write(json.dumps(event, separators=(',', ':')) + '\n')
    print(json.dumps(summarize(header, events), indent=2))


if __name__ == '__main__':
    main()
