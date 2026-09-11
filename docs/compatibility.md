# Compatibility

**Release scope: `v0.2.0-alpha.1`, source preview.** Demonstrated behavior comes from the development Galaxy Z Fold. It is evidence for those workflows on that setup, not certification of every device or a ready-to-install public package.

## Experience matrix

| Area | Status | Scope |
| --- | --- | --- |
| Linux desktop interface | Demonstrated | ChatGPT and Codex rendered locally on the inner display |
| Touch and keyboard | Demonstrated | Android keyboard integration and text input, including accented characters |
| Local projects | Demonstrated | Real command execution and file operations through the native executor |
| Developer tools | Demonstrated | Selected Git, Node, and Python workflows |
| Document tools | Demonstrated | Creation and readback of DOCX, PPTX, XLSX, and PDF outputs, including rendered documents |
| Recovery and explicit stop | Demonstrated in bounded tests | Controlled crash recovery and persistence of an intentional stop |
| Fold-aware display handling | Implemented; qualification incomplete | Posture and display lifecycle integration; reliable automatic return and active work across extended folding still need qualification |
| Several active conversations | Qualification pending | Independent conversations remain a product requirement; sustained concurrent load is not established |
| Long background sessions | Qualification pending | Android process and memory policies can interrupt the runtime |
| Remote | Experimental | End-to-end use and continuity across device posture changes are not qualified |
| Client and runtime updates | Qualification pending | The workspace adapter is tied to a recognized client version |
| Fresh installation | Qualification pending | No consumer APK or one-click installer in this release |
| General plugin compatibility | Partial | Specific workflows have passed; arbitrary plugins and package managers are not qualified |

“Demonstrated” describes a real exercised workflow. It does not mean that every later build or environment has passed the same check.

## Device and system scope

The development target is the Galaxy Z Fold 8 (`SM-F971B`), using ARM64, Android 17/API 37, and Adreno graphics. Other Fold generations, non-Samsung devices, and alternative GPU families require their own validation.

| Property | Meaning |
| --- | --- |
| Root | Not required by the FoldGPT execution model |
| Bootloader | Unlocking is not required; the development phone was observed locked |
| Verified boot and Knox | The development phone reported verified boot `green` and Knox warranty bit `0` |
| Payment and banking apps | Not directly qualified; observed boot state does not guarantee their compatibility |
| Display refresh | The development display reports approximately 120 Hz; application frame rate has not been benchmarked |
| Network | Required for OpenAI account services and model requests |
| Desktop host computer | Not used as a streamed desktop in the demonstrated runtime; source preparation still uses development tooling |

## Process pressure

The development phone reports `max_phantom_processes=32`. Android shares this budget across monitored child processes rather than assigning 32 to each app. Other applications and transient tool launches affect available headroom.

A foreground service does not exempt its Linux subprocesses from this policy. Crash recovery can restore eligible sessions after some failures, but it does not prevent Android from reclaiming processes or prove that an interrupted tool completed.

## What unlocks a beta

A beta needs a reproducible installation on a clean device, tested update and recovery flows, and measured behavior through concurrent work, folding, and background use. Follow the [roadmap](roadmap.md) for the acceptance criteria.
