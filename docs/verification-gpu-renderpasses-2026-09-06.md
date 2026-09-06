# Settings-menu GPU correction — 2026-09-06

The selected development driver is Mesa 26.2.2 **foldgpt5**, installed in its
own `/opt/foldgpt-gpu/mesa-26.2.2-foldgpt5` prefix. The official application's
files are unchanged. Android remains unrooted; the CPU executes ARM64 natively
and the GPU uses ANGLE, Zink and Turnip on the Adreno 840.

## Defects and correction

Two independent renderpass lifetime bugs were reproduced:

1. Threaded-context playback advanced the renderpass-info pointer only after
   executing the first draw/clear of the next pass. Zink therefore consumed the
   preceding pass's resolve/invalidate metadata during that callback. The patch
   advances before that call, also covering the indirect and single vertex-state
   draw variants recorded by the same parser.
2. A partial inline resolve narrowed Zink's cached render area. A later rendering
   instance on the same framebuffer could inherit that rectangle. The patch
   restores framebuffer bounds for every new instance, before applying the
   current swapchain damage or partial-resolve rectangle.

The patches retain MSAA, GMEM, partial resolves and hardware rendering. They do
not force loads of invalidated data, select SYSMEM or add synchronization flags.
An independent source review found no blocking issue; details and extra TC
callback checks are in `tools/gpu/ZINK-RENDERPASS-REVIEW.md`.

## Independent device regression

`tools/gpu/zink-partial-resolve-probe.c` is a standalone ES3 test with RGBA8 x4
and stencil8 x4. Six scenarios repeated four times cover disjoint/overlapping
partial resolves, invalidate then draw/clear, flush splits and preservation.
Every resolved sample is defined first. Every destination RGBA8 pixel is compared
to an independent CPU expectation. The default executable refuses a renderer
without both Zink and Adreno.

| Mesa 26.2.2 candidate | Actual Fold result |
| --- | --- |
| Original foldgpt4 | Case 3 fails: 52,562 incorrect pixels |
| Render-area reset only | Same case 3 failure, despite clean menu screenshots |
| TC transition only | Case 3 passes; case 4 fails: 313,582 incorrect pixels |
| Both corrections | All 24 cases pass |
| Complete rebuilt foldgpt5 package | All 24 cases pass |

The complete package also passes the existing Adreno Vulkan submission/readback
and GLX clear/triangle pixel probes. These are bounded functional tests, not a
Vulkan conformance certification, frame-rate or battery measurement.

Run the regression after installing the development prefix:

```powershell
python tools/gpu/run-probes.py --serial R3GL808JN4A --api partial
```

## Actual application

Normal foldgpt4 reproduced black noise with real Android taps on Plugins then
Browser. The render-area candidate removed that noise; restoring foldgpt4
brought it back. The combined candidate and complete foldgpt5 package remain
visually clean in that same sequence.

After installing the rebuilt debug APK and normally starting the application,
all 20 settings sections were clicked, followed by two Plugins/Browser sequences
without an intermediate screenshot. Captures of the upper/lower menu and the
final Browser state were inspected. The selected section is checked after taps;
other-app foreground trials are rejected. Blank-interior pixel counts alone do
not certify icons, text or a solid diagnostic color.

The GPU process maps the foldgpt5 GL, Gallium and Turnip libraries. CDP reports
ANGLE on Zink/Adreno 840 with GPU composition, rasterization, OpenGL, WebGL and
WebGPU enabled. The normal client has no TU_DEBUG, TU_DEBUG_FILE or ZINK_DEBUG
selection. The official Codex executable remains SHA-256
`4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6`.

## Artifact and private evidence

Driver archive SHA-256:
`e02091631e5f16efbc3678373b2c048ebf81b10d551caf210d61b1954b7671d4`.
The collector includes the exact upstream source archive, all seven patches,
build scripts, probes, notices and ELF requirements. No OpenAI binary or account
data is included. This is a development driver, not a published FoldGPT APK.

Private evidence under `downloads/gpu/` includes:

- `partial-device-3395a1f0da8b4fbf8145ad9ffcb93033`: original and single fixes.
- `partial-device-94cbf84196354129be85e6c4b08b8981`: combined 24-case pass.
- `experiment-23226c6d18094394b54bcee0b26abb5c` and
  `experiment-fd182913072f42799656dcd2abee2933`: original library restored, noise.
- `settings-adb-c7bbee928936419c99c3fd31fa2940d1`: normal foldgpt5, 20 sections.
- `experiment-d0cb22caac8d4f4a942c9a5e326ce7ef`: final normal Browser capture.
- `verified-foldgpt5-8c2564a3809d4e73b88ad7a541f53109`: actual maps, selected
  environment and CDP GPU information.

## Remaining scope

The red `rploads` diagnostic GUI remains a separate investigation; its broad
color/depth/stencil poisoning and mutation of cached state are not neutral.
The combined independent pixel probe passes with rploads. The other flag,
rpstores, demonstrably poisons an otherwise valid resolve destination because
its synthetic clear keeps the original resolve attachment. Neither flag is
installed as a runtime fix. See the source-review note for the distinction.

These corrections resolve the reproduced normal menu corruption and the listed
defined-content regressions. They do not certify every GPU operation or eliminate
every possible dependency on undefined contents. The complete installer,
production command isolation, lifecycle and final signed APK remain separate
unfinished work.
