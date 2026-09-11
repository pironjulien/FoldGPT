# Licensing and attribution

FoldGPT is an independent interoperability experiment. ChatGPT and OpenAI are marks of OpenAI; Samsung, Galaxy and Knox are marks of Samsung. This project is not endorsed or certified by either company.

## Source and dependencies

The FoldGPT wrapper code is offered under GPL-3.0-or-later. Termux:X11 and PRoot retain their upstream licenses and copyright notices. Other runtime dependencies, including talloc and Android shared-memory support, have their own license terms.

The `vendor/termux-x11` and `vendor/proot` directories contain committed source snapshots, not Git submodules. Their upstream bases are recorded below. The Termux:X11 tree already includes FoldGPT integration changes; do not apply a recovery patch a second time. Preserve upstream notices and the licenses of nested dependencies when modifying or redistributing these trees. The development build still collects some native libraries from separately obtained packages; this source release is not a complete binary distribution.

| Source component | Pinned revision | Upstream license |
| --- | --- | --- |
| [Termux:X11](https://github.com/termux/termux-x11) | `9df8b767645aa0d0a2f2576767449df55b41962f` | GPL v3, with dependency-specific notices |
| [PRoot](https://github.com/termux/proot) | `7266fb3e8516535682f5a9c8f3a7e70f6506eddb` | GPL v2 or later; see its source headers and `COPYING` |
| [Codex](https://github.com/openai/codex) native execution integration | `rust-v0.153.4`, base `3d2ee51ca2d5db578f328aa75e20aa22c0197c9a` | Apache License 2.0; preserve the upstream LICENSE and NOTICE with rebuilt source or binary distributions |
| Apache Commons Compress (installer), with Commons IO/Codec/Lang dependencies | `1.28.0`; see Gradle dependency resolution and pinned host-test inputs | Apache License 2.0; retain component LICENSE/NOTICE files for binary distribution |

The Codex integration is distributed as a source patch in [`recovery/engine`](recovery/engine), with the upstream revision and patch checksum in its manifest. It is based on the open-source Codex project, copyright OpenAI, and remains subject to its [Apache-2.0 license](docs/licenses/codex-LICENSE) and [upstream notice](docs/licenses/codex-NOTICE). These two files are retained from the recorded base revision. The source restoration tool obtains that upstream tree separately. This attribution does not apply the repository's GPL license to upstream Codex code or grant rights to the proprietary desktop client.

This publication distributes source, without APKs, runtime libraries or Linux images. A future binary release must inventory dependencies and provide corresponding source and notices as required by their licenses. Collected binary hashes and a general GPL notice alone do not establish reproducibility or complete compliance.

## Proprietary client and private data

OpenAI's application is not licensed by this repository. Users must obtain it from the official source under the applicable OpenAI terms. This project does not grant redistribution rights to OpenAI binaries, icons or other assets. Account data, proprietary installers and preconfigured Linux images are excluded from the source publication and must remain outside future releases.

The integration includes a compatibility shim that changes runtime behavior, including sandbox checks, and a version-specific workspace adapter that modifies a limited ASAR integration point. The currently recognized client version is `26.901.41600`; the adaptation flow retains the original archive and rejects unknown versions. The resulting installation must not be described as an unmodified client or as compatible with arbitrary future client updates.

These adaptations do not provide equivalent Linux namespace isolation. The keyboard bridge also attaches through the client's local debugger and installs DOM event listeners. See the [architecture](docs/architecture.md) and [security policy](SECURITY.md) for the execution and trust boundaries.

## Limits of this notice

This document is an attribution and distribution policy, not a legal clearance. Interoperability exceptions depend on jurisdiction and facts; this project has not obtained a legal determination that all proposed distribution or reverse-engineering activities qualify.

Observed bootloader, verified-boot and Knox states are summarized in the [compatibility matrix](docs/compatibility.md). They do not guarantee Samsung Care+, payment-app compatibility, future firmware behavior, OpenAI update compatibility or suitability for sensitive data.
