# Partial raster corruption: next discriminating experiment

Status: investigation, 2026-09-06. Repeated GMEM/SYSMEM comparisons now isolate
the tiled rendering path; the exact source defect and production fix remain open.
This note changes no driver, client, runtime flag, or phone setting.

## Device results: real settings clicks and GMEM discrimination

Real Android taps reproduce corruption more reliably than JavaScript `.click()`
or CDP input dispatch. At DPR 2.625 and CSS viewport 933 by 704, scrolling the
settings menu to its top and selecting General establishes Plugins at
(8,596,244.142868,30) and Browser at (8,627,244.142868,30). Tap those two rows in
that order without a capture between them. The screenshot after Browser shows
noise behind both rows. A capture between every click, or scrolling a row into
the middle of the viewport, can hide the defect. A first clean pass after a
restart is therefore insufficient. Exercising all internal settings rows and
then repeating the two taps restores the failure in otherwise clean baselines.

The user identifies Personnel as unaffected and the three subsequent groups as
affected. Twenty internal settings destinations were exercised with actual taps;
Compte is an external link and is excluded from that count. Earlier sequential
captures included noise after Importer, Plugins, Browser, Connections, Git and
Environments; those observations do not establish that every click fails or that
other destinations are immune. They also distinguish the destination clicked
from the rows where retained corruption remains visible.

Repeated comparisons in the **same live GPU process**, changing only the private
`TU_DEBUG_FILE`, now show:

| Condition | Reference clicks |
| --- | --- |
| Empty file, normal selection | Corrupt |
| `sysmem` | Clean |
| Empty file again | Corrupt |
| `3d_load` | Still corrupt |
| `unaligned_store` | Still corrupt |
| `sysmem` again | Clean |
| Empty file again, two sequences | Corrupt in both |
| `nobin`, then independently `nobinmerging` | Still corrupt |

Evidence: `downloads/gpu/runtime-toggle-gmem-evidence.json`, and the individual
`experiment-*/touch.json` and PNG files it names. The two blank interiors contain
one color under SYSMEM and more than 1,200 colors in the final normal runs.
Full images were inspected as well; these are sample counts, not whole-frame
conformance. The launcher is restored byte-for-byte after each diagnostic spawn.
The runtime file watcher does not print its debug-level notices at the default
Mesa log level; repeated reversibility is observed, not a quoted watcher log.

Additional isolated startup trials `TU_DEBUG=flushall` and `TU_DEBUG=syncdraw`
still showed corruption. `TU_DEBUG=noubwc` also fails after the complete menu
traversal and reference taps; adding `nolrz` to that still-failing condition did
not remove the noise. A clean first `ZINK_DEBUG=flushsync` sequence has **not**
yet received equivalent repeated validation and is inconclusive. Likewise,
`ZINK_DEBUG=sync TU_DEBUG=gmem` was clean on its first sequence only.

`ZINK_DEBUG=sync` ends each render pass as well as adding global barriers.
Turnip ordinarily chooses SYSMEM for passes with fewer than five draws, so the
earlier sync A/B/A cannot by itself establish a missing synchronization barrier.
The runtime `noconcurrentresolves` and `noconcurrentunresolves` trials do not
discriminate this Adreno 840: the reviewed source consults those flags only on
A7XX. No negative conclusion is drawn from them.

Khronos validation 1.4.309 was really loaded (GPU process maps checked) with
synchronization validation requested. It reported no VUID/SYNC-HAZARD, but the
instrumented frame was clean. This does not prove the uninstrumented failing
frame correct. CPU/GPU remain native ARM64/Adreno; these debug experiments are
not production settings or a substitute for correcting the source defect.

## Evidence and scope

`downloads/visual-browser-check/android-current.png` visibly contains a noisy
rectangle behind the Plugins and Browser settings rows. The coordinator also
observed the defect in the client's `Page.captureScreenshot` output and its
disappearance after opening a menu/repainting. Corruption already present in the
client capture cannot be explained solely by final Android display presentation.
It does not distinguish Chromium/ANGLE resource handling from Zink/Turnip.

`downloads/visual-browser-check/style-report.json` records these actual rows:

| Row | CSS bounds | Background |
| --- | --- | --- |
| Plugins | x=8, y=368.952392578125, width=244.1428680419922, height=30 | transparent |
| Browser | x=8, y=399.952392578125, width=244.1428680419922, height=30 | rgba(26,28,31,0.055) |

Their two inspected ancestors are transparent; no filter, backdrop filter,
transform, or blend mode is active on those inspected elements. This inspection
does not include every ancestor, pseudo-element, or nested text mask.

The successful 64-frame fixture report is
`downloads/gpu/raster-b4aa48f87ade4dfbba7fc323a64c26d5/report.json`:
4,005,716 sampled pixels, zero mismatches. Its rows have opaque backgrounds,
integer 31-pixel heights, and all selection classes are reevaluated on every
frame. This is useful evidence but leaves transparent retained contents,
fractional geometry, and small damage regions insufficiently exercised.

## First experiment: change the stimulus, retain the GPU stack

Use the existing disposable IAB fixture mechanism and the real current DPR.
Build a separate fixture variant from the recorded sidebar geometry: 30-pixel
rows, one-pixel gaps, transparent ordinary rows, the measured translucent
selection color, SVG icons, nested text-fade masks, fractional top/width, and an
unchanging opaque ancestor. Do not modify the application's CSS.

1. Establish a clean fully painted reference. Record DPR, all sample rectangles,
   computed colors, viewport, target visibility, and the exact stimulus sequence.
2. Change only the selected/hovered state of the two adjacent rows. Leave the
   remainder of the list unchanged. Capture the background interiors after
   completed animation frames, checking both changed and unchanged rows.
3. Exercise fractional scroll offsets and a fixture-owned overlay that covers
   and uncovers just those rows. This models partial invalidation/occlusion
   without opening real account content or changing client settings.
4. If noise appears, capture twice with no DOM mutation, then cause a complete
   repaint of the same fixture while restoring identical DOM, geometry, scroll,
   and style. Compare the same interior pixels with the clean reference.

A defective partial frame followed by a correct complete repaint, for identical
final DOM/style, establishes dependence on retained rendering state. It still
does not establish which layer caused it. Different noise in repeated captures
without changes instead strengthens a synchronization/lifetime hypothesis.
No reproduction means inconclusive; do not count another fixture pass as a fix.

## Second experiment only after a repeatable failing stimulus

Run a bounded A/B/A comparison in an isolated diagnostic client process, keeping
the GPU enabled and preserving the user's live process and profile. One variable
at a time; log the exact loaded libraries and inherited environment. Remove all
diagnostic flags afterwards. These are classification instruments, not repairs.

| Instrument verified in Mesa 26.2.2 source | Question |
| --- | --- |
| `ZINK_DEBUG=sync` | Does conservative Vulkan memory ordering change the failure? |
| `ZINK_DEBUG=flushsync` | Does serialized submission/presentation change it? |
| `TU_DEBUG=flushall` | Does conservative Turnip cache clean/invalidate change it? |
| `TU_DEBUG=sysmem` | Does avoiding GMEM load/store change it? |

Prefer the first instrument corresponding to the observed failure. Do not set
all flags together, and do not attribute a disappearance to that subsystem until
baseline failure returns in the final A run. A failed reproduction under every
condition cannot discriminate them. Compression/shader switches are a later
branch requiring a matching observation, not an initial blanket experiment.

## Source observations

- `src/gallium/drivers/zink/zink_screen.c:104` defines `sync`; line 112 defines
  `flushsync`; line 3416 disables the threaded-submit path for `flushsync`.
- `src/gallium/drivers/zink/zink_context.c:5131` shows a real all-command memory
  barrier under `ZINK_DEBUG_SYNC` in a transfer path. Additional guarded sites
  exist; this flag is not equivalent to disabling acceleration.
- `src/freedreno/vulkan/tu_cmd_buffer.cc:360` adds all clean/invalidate operations
  for `flushall`. The adjacent `syncdraw` path adds waits. Lines 368 onward explain
  that CCU must be cleaned before invalidation. This is existing implementation
  context, not proof that a missing barrier caused this report.
- `src/freedreno/common/freedreno_devices.py:1427` explicitly describes Adreno
  840, including tile alignment 96 by 32. Device recognition alone proves no
  rendering conformance.
- The five FoldGPT Mesa patches affect GLX/DRI3 capability discovery, WSI build
  dependencies, pixmap texture fallback, refresh-rate reporting, and calibrated
  timestamps. None directly changes Chromium raster tiles, alpha blending,
  Turnip renderpass load/store, or shader generation. Their indirect involvement
  remains testable; there is no identified patch defect from this review.

The current build explicitly uses `-Dbuild-tests=false`. Mesa's Android CI recipe
`src/freedreno/ci/deqp-tu-android.toml` documents independent Vulkan WSI, AHB,
fractioned VKCTS, and synchronization tests, but they were not executed here.
An eventual conformance followup should select retained FBO/blending,
renderpass load/store, and synchronization cases from the actual installed CTS
case list. An unrelated GPU's CI failure list is not evidence against this 840.

All source paths in this section are relative to
`downloads/gpu/src/mesa-26.2.2/`.

## Implemented fixture and coordinator command

`renderer-patterns.html` now accepts `?mode=partial`; `check-client-raster.py`
selects that mode explicitly. The original opaque exercise remains available
through the default `--mode basic`.

The coordinator, who owns ADB, can run from `C:\Dev\ChatgptFold` after opening
the disposable IAB pane visibly and obtaining its current page target ID:

```powershell
python tools/gpu/check-client-raster.py --serial R3GL808JN4A --target ACTUAL_DISPOSABLE_PAGE_TARGET --mode partial
```

The target must currently contain `about:blank` or `https://example.com/`.
The helper restores that original page in its cleanup. It does not modify the
official client's styles, profile, flags, or GPU libraries. Use the actual target
ID, not a target copied from an earlier client session.

Default partial mode performs 32 state steps and 73 captures: an initial
reference, two captures per partial state with no mutation between them, and
two captures after a fresh subtree rebuild every eight steps. The two adjacent
changing rows have indices 4 and 5. Four selection/hover combinations and four
fractional scroll requests are repeated at two integer scroll offsets; actual
scroll positions are recorded because the browser may quantize a request.
Only the two rows' classes change during a selection step. Every fourth step
also covers and uncovers those rows with a fixture-owned overlay.

The `full` phase replaces only the fixture's scene with structurally identical
fresh nodes and restores its scroll position. This invalidates the subtree's
retained layout/paint objects; it is not a claim that the complete application's
GPU surface was rerasterized. Each partial/repeat/full pair is accepted for pixel
comparison only if final serialized DOM, computed row backgrounds/text masks,
viewport, DPR, all row rectangles, scroll position, and samples are identical.
An incomparable pair makes the run inconclusive instead of becoming a GPU error.

Evidence goes to a new ignored `downloads/gpu/raster-partial-<id>/` directory:
every captured PNG, `metadata.jsonl` with fixture state and image digests,
`stderr.log`, and `report.json`. The report separates expected-color mismatches,
changes between otherwise identical captures, incomparable pairs, incomplete
runs, and partial failures that disappear after the subtree rebuild. The sample
checker rejects empty or out-of-bounds crops and mismatched viewport/DPR rather
than accepting Pillow's implicit crop padding. Text and icon pixels are outside
the sampled background interiors and are not certified by this test.

Exit codes: 0 means the complete bounded sample matrix passed; 1 means sampled
pixels were wrong or changed between comparable captures; 2 means the run or its
comparison evidence is incomplete/invalid. A pass still does not resolve the
reported application corruption.

The agent performed Python and embedded-guest syntax parsing, Node JavaScript
syntax checking, and synthetic verifier QA for capture ordering, one-pixel
corruption detection, partial/full comparison, changed-DOM refusal, out-of-bounds
refusal, and viewport mismatch refusal. Those checks are not GPU evidence. The
new partial fixture has not been run on the phone by this agent.

## Actual settings-section click diagnostic

The coordinator's partial fixture run completed 73 captures and 2,757,078
sampled pixels without a reported mismatch. That does not reproduce the user's
more specific trigger: clicking a section in the application's settings menu.

`check-settings-menu.py` now exercises that actual UI. With settings open and
Général, Plugins or Navigateur selected, the coordinator can run:

```powershell
python tools/gpu/check-settings-menu.py --serial R3GL808JN4A --target ACTUAL_MAIN_PAGE_TARGET
```

The explicit target must be the current visible `app://-/index.html` main page.
Do not use an IAB page, an avatar window or a stale target ID. Exact French
`aria-label` values and `data-settings-panel-slug` attributes restrict discovery
to the three observed section buttons; the known Plugins and Navigateur slugs
are checked. The selected Général slug is discovered from its exact section
button. No page text, account content or settings values are collected.

The default run takes three initial captures, then six cycles of real input
clicks through Plugins → Navigateur → Général, with three captures after each
click (57 captures total). It verifies live hit-testing at each click point,
does not scroll, and restores the initial section when possible. It never
modifies CSS, DOM, client files, profile flags or GPU configuration. Captures
are cropped to the sidebar rectangle spanning those three buttons; PNGs and
limited style/geometry metadata remain in ignored `downloads/gpu/settings-menu-*`.

Analysis checks blank row interiors to the right of measured text/SVG bounds.
Expected colors derive from computed transparent/translucent backgrounds over
a known opaque ancestor. Unsupported effects or an unknown native background
produce explicit inconclusive results; there is no assumed background color.
Only otherwise identical button/ancestor/descendant styles, geometry, viewport,
scroll, hover and focus permit comparison of repeats or returns to a section.
Metadata is collected immediately before and after each screenshot to reject
state changes during capture. Section content itself is outside the crop and
the analysis. Icons, glyphs and other unsampled menu pixels require visual
inspection of the retained images.

Exit 0 means only that this complete bounded sample found no anomaly; exit 1
means a color mismatch or a change between comparable blank interiors; exit 2
means incomplete, unstable, unsupported or incomparable evidence. None alone
identifies a driver defect. Static host/guest/JavaScript syntax checks and local
checker QA passed (one corrupted pixel, changed hover refusal, bad crop/empty
sample refusal and alpha composition). The subagent did not operate the phone.
