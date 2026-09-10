# FoldGPT GMEM metadata diagnostic

This is an isolated diagnostic for the Mesa 26.2.2 foldgpt4 source. It preserves
normal GPU rendering. It is not a visual-corruption correction and must not be
left in the production driver as a substitute for one.

The generated patch adds a bounded 8192-event memory ring and two runtime options
to the existing `TU_DEBUG_FILE` watcher. It records command-construction metadata,
not pixels, clear values, resource contents, descriptors, shaders or GPU virtual
addresses. CPU object addresses are only used as process-local correlation IDs.
There is no event-by-event file I/O. Contended groups are dropped rather than
blocking rendering; the dump reports both dropped and overwritten records.

## Generate and verify without changing production source

From `C:\Dev\FoldGPT`:

```powershell
python tools/gpu/diagnostics/make-gmem-metadata-patch.py --mesa downloads/gpu/src/mesa-26.2.2 --output tools/gpu/diagnostics/mesa-gmem-metadata.patch
wsl -d Ubuntu-24.04 -- python3 /mnt/c/Dev/FoldGPT/tools/gpu/diagnostics/verify-gmem-metadata.py --repo /mnt/c/Dev/FoldGPT
```

The verifier copies the Vulkan source directory into an isolated `/var/tmp`
overlay, applies all five patch files with `--fuzz=0`, then checks the three
modified C++ units with the existing ARM64 compile arguments and `-fsyntax-only`.
It records the command logs, exit codes, and before/after SHA256 hashes of the
production inputs. This verifies compilation syntax, not a complete link or
device behavior. Build and deploy an isolated diagnostic library separately;
do not apply this patch to the working production source or modify the canonical
build scripts for this experiment.

## Capture

1. Start the diagnostic library with the existing absolute `TU_DEBUG_FILE` path
   and a new, private, absolute Linux `FOLDGPT_GMEM_TRACE_PATH`, such as
   `/tmp/foldgpt-gmem-capture-unique.ndjson`. Keep diagnostic names out of the
   startup `TU_DEBUG`: startup flags cannot be disabled by the runtime file.
2. Warm up the ordinary full settings traversal. Confirm the baseline corruption
   before enabling capture; an initially clean frame is not sufficient evidence.
3. Write `gmemtrace` to `TU_DEBUG_FILE` using the existing runtime-toggle helper.
   After the watcher applies it, run the short tactile Plugins -> Navigateur
   sequence and save the matching CDP screenshot separately. Optional same-process
   phases can use `sysmem,gmemtrace` then `gmemtrace`; the actual render mode is
   recorded per pass. These flags are diagnostic discriminators only.
4. Replace the runtime file with `gmemdump`, removing `gmemtrace` and preserving
   only any intended unrelated flags. The watcher stops capture and writes the
   ring after taking its lock. The output is created once, mode 0600, with
   `O_EXCL|O_NOFOLLOW`; an existing path is refused. Check the driver log for
   `metadata dump complete` and copy the dump out.
5. Restore the previous runtime file contents and the normal library after the
   experiment. A fresh process and output path provide a fresh ring for another
   capture. Neither debug option is a permanent fix.

To decode locally:

```powershell
python tools/gpu/diagnostics/decode-gmem-metadata.py downloads/gpu/capture.ndjson --decoded downloads/gpu/capture-decoded.ndjson
```

The decoder refuses malformed field counts, nonconsecutive sequence numbers,
truncated dumps, and an existing decoded-output path. It prints a compact
summary. Numeric Vulkan formats are kept as numeric values for exactness.

## Event schema and limitations

`decode-gmem-metadata.py:SCHEMA` is the authoritative ordered field-name mapping
for every `v` array. Each raw event has `seq`, `kind`, `v`. The dump header records
the schema, capacity, total events, overwritten count and dropped lock groups.

| Kind | Event | Meaning |
| --- | --- | --- |
| 0 | invalid_state | Command metadata unavailable; reason 1 means missing pass, framebuffer or tiling |
| 1 | render_pass | Completed command construction: actual GMEM/SYSMEM selection, binning, draw count, tiling and pass flags |
| 2 | render_area | Rectangle for the pass whose sequence number is `pass_id` |
| 3 | attachment | Format, samples, clear/load/store bits, both GMEM layouts, view extent, UBWC and object IDs |
| 4 | subpass | Counts, samples, input/resolve/feedback/depth/stencil flags |
| 5 | clear | Explicit `CmdClearAttachments` invocation, command ID, flags and counts |
| 6 | clear_attachment | Aspect mask and color slot for the invocation at `clear_id` |
| 7 | clear_rect | Explicit clear rectangle and layers for `clear_id` |

Clear calls precede the pass summary in command-construction order. Correlate
them through `cmd` and the next pass-summary event for that command; dropped or
overwritten groups can prevent a complete association. Clear-attachment color
indices address subpass color slots, not necessarily pass attachment indices.
Dynamic render passes may be reconstructed between commands. The ring does not
record queue submit IDs or prove GPU completion. Debug flags are read at record
time; the explicit `sysmem` and `binning` fields carry the actual selected path.

Up to 32 per-view render areas are captured. Event groups stay together while
recorded, but ring wrap can remove their leading members. A capture starting in
the middle of a pass can include its summary without the preceding clears.
The hook records pass and clear intent; it does not yet trace individual tile
load/store packet choices. Use a short capture to keep `overwritten` and
`dropped_lock_groups` at zero. Timing perturbation remains possible despite
bounded memory recording, so retain matched baseline and A/B/A screenshots.
