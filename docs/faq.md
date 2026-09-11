# Frequently asked questions

## What is FoldGPT?

An independent Android host that runs the Linux ARM64 ChatGPT desktop client on a Galaxy Z Fold, with the desktop Codex interface and local project tools. See the [product overview](overview.md).

## Is this a mobile website or a remote video stream?

No. The desktop client and its display session run on the phone. Model requests still reach OpenAI's online services. “Local” describes the desktop runtime, files, and tools; it does not mean offline model inference.

## Is it an official OpenAI or Samsung app?

FoldGPT is an independent project. It uses an official Linux desktop package obtained separately from OpenAI, together with FoldGPT compatibility adaptations. It is not endorsed or certified by OpenAI or Samsung.

## Does it require root or an unlocked bootloader?

No. The host runs under its own ordinary Android application UID. PRoot provides userspace compatibility without rooting Android or replacing its kernel.

## What about Knox and Samsung Pay?

The development phone reported verified boot `green`, a locked bootloader, and a Knox warranty bit of `0`. The architecture does not require bootloader unlocking. Samsung Pay and other banking or payment apps have not been directly qualified, so the project does not promise their compatibility.

## Can I download an APK and install it now?

`v0.2.0-alpha.1` is a source preview. It does not distribute a consumer APK, a Linux image, or the proprietary ChatGPT client. The repository provides the host and integration sources for developers; a reproducible clean-device installation is a [roadmap milestone](roadmap.md).

## Which devices work?

The development target is the Galaxy Z Fold 8 (`SM-F971B`) with ARM64 and Adreno graphics. Other devices are not yet qualified. A similar processor or screen shape alone is not enough to establish compatibility.

## Does 120 Hz mean the desktop runs at 120 frames per second?

No. Approximately 120 Hz is an observed display refresh mode. Application frame rate, frame pacing, and latency need separate measurements.

## Can ChatGPT still update normally?

Update compatibility is not guaranteed. The workspace integration includes an ASAR adapter for a recognized client version, currently `26.901.41600`. A new client version needs compatibility review; an unknown version is rejected by that adaptation flow.

## Is Remote supported?

Remote remains experimental. An end-to-end connection to the same desktop session, and continuity through folding or background use, still need qualification. A working local desktop session does not prove Remote works.

## Will folding the phone keep my task running?

The display and runtime have separate lifecycles, and the host handles folding posture. Continued active work over extended folding, reliable automatic return, and background survival remain under qualification. Android may still terminate runtime processes.

## What does Android's limit of 32 processes mean?

The development phone reports a global budget of 32 monitored child processes, commonly called phantom processes. It is not a limit on all Android processes, nor a private allowance of 32 for FoldGPT. Desktop helpers and other apps can compete for that shared budget.

Ordinary additional APKs do not multiply it. The project's direction is to reduce unnecessary process lifetimes, start tools when needed, and improve cleanup while preserving simultaneous conversations. The source alpha does not depend on disabling Android's process protections.

## Are commands sandboxed like they are on a Linux desktop?

Not equivalently. Android's UID and permission model remain in force, but PRoot and the desktop compatibility shim do not provide Linux namespace isolation. Project checks have a narrower scope than universal tool containment. Read the [security policy](../SECURITY.md) before evaluating sensitive workloads.

## Can I propose an improvement?

Yes. Open an issue, start a discussion, or fork the repository and submit a pull request. You do not need write access. Maintainers review changes and decide what to merge; see [CONTRIBUTING.md](../CONTRIBUTING.md).
