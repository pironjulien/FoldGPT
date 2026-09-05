# Licensing and attribution

FoldGPT is an independent interoperability experiment. ChatGPT and OpenAI are marks of OpenAI; Samsung, Galaxy and Knox are marks of Samsung. This project is not endorsed or certified by either company.

## Source and dependencies

The FoldGPT wrapper code is offered under GPL-3.0-or-later. Termux:X11 and PRoot retain their upstream licenses and copyright notices. Other runtime dependencies, including talloc and Android shared-memory support, have their own license terms.

The `vendor/termux-x11` and `vendor/proot` submodules pin upstream source. Preserve their notices and nested source dependencies. PRoot and its matching loaders have been compiled from the pinned source for the integrated prototype. The development build still collects other native libraries from installed official packages.

| Source component | Pinned revision | Upstream license |
| --- | --- | --- |
| [Termux:X11](https://github.com/termux/termux-x11) | `9df8b767645aa0d0a2f2576767449df55b41962f` | GPL v3, with dependency-specific notices |
| [PRoot](https://github.com/termux/proot) | `7266fb3e8516535682f5a9c8f3a7e70f6506eddb` | GPL v2 or later; see its source headers and `COPYING` |

This publication distributes source, without APKs, runtime libraries or Linux images. A future binary release must inventory dependencies and provide corresponding source and notices as required by their licenses. Collected binary hashes and a general GPL notice alone do not establish reproducibility or complete compliance.

## Proprietary client and private data

OpenAI's application is not licensed by this repository. Users must obtain it from the official source under the applicable OpenAI terms. This project does not grant redistribution rights to OpenAI binaries, icons or other assets. Account data, proprietary installers and preconfigured Linux images are excluded from the source publication and must remain outside future releases.

The experimental shim leaves packaged OpenAI files unchanged but modifies behavior at runtime, including sandbox checks. It does not provide equivalent Linux namespace isolation. The keyboard bridge also attaches through the client's local debugger and installs DOM event listeners.

## Limits of this notice

This document is an attribution and distribution policy, not a legal clearance. Interoperability exceptions depend on jurisdiction and facts; this project has not obtained a legal determination that all proposed distribution or reverse-engineering activities qualify.

Observed bootloader, verified-boot, SELinux and Knox states are recorded in [PUBLICATION.md](PUBLICATION.md). They do not guarantee Samsung Care+, payment-app compatibility, future firmware behavior, OpenAI update compatibility or suitability for sensitive data.
