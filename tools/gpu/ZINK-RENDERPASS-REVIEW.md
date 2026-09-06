# Independent review of the two renderpass corrections

Reviewed 2026-09-06 against the untouched Mesa 26.2.2 source, the isolated
`9py_w2lf` Zink candidate, and `diagnostics/mesa-tc-renderpass-transition.patch`.
This review made no phone or canonical driver changes.

## Verdict

No blocking correctness issue found in either change. The corrections address
separate violations of renderpass lifetime and both are needed by the reported
Adreno probe results. Neither forces SYSMEM, adds a diagnostic load, disables
MSAA, or changes the application's rendering API.

### Reset the render area for each new rendering instance

`begin_rendering` only reaches the new reset after its two early returns for an
already compatible active renderpass. `zink_batch_no_rp` closes the old instance
before the reset. Reinitializing `(0,0,fb_width,fb_height)` at that point cannot
change a renderpass already submitted to Vulkan.

The later swapchain branch still applies the swapchain damage rectangle and its
resize limits. The later inline-resolve branch still narrows the area for the
current resolve where invalidation permits it. Thus both intended optimizations
remain. The prior rectangle could otherwise survive a split/new instance on the
same FBO, since the other full-area initialization is in set_framebuffer_state.

Surface bounds, layers and view masks are unchanged. This has the same dimension
source as the existing framebuffer-state initialization; it does not introduce
guessed geometry. Resetting layerCount as part of this change is unnecessary:
the partial-resolve branch only changes the rectangle, not that field.

### Advance TC metadata before the next draw or clear

Recording advances to the next info object before parsing the first draw after
`ended` in tc_parse_draw, or while recording that first clear in tc_clear. The
consumer must therefore make the same object visible before invoking the
corresponding driver callback. The old code advanced only after the callback.

The patch preserves the old info for the terminating resolve and intervening
invalidate/state calls. It advances once when the next draw/clear actually
arrives, then clears the pending flag. The post-call flush and framebuffer
transition branches retain their order; a flush or framebuffer change cancels
the pending draw transition, avoiding an additional increment.

The added draw_indirect and draw_vstate_single cases are appropriate: their
recording entrypoints call tc_parse_draw just like the other draw variants. Mesh
draws do not currently call tc_parse_draw, so adding them only to the consumer
switch would be incorrect; the patch correctly leaves them alone.

The change is guarded by the existing parsing switch. Queue storage, ownership,
fences, and rollover pointers are not modified. The callback harness covers all
seven draw/clear variants with/without an intervening invalidate, and the real
device probe covers ordinary draw/clear, invalidate, resolve and flush paths.
Eight extra reviewer checks of the same verbatim consumer function also passed:
pending transition cancelled by flush or framebuffer change, both initial
framebuffer modes, and parsing enabled/disabled. Private evidence is in
`/var/tmp/foldgpt-tc-review-rfs_uf2l`; surrounding pipe callbacks are mocks, not
GPU evidence.
It does not claim exhaustive coverage of every threaded-context client, mesh
draw handling, multi-layer framebuffer, or every batch-boundary schedule.

## Evidence scope

The coordinator reported the following actual Adreno/Mesa 26.2.2 outcomes:

| Candidate | Independent GLES probe | Application settings |
| --- | --- | --- |
| Baseline | Case 3 fails, 52562 pixels | Black corruption reproduced |
| Area reset only | Same case 3 failure | Visually clean in tested sequence |
| TC transition only | Case 3 passes; case 4 fails, 313582 pixels | Corruption remains |
| Both | All 24 defined-content cases pass | Tested sequence visually clean |

These results support both changes and demonstrate why application screenshots
alone were insufficient for verification. This independent reviewer did not
operate the phone; retain the coordinator's raw logs/screenshots as the primary
evidence for that table.

## Diagnostic flags: do not overinterpret them

`ZINK_DEBUG=rpstores` has a concrete side effect beyond poisoning discarded
multisample source storage. zink_batch_no_rp_safe first ends the real rendering
instance, then starts/ends a synthetic CLEAR/STORE instance using the same
VkRenderingInfo and attachments. It does not clear resolveImageView/resolveMode
until after that synthetic instance. A retained resolve therefore copies the
red poison into the independently valid single-sample destination. This explains
why even the defined-content probe can fail case 1 under this diagnostic flag.
That failure does not invalidate the two fixes. The diagnostic also mutates
cached storeOps before subsequent validity bookkeeping, so it is not a neutral
observer.

`ZINK_DEBUG=rploads` differs. It changes every DONT_CARE load to CLEAR, using
opaque red for color, depth 1 and stencil 255. It does so before renderpass
submission and changes cached attachment state; it does not inject the separate
post-pass resolve responsible for the rpstores false positive. It affects
depth/stencil as well as color, so a red result does not localize the offending
attachment or prove a Turnip cache/synchronization defect.

The reported combined+rploads probe pass is encouraging. The remaining red GUI
rectangles should nevertheless be retained as an unresolved diagnostic signal,
not dismissed by applying the rpstores explanation to them. They may indicate
remaining reads of invalidated attachment contents, application undefined
content use, or another effect of the diagnostic path. The next discriminating
experiment would poison only active color attachments, then only depth/stencil,
recording original load/store/resolve metadata and the relevant rectangles.
Poisoning a temporary attachment-info copy rather than cached attachment state
would separately test diagnostic cache persistence. No production workaround is
justified by this flag alone.

Normal-rendering regression results can justify integrating the two established
fixes while this narrower diagnostic investigation continues. Do not claim all
possible undefined-content dependencies have been eliminated based on the
normal screenshots or the 24-case probe alone.
