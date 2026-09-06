# Inactive integration v2: agent-context files

The new integration container adds the real context generator and its source
manifest to a separately prepared inactive stage. It does not change the
historical v1 container, its manifest, the existing Android v3 preparation, or
their retained reports. Existing v1 bundles still use their exact original file
set and report bytes.

| Contract | Historical input | New input |
| --- | --- | --- |
| Container and manifest format | `foldgpt.inactive-integration.v1` | `foldgpt.inactive-integration.v2` |
| Installed regular files | 20 | 22 |
| Installed relative library links | 9 | 9 |
| Launch contract | `usr/local/share/foldgpt/launch-contract.v1` | `usr/local/share/foldgpt/launch-contract.v2` |
| Integration report header | `foldgpt.inactive-integration-report.v1` | `foldgpt.inactive-integration-report.v2` |

The v2 file set replaces the launch contract and adds two mode-0644 files:

- `usr/local/lib/foldgpt/foldgpt_agent_context.py` from the canonical guest bundle.
- `usr/local/share/foldgpt/agent-environment.v1.json` from
  `config/agent-context/foldgpt.v1.json`.

The Python assembly tool emits v2 explicitly. The Android reader authenticates
the complete container with the caller's independently trusted SHA-256 and byte
count before parsing it. Framing and manifest versions must agree. Each version
selects an exact file/mode/link set and exact launch-contract bytes; the reader
rejects relabeling, omitted or additional context files, and unlisted modes.
The authenticated Debian and reviewed Mesa inputs retain their previous pins.

The launch contract identifies the context generator, manifest, local Codex
global-AGENTS consumer, and first-nonempty override selection. Its final field is
`agent-context-delivery=separate-runtime-observation-required`.

The installer only installs files. It does not execute the generator, create a
Codex profile or `AGENTS.md`, start the client, contact a model, or activate the
stage. The v2 report states:

```text
bundleFormat	foldgpt.inactive-integration.v2
agentContext	files-installed-only
modelDelivery	not-verified
```

Context synchronization at session startup is a separate runtime operation;
[Agent environment](../agent-environment.md) describes its scope. Successful
file installation is not evidence that a particular model session received the
instructions.

## Retry and historical evidence

The durable paths remain `integration-install/intent.v1` and `report.v1`.
The intent already binds the entire container and manifest SHA-256, so a retry
with another revision fails before installing files or replacing the original
intent/report. Both v1-to-v2 and v2-to-v1 retries are tested. The installer does
not provide in-place migration of an existing bound stage.

The existing combined-probe Python prepare/collector tools and Android debug
probe deliberately retain their v1 integration-report contract. They cannot be
used to claim an Android v2 preparation. The production Java bundle reader and
installer accept both versions; an Android run using the new revision needs a
separate compatible diagnostic input and collection. No old v3 evidence has
been reclassified as testing the new context files.

## Host verification

Run the dedicated JVM suite, then give its printed classes directory to the
real archive comparison:

```bash
bash tools/install/integration-native/run-jvm-tests.sh
bash tools/install/integration-native/check-context-revision.sh /var/tmp/foldgpt-integration-java-EXAMPLE/classes
```

The comparison checks out no account/profile data. It assembles a new guest
bundle from the named repository text sources, authenticates the actual Debian
and Mesa archives, and builds a new content-addressed v2 container. It uses two
new host filesystem stages, never the historical stage. Each actual v1/v2 input
is installed, closed, reopened and verified again under Linux UID 12345 and GID
23456, numerical identities free in the Debian base. Those are test-host
credentials, not Android or production guest constants.

The runner retains text-source snapshots, the new archives and manifest,
structural reports, identity, test output and SHA-256 inventory under a fresh
private `downloads/install/integration-native/foldgpt-integration-context-*`
directory. Host stage trees remain under `/var/tmp`. It never runs ARM code,
accesses Android, opens a vault or activates a root.

The completed host comparison is retained under
`downloads/install/integration-native/foldgpt-integration-context-7njeZw4s`.
Its actual v2 container has SHA-256
`340c2dcbc7cafa16fc327abe74acc2e9dc3f350691339dd298069f3b7f66573d`
and 41,136,548 bytes. Both real stage preparations and reopen checks passed,
along with eight Python archive tests. The separate JVM suite passed 15 tests,
including actual process deaths/retries and cross-version refusal.
The retained text-source snapshot describes the `.1` agent manifest; the
later model-neutral `.2` source produces a new container identity and is not
retroactively covered by this archive hash. Actual live profile context
deployment and model delivery have their own evidence in the linked context
document.
