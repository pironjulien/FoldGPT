# Explore FoldGPT

FoldGPT brings a desktop ChatGPT and Codex workspace to the inner screen of a Galaxy Z Fold. Start with the product, then explore how the Android host makes it possible.

Visit the [FoldGPT showcase on julienpiron.fr](https://julienpiron.fr/foldgpt/) for the interactive handset, authentic development-device captures, and a visual explanation of the architecture.

| Guide | What you will find |
| --- | --- |
| [Product overview](overview.md) | The experience, practical uses, and scope of the source release |
| [Architecture](architecture.md) | Android, Linux, display, input, execution, and their trust boundaries |
| [Compatibility](compatibility.md) | What has been demonstrated and what still needs qualification |
| [Roadmap](roadmap.md) | The milestones between this alpha and an installable beta |
| [FAQ](faq.md) | Root, Knox, local execution, updates, Remote, and Android process limits |

## Build and contribute

The [repository README](../README.md) is the entry point for source setup and build guidance. Read the [contribution guide](../CONTRIBUTING.md) before opening a pull request, the [security policy](../SECURITY.md) for vulnerability reports, and the [licensing notice](../LEGAL.md) for distribution boundaries.

## Engineering references

These references explain implementation details and bounded device observations. They complement the product guides; a past successful check does not qualify every later build.

| Reference | Focus |
| --- | --- |
| [Display integration](display-integration.md) | Embedded display, input, and upstream integration |
| [Fold lifecycle](fold-lifecycle.md) | Posture, Activity lifecycle, and runtime ownership |
| [Session recovery](session-recovery.md) | Recovery behavior and intentional stop |
| [Workspace dependencies](workspace-dependencies.md) | ARM64 tools and document runtime |
| [Android tools](android-tools.md) | Permission-based device integrations |

Dated verification reports and publication drafts are retained as historical engineering context. Use the [compatibility matrix](compatibility.md) for current public support statements and the [changelog](../CHANGELOG.md) for release scope.

**Current release: `v0.2.0-alpha.1` — source preview.** The public release gives developers the host and integration sources. It does not include a consumer APK, a preconfigured Linux image, or the proprietary ChatGPT client.
