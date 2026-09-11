# Roadmap

FoldGPT's next step is a dependable installation and daily workflow around the desktop experience already demonstrated on the development Fold. These milestones describe acceptance criteria, not release dates.

## Available now · source alpha

`v0.2.0-alpha.1` opens the Android host, integration code, build checks, and project documentation to contributors. Local desktop interaction, project execution, selected document workflows, and bounded recovery scenarios have been demonstrated. See [compatibility](compatibility.md) for their limits.

## Milestone 1 · reproducible installation

- Build the required open-source components from documented, pinned inputs.
- Verify package provenance, hashes, completeness, and required license notices.
- Complete installation on a clean supported device without relying on a prepared development environment.
- Keep proprietary client acquisition separate and leave account sign-in to the client.
- Exercise interrupted installation, storage exhaustion, repair, and uninstall behavior without losing existing projects.

**Exit criterion:** a contributor can follow the published setup on a clean supported device and complete a real local Codex task.

## Milestone 2 · dependable sessions

- Measure global monitored child processes, application processes, and memory separately, through idle and peak tool activity.
- Reduce unnecessary helpers and release idle resources while retaining independent simultaneous conversations.
- Validate owner-scoped cleanup against active tools and persistent project data.
- Exercise folding, display recreation, background use, memory pressure, and repeated start/stop cycles.
- Make interruption visible and preserve user intent without replaying commands or model requests automatically.

**Exit criterion:** a published device test matrix demonstrates concurrent work and lifecycle recovery, including failures and remaining limits.

## Milestone 3 · safe updates

- Test host, Linux environment, workspace runtime, and desktop client updates as separate transitions.
- Require compatibility checks for a new client version before activating its workspace adapter.
- Verify project preservation and rollback for each supported transition.

**Exit criterion:** an update matrix records successful upgrades and recoverable failures from the supported previous version.

## Milestone 4 · wider experience

- Qualify Remote against the same desktop session, including folding and background transitions.
- Expand device and GPU coverage from reproducible contributor reports.
- Extend Android integrations through explicit permissions and real end-to-end scenarios.
- Measure interaction latency, frame pacing, power use, and accessibility on supported hardware.

**Exit criterion:** each newly advertised capability has a repeatable test and a stated support boundary.

## Contribute where it matters

Good contributions include a focused lifecycle regression case, a reproducible package build, a process trace with private data removed, an input or accessibility improvement, or a device compatibility report. Start with [CONTRIBUTING.md](../CONTRIBUTING.md) and open a proposal before a broad architectural change.
