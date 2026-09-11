# Contributing to FoldGPT

FoldGPT welcomes practical improvements to the Android host, Linux integration, local tools, documentation, and user experience. You can contribute through an issue, a discussion, or a pull request without write access to the repository.

## Find a useful starting point

Read the [product overview](docs/overview.md), [architecture](docs/architecture.md), and [roadmap](docs/roadmap.md). Check existing issues before opening a new one. For a broad architecture change or new dependency, first explain the user problem, alternatives, and expected benefit in an issue or discussion.

Good first contributions include clearer setup documentation, focused input fixes, accessibility improvements, reproducible runtime tests, and reports from additional devices.

## Report a bug

Include the source revision or release, device model, Android version, steps to reproduce, expected behavior, and actual behavior. For runtime problems, distinguish command output from UI state and note whether the failure involves folding, background use, an update, or concurrent conversations.

Share a minimal redacted log or reproduction. Remove device serials, conversation contents, local account paths, tokens, and other private data. Report vulnerabilities through [SECURITY.md](SECURITY.md), not a public issue.

## Submit a pull request

1. Fork the repository and create a branch from the current default branch.
2. Keep the change focused on one behavior or coherent improvement.
3. Follow the source setup and build guidance in the [README](README.md).
4. Run the checks relevant to the change and record the commands and outcomes.
5. Update documentation and the [changelog](CHANGELOG.md) when behavior or requirements change.
6. Explain the problem, resulting behavior, validation, and remaining limitations in the pull request.

Maintainers review every contribution and retain merge and release control. Opening a pull request proposes a change; it does not grant direct access to the default branch. Changes to runtime permissions, lifecycle ownership, packaging, or execution boundaries receive particular scrutiny.

See the [test guide](tests/README.md) for commands and platform requirements, and the [repository layout](docs/project-layout.md) before adding source files.

## Make validation meaningful

Use a regression test when it can demonstrate a real behavior or failure boundary. Documentation and visual changes need appropriate review rather than tests that merely repeat their contents.

Android runtime changes often need device evidence in addition to host checks. A successful build does not establish that an installed runtime works. A visible desktop window does not establish command execution, and a recovered service does not establish that an interrupted task completed. Include the tested scope and leave untested claims explicit.

Preserve independent simultaneous conversations. Do not make a process-pressure test pass by serializing normal conversation use, silently disabling tools, suppressing failures, or weakening Android protections.

## Keep the source distributable

Contribute code you have the right to submit and preserve dependency notices. The host uses GPL-3.0-or-later; components keep their own licenses. See [LEGAL.md](LEGAL.md).

Do not commit credentials, OAuth material, browser profiles, proprietary client files or icons, APKs, Linux images, private recovery archives, or account-derived screenshots and logs. Use synthetic examples and artwork created for this project. Do not claim compatibility with updates, Knox, payment apps, Remote, or additional devices without evidence for that exact scope.

## Work together well

Keep feedback specific, respectful, and focused on the work. Explain tradeoffs, welcome reproducible counterexamples, and make the project easier for the next person to understand.
