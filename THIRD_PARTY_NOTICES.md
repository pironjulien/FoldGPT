# Third-party notices

FoldGPT depends on independent open-source projects. The host's GPL-3.0-or-later license does not replace the licenses and notices of those components.

| Component | Source and attribution |
| --- | --- |
| Termux:X11 | Modified committed source in [`vendor/termux-x11`](vendor/termux-x11), based on revision `9df8b767645aa0d0a2f2576767449df55b41962f`; retain its [GPL v3 license](vendor/termux-x11/LICENSE) and nested notices |
| PRoot | Committed source in [`vendor/proot`](vendor/proot), based on revision `7266fb3e8516535682f5a9c8f3a7e70f6506eddb`; retain its [copyright and license notices](vendor/proot/COPYING) and source headers |
| OpenAI Codex | Native execution integration patch in [`recovery/engine`](recovery/engine), based on `rust-v0.153.4`; retain the [Apache-2.0 license](docs/licenses/codex-LICENSE) and [upstream NOTICE](docs/licenses/codex-NOTICE) |
| Apache Commons components | Installer dependencies resolved by Gradle; Apache License 2.0. Keep each artifact's LICENSE and NOTICE when preparing a binary distribution |
| Other toolchain and runtime components | Each prepared-source/build manifest identifies its own upstream inputs and licenses. Preserve those notices with its source and any separately built artifacts |

Vendored Termux:X11 includes dependency-specific licenses, including [Android shared-memory support](vendor/termux-x11/lorie/src/main/cpp/lorie/shm/LICENSE) and [bzip2](vendor/termux-x11/lorie/src/main/cpp/bzip2/LICENSE). Consult the full source trees and build manifests before packaging; this table is an entry point, not a complete binary bill of materials.

The proprietary ChatGPT desktop client is obtained separately and is not licensed or redistributed by this repository. ChatGPT and OpenAI are marks of OpenAI; Samsung, Galaxy, and Knox are marks of Samsung. FoldGPT is independent and has no endorsement or certification from either company. See [LEGAL.md](LEGAL.md) for distribution scope.
