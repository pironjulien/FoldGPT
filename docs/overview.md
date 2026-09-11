# A desktop workspace that unfolds

FoldGPT turns the inner screen of a Galaxy Z Fold into a local desktop workspace for ChatGPT and Codex. The Android host brings the Linux ARM64 desktop client, project files, command execution, and document tools together on the phone.

The desktop session runs on the Fold. It is not a video stream from another computer. Model requests still use OpenAI's online services.

## What you can explore

### Work on real projects

Use the desktop Codex interface with a workspace stored on the device. Local command and file operations let a conversation create, inspect, and change real project files. Git, Node, and Python workflows have been exercised on the development Fold.

### Create documents on the phone

The adapted ARM64 workspace runtime has produced and read back Word documents, PowerPoint slides, spreadsheets, and PDFs. Rendering tools run locally. These demonstrations cover specific workflows; compatibility with every plugin and package is still being developed.

### Use the space you unfold

The embedded display uses the inner screen for the desktop surface, with touch and Android keyboard integration. The host observes folding posture and separates the visible Activity from the runtime service so the display can change without making its lifecycle the owner of all work.

Reliable continuation through extended background use, folding, and multiple active conversations is an engineering milestone, rather than a guarantee of this alpha.

## Built around Android

FoldGPT runs under its own Android application UID. Its execution model does not require root or an unlocked bootloader. It uses a Debian/PRoot environment for Linux compatibility and an embedded Termux:X11 display with a Mesa graphics path for Adreno hardware.

This is an independent interoperability project. The desktop client is obtained separately from OpenAI; FoldGPT adds a compatibility shim and a workspace adapter bound to a specific client version. It is not an OpenAI or Samsung product.

## Who the alpha is for

`v0.2.0-alpha.1` is a source preview for Android, Linux, graphics, and developer-tool contributors. It exposes the implementation and its open engineering questions so others can inspect the work, reproduce suitable parts of it, and propose improvements.

A consumer APK and a one-click installation path are not part of this release. The next product milestones are reproducible packaging, a clean installation flow, and measured lifecycle and process reliability.

Continue with [architecture](architecture.md), check the [compatibility matrix](compatibility.md), or choose an area on the [roadmap](roadmap.md).
