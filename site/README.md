# FoldGPT showcase

The public product page lives at **[julienpiron.fr/foldgpt/](https://julienpiron.fr/foldgpt/)** as part of the julienpiron.fr portfolio. This directory mirrors that page's static source so contributors can inspect and improve it alongside FoldGPT.

The mirror follows the portfolio's FoldGPT source, including the julienpiron.fr branding and social preview metadata. It removes a trailing empty line from `app.js`; executable content is unchanged.

## Contents

- `index.html`: French product page, real capture gallery, architecture explorer, and source-release links.
- `style.css`: graphite/gold visual identity, responsive layout, and accessibility styles.
- `scene.js`: WebGL handset and particle interaction, including folding, rotation, dispersion, and reassembly.
- `app.js`: gallery and accessible interface controls.
- `locale.js`: early automatic language routing: French when it is the browser's preferred language, English otherwise, without a visible selector, cookies or geolocation.
- `assets/`: the canonical application icon, three reviewed historical device captures, OpenAI's official Remote preview, and the banner export for social previews. Read [media notices](assets/MEDIA-NOTICES.md) before reusing them.

The handset is a 3D visualization using an authentic Fold capture on the inner display and OpenAI's official Remote illustration on the cover display. The Remote visual is not an Android device capture or evidence of a live connection on the Fold. Gallery screenshots are historical evidence, not a live remote session, video recording, or claim that every workflow is qualified.

## Portfolio integration

The page is served under `/foldgpt/`. Absolute asset paths deliberately target that route. The portfolio supplies `/js/locale.js` and its shared fonts under `/fonts/`; its localization process produces the English route at `/en/foldgpt/`. Both routes select the visitor's preferred browser language automatically and preserve query strings and section links. English is the fallback and the `x-default` search language.

To integrate changes, place these page files at the portfolio's `foldgpt/` route and run the portfolio's own localization, validation, and deployment workflow. This source mirror does not contain portfolio credentials, a separate hosting project, or an independent deployment pipeline. The portfolio remains the deployment source of truth.

Submit proposed improvements through the [FoldGPT contribution workflow](../CONTRIBUTING.md). Keep the mirror aligned with the production page and preserve the provenance and privacy masks of the three public captures.
