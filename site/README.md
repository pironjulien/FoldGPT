# FoldGPT showcase

The public product page lives at **[julienpiron.fr/foldgpt/](https://julienpiron.fr/foldgpt/)** as part of Julien Piron's portfolio. This directory mirrors that page's static source so contributors can inspect and improve it alongside FoldGPT.

Source snapshot: portfolio commit `08771fde096ce710afdd798b37d795a583e3a975`. The mirror removes a trailing empty line from `app.js`; executable content is unchanged.

## Contents

- `index.html`: French product page, real capture gallery, architecture explorer, and source-release links.
- `style.css`: graphite/gold visual identity, responsive layout, and accessibility styles.
- `scene.js`: WebGL handset and particle interaction, including folding, rotation, dispersion, and reassembly.
- `app.js`: gallery and accessible interface controls.
- `assets/`: the canonical application icon and three reviewed historical device captures. Read [media notices](assets/MEDIA-NOTICES.md) before reusing them.

The handset is a 3D visualization using an authentic capture as its screen texture. Gallery screenshots are historical evidence, not a live remote session, video recording, or claim that every workflow is qualified.

## Portfolio integration

The page is served under `/foldgpt/`. Absolute asset paths deliberately target that route. The portfolio supplies `/js/locale.js` and its shared fonts under `/fonts/`; its localization process produces the English route at `/en/foldgpt/`.

To integrate changes, place these page files at the portfolio's `foldgpt/` route and run the portfolio's own localization, validation, and deployment workflow. This source mirror does not contain portfolio credentials, a separate hosting project, or an independent deployment pipeline. The portfolio remains the deployment source of truth.

Submit proposed improvements through the [FoldGPT contribution workflow](../CONTRIBUTING.md). Keep the mirror aligned with the production page and preserve the provenance and privacy masks of the three public captures.
