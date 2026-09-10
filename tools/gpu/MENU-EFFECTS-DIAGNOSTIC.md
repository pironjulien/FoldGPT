# Isolated menu effects fixture

This diagnostic adds a missing stimulus to the existing raster checks: a 90%
white menu, real `backdrop-filter: blur(8px)`, spread shadow, half-pixel ring,
rounded menu and rows, text masks and icons. The official client is unchanged.
It is a synthetic discriminant, not a reproduced client failure or a GPU fix.

The nonuniform dark/light strip behind the left side exercises actual blur.
Samples on the right are over an opaque uniform RGB(246,246,246) backdrop and
remain more than twelve blur standard deviations from that strip. Blur of a
constant field remains constant; menu and selection alpha composition is
calculated from computed CSS colors, independently of screenshot pixels. The
normal menu interior is approximately RGB(254,254,254); selected interiors are
approximately RGB(242,242,242). The verifier allows one channel level for
quantization. Closed-menu samples require the original opaque backdrop.

Each of four geometry variants exercises selection changes, a closed frame,
reopening, temporary occlusion, close/reopen without an intermediate capture,
fractional move/return, and backdrop mutation/return. Geometry uses the observed
259 / 260.142868 widths, 30-pixel rows with one-pixel gaps, and fractional
positions. The actual `devicePixelRatio` is recorded and used to choose strictly
interior physical pixels. A run at 2.8125 does not claim to test 2.625; reproducing
another DPR requires another actual rendering configuration, never an inferred
pass from scaling coordinates.

From the coordinator's device-owning task, with an explicit visible disposable
IAB page currently at `about:blank` or `https://example.com/`:

```powershell
python tools/gpu/check-menu-effects.py --serial <device-serial> --target CURRENT_DISPOSABLE_PAGE_ID
```

Default: 32 steps, 81 captures (initial reference, two per state, and two after
subtree replacement every four steps). Capture metadata is observed again after
the screenshot; changing viewport/DOM/styles/samples makes the run inconclusive.
A fresh-subtree reference only counts as stable and correct when its two captures
match and both pass the independent color oracle. Replacement invalidates this
fixture's layout/paint objects; it does not certify a complete GPU surface repaint.

The new harness imports only validators and the bounded guest transport from
`check-client-raster.py`. Its capture adapter asserts that the source transport
still matches the expected statement; a later transport refactor requires review.
Both source files remain separate, and importing or requesting help does not
operate the phone. The helper restores the original disposable page at cleanup.

Outputs under ignored `downloads/gpu/menu-effects-<id>/` preserve every PNG,
before/after metadata and digests, stderr, and a report. Exit 0 means the complete
bounded sample found no anomaly, 1 means incorrect or changing pixels, and 2
means incomplete/unstable evidence. A clean first capture is not a correction.

Limits: uniform strips do not certify blur transitions, shadows, antialiased
corners, glyphs or icons. Inspect full images too. The synthetic CSS only models
the observed effects, not the application's exact stacking contexts or animation
schedule. IAB and the main client can use different resource/compositor paths.
Two animation-frame waits are practical settling points, not a GPU fence proof.
No application screenshot, driver behavior or phone result is claimed from local
syntax checks.
