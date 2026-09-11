# Publication scope

`v0.2.0-alpha.1` publishes the FoldGPT Android host, runtime integration, build and verification tools, dependency provenance, and product documentation. It is a source preview for contributors.

Start with the [product overview](docs/overview.md), [architecture](docs/architecture.md), and [contribution guide](CONTRIBUTING.md). The [compatibility matrix](docs/compatibility.md) distinguishes exercised workflows from open qualification work. Dated device reports describe only their recorded setups.

The source includes modified open-source dependencies and a version-specific compatibility integration. The proprietary desktop client must be acquired separately from OpenAI. Generated runtime libraries, native executor packages, consumer APKs, and preconfigured Linux images are not release assets. Build prerequisites and separate inputs are documented in the [build guide](docs/build.md); this release does not establish a clean-device installation path.

Fresh installation, updates, Remote, prolonged background/fold cycles, simultaneous active conversations, and broader tool isolation remain qualification milestones. The shared Android phantom-process budget still applies. Ordinary additional APKs do not create separate budgets. See the [roadmap](docs/roadmap.md) for completion criteria.

Publication excludes credentials, account and browser profiles, proprietary client assets, private logs, device serials, and encrypted recovery archives. Keep dependency notices and corresponding-source obligations intact; see [LEGAL.md](LEGAL.md) and [third-party notices](THIRD_PARTY_NOTICES.md).
