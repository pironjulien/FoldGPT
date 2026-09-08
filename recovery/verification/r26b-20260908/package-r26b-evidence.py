"""Read archived r26b observations; preserve only scoped evidence, never the phone.

Run from anywhere with Python. No ADB, subprocess, network, Git, or source edits.
"""
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path

ROOT = next(parent for parent in Path(__file__).resolve().parents
            if (parent / "work/app-transport-20260908").is_dir() and (parent / "android/app").is_dir())
BASE = ROOT / "work/app-transport-20260908"
DEST = ROOT / "recovery/verification/r26b-20260908"
THREAD = "01a07fe2-4dc0-7791-adc0-fb3fe079872c"
TURN = "01a08287-665b-74e3-9d93-018afdf57f1e"
COMMANDS = {"exec-adcda63d-d4f5-476c-8558-a68b37fdd3d8",
            "exec-b30605e3-a0c1-4e5a-945a-c95a377b92ff"}
origins = {}
sources = {}


def read(name):
    data = (BASE / name).read_bytes()
    sources[name] = {"bytes": len(data), "sha256": sha256(data).hexdigest()}
    return data


def parsed(name):
    return json.loads(read(name))


def emit(name, value, source, selection):
    (DEST / name).parent.mkdir(parents=True, exist_ok=True)
    (DEST / name).write_text(json.dumps(value, ensure_ascii=True, indent=2) + "\n", encoding="utf-8", newline="\n")
    origins[name] = {"kind": "JSON extraction or calculated audit", "source": source, "selection": selection}


def copy(source, name=None):
    name = name or source
    (DEST / name).parent.mkdir(parents=True, exist_ok=True)
    (DEST / name).write_bytes(read(source))
    origins[name] = {"kind": "byte-identical copy", "source": source}


DEST.mkdir(parents=True, exist_ok=True)
capture = parsed("native-validation-progress1.json")
events = capture["response"]["result"]["result"]["value"]["events"]
selected = []
completed = []
turns = []
for index, event in enumerate(events):
    params = event.get("params", {})
    method = event.get("method")
    if params.get("threadId") != THREAD:
        continue
    item = params.get("item", {})
    target = item.get("id", params.get("itemId")) in COMMANDS
    if (target and params.get("turnId") == TURN and
            method in {"item/started", "item/completed", "item/commandExecution/outputDelta",
                       "item/commandExecution/terminalInteraction"}):
        selected.append({"sourceIndex": index, "event": event})
        if method == "item/completed":
            completed.append(event)
    if method in {"turn/started", "turn/completed"} and params.get("turn", {}).get("id") == TURN:
        turns.append({"sourceIndex": index, "at": event["at"], "method": method,
                      "threadId": params["threadId"],
                      "turn": {k: v for k, v in params["turn"].items() if k != "items"}})
assert len(completed) == 2
assert completed == parsed("native-validation-tools.json")
assert len(turns) == 2 and turns[-1]["turn"]["status"] == "completed"
assert turns[-1]["turn"]["error"] is None
assert completed[0]["params"]["item"]["exitCode"] == 0
output = completed[0]["params"]["item"]["aggregatedOutput"]
assert "Ran 5 tests in 0.637s\n\nOK" in output
assert "statuses: environment=0 rg=0 tests=0 json=1 markdown=1 rg_files=0\n" in output
assert completed[1]["params"]["item"]["exitCode"] == 23
assert completed[1]["params"]["item"]["status"] == "failed"
assert completed[1]["params"]["item"]["aggregatedOutput"] == "bonjour autonome\r\nFOLD_APP_REPLY=bonjour autonome\r\n"
interactions = [s for s in selected if s["event"]["method"].endswith("/terminalInteraction")]
assert len(interactions) == 1 and interactions[0]["event"]["params"]["stdin"] == "bonjour autonome\n"
emit("command-events.json", selected, "native-validation-progress1.json",
     "/response/result/result/value/events; exact selected event objects with zero-based sourceIndex")
emit("turn-metadata.json", turns, "native-validation-progress1.json",
     "/response/result/result/value/events; selected turn metadata only; items deliberately omitted")
copy("native-validation-tools.json")

# The UI event capture omitted initial chunks. The actual persisted tool outputs
# retain them; independently match the supplied extraction against its JSONL.
functional_bytes = read("r26b-functional/native-conversation.jsonl")
functional_records = [json.loads(line) for line in functional_bytes.splitlines()]
tool_rows = []
tool_indices = []
for index, record in enumerate(functional_records):
    payload = record.get("payload", {})
    if (record.get("type") == "response_item" and payload.get("type") == "custom_tool_call_output"
            and payload.get("internal_chat_message_metadata_passthrough", {}).get("turn_id") == TURN):
        tool_rows.append(record)
        tool_indices.append(index)
assert tool_rows == parsed("r26b-functional/tool-outputs.json") and len(tool_rows) == 4
copy("r26b-functional/tool-outputs.json")
chunks = []
for record in tool_rows:
    for block in record["payload"]["output"]:
        try:
            value = json.loads(block.get("text", ""))
        except json.JSONDecodeError:
            continue
        if type(value) is dict and "output" in value:
            chunks.append(value)
assert len(chunks) == 4
environment = chunks[0]["output"]
for line in ["sys.platform= android", "platform.machine()= aarch64", "os.getuid()= 10412",
             "os.getcwd()= /data/data/app.foldgpt/files/projects/ui-python-caae3a83d156",
             "sys.executable= /data/app/~~h1j2vVo5ocZN-Hqe_vqEog==/app.foldgpt-MYcth4qAAloa1xvUC2DBWg==/lib/arm64/libfoldgpt_python_cli.so",
             "/data/data/app.foldgpt/files/native-runtime-v1/python/bin/rg"]:
    assert line in environment.splitlines()
assert chunks[0]["session_id"] == 27554 and chunks[2]["session_id"] == 5081
assert chunks[2]["output"] == "FOLD_APP_READY\r\n"
assert chunks[3]["exit_code"] == 23
emit("persisted-tool-output-audit.json", {"sourceRecordIndices": tool_indices, "sourceRecordNumbers": [i + 1 for i in tool_indices],
     "extractionMatchesOriginalRecords": True, "parsedCommandChunks": chunks,
     "scope": "Actual tool-result records of the target turn; full conversation omitted"},
     "r26b-functional/native-conversation.jsonl", "zero-based JSONL record indices, plus parsed nested tool results")

for name in ["app-start-r26b/startup.json", "app-start-r26b/native-status.json",
             "app-start-r26b/report.json", "device-current-r26b/native-status.json",
             "device-current-r26b/report.json", "apk-r26b-verification.json",
             "legacy-migration-r2/qualification-commands.json", "legacy-migration-r2/copy-receipt.json",
             "legacy-migration-r2/report.json", "legacy-migration-r2/source-inventory.json",
             "legacy-migration-r2/destination-inventory.json",
             "native-thread-after/appended.jsonl"]:
    copy(name)

# Preserve selected direct device observations, excluding the full device process census.
device = parsed("device-current-r26b/commands.json")
keep = [0, 1, 4, 5]
assert [device[i]["argv"][0] for i in keep] == ["run-as", "pm", "sha256sum", "cat"]
assert all(device[i]["code"] == 0 for i in keep)
emit("device-observations.json", [{"sourceIndex": i, "record": device[i]} for i in keep],
     "device-current-r26b/commands.json", "array indices 0,1,4,5; exact command result records")
status = parsed("device-current-r26b/native-status.json")
assert json.loads(device[0]["stdout"]) == status
assert status["state"] == "ready" and status["launchOrigin"] == "android-app"
assert status["lastNativeSessionStatus"]["cleanupComplete"] is False
assert status["lastNativeSessionStatus"]["ownerRetained"] is True
assert status["lastNativeSessionStatus"]["bootstrapReaped"] is False
apk = parsed("apk-r26b-verification.json")
assert device[4]["stdout"].split()[0] == apk["apkSha256"]

process_facts = {}
for name in ["app-start-r26b/processes.txt", "device-current-r26b/processes.txt"]:
    lines = read(name).decode().splitlines()
    rows = []
    for index, line in enumerate(lines):
        fields = line.split(maxsplit=3)
        # Native owner and UI bootstrap chain only; no browser handles or unrelated apps.
        if len(fields) == 4 and fields[2] == "10412" and fields[3].split()[0] in {
                "app.foldgpt", "app.foldgpt:runtime", "libfoldgpt_python_cli.so", "libproot.so",
                "dbus-run-session", "bash", "codex-native"}:
            rows.append({"sourceLine": index + 1, "text": line})
    assert any("29060 28958 10412 libfoldgpt_python_cli.so" in row["text"] for row in rows)
    assert any("29066 28958 10412 libproot.so" in row["text"] for row in rows)
    process_facts[name] = {"selected": rows,
                          "shizukuNameFoundInFullSnapshot": "shizuku" in "\n".join(lines).lower()}
emit("process-chain.json", process_facts, list(process_facts),
     "exact selected lines with one-based line numbers; Shizuku name check calculated over full snapshots")

logname = "app-start-r26b/runtime.log"
handshakes = [{"sourceLine": i + 1, "text": line}
              for i, line in enumerate(read(logname).decode("utf-8", "replace").splitlines())
              if "initialize_handshake_result" in line and "outcome=success" in line]
assert handshakes
emit("desktop-handshake.json", handshakes, logname,
     "exact lines containing initialize_handshake_result and outcome=success")

# independently compare raw history bytes. This capture ends at cwd repair, before validation.
before = read("native-thread-before/conversation.jsonl")
after = read("native-thread-after/conversation.jsonl")
append = read("native-thread-after/appended.jsonl")
assert after[:len(before)] == before and after[len(before):] == append
assert functional_bytes[:len(after)] == after
added = [json.loads(line) for line in append.splitlines()]
assert len(added) == 1 and added[0]["type"] == "event_msg"
assert added[0]["payload"]["type"] == "thread_settings_applied"
assert added[0]["payload"]["thread_settings"]["cwd"] == "/data/data/app.foldgpt/files/projects/ui-python-caae3a83d156"
history = {"beforeBytes": len(before), "afterBytes": len(after), "appendedBytes": len(append),
           "historyPrefixByteIdentical": True, "addedRecords": 1,
           "addedEventType": "thread_settings_applied", "scope": "cwd repair before target validation turn",
           "postValidationBytes": len(functional_bytes), "postValidationPreservesRepairedPrefix": True}
emit("history-audit.json", history,
     ["native-thread-before/conversation.jsonl", "native-thread-after/conversation.jsonl", "native-thread-after/appended.jsonl", "r26b-functional/native-conversation.jsonl"],
     "raw byte prefix and exact suffix comparison; full conversations omitted")

project = parsed("project-current-after-repair.json")
value = project["response"]["result"]["result"]["value"]["projects"]
emit("project-settings.json", value, "project-current-after-repair.json",
     "/response/result/result/value/projects; visible UI text and page expression omitted")
inventories = parsed("device-current-r26b/project-inventories.json")
assert json.loads(device[2]["stdout"]) == inventories
canonical = inventories["/data/data/app.foldgpt/files/projects"]
alias = inventories["/data/user/0/app.foldgpt/files/projects"]
assert canonical == alias

# Migration fingerprints are recomputed independently from their documented canonical JSON.
def fingerprint(value):
    return sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def content(value):
    return [{k: entry[k] for k in ("path", "kind", "sha256", "bytes", "executable") if k in entry}
            for entry in value["entries"]]


migration_source = parsed("legacy-migration-r2/source-inventory.json")
migration_destination = parsed("legacy-migration-r2/destination-inventory.json")
for inv in [migration_source, migration_destination]:
    original = {k: v for k, v in inv.items() if k not in {"inventorySha256", "contentSha256", "fileCount", "totalBytes"}}
    assert fingerprint(original) == inv["inventorySha256"]
    assert fingerprint(content(inv)) == inv["contentSha256"]
    assert inv["fileCount"] == 0 and inv["totalBytes"] == 0
    assert all(e["kind"] == "directory" for e in inv["entries"])
assert content(migration_source) == content(migration_destination)
copy_calls = parsed("legacy-migration-r2/copy-commands.json")
assert len(copy_calls) == 5 and all(row["code"] == 0 for row in copy_calls)
assert json.loads(copy_calls[1]["stdout"]) == migration_source
assert json.loads(copy_calls[4]["stdout"]) == migration_source
assert json.loads(copy_calls[3]["stdout"]) == migration_destination
copy("legacy-migration-r2/copy-commands.json")
qualification = parsed("legacy-migration-r2/qualification-commands.json")
test_output = qualification[0]["stderr"]
assert qualification[0]["code"] == 1
assert test_output.count(" ... ok\r\n") == 20
assert "Ran 21 tests" in test_output and "FAILED (errors=1)" in test_output
assert "os.link(self.source" in test_output and "PermissionError: [Errno 13]" in test_output
audit = {
    "schema": "foldgpt.r26b-evidence-audit.v1", "threadId": THREAD, "turnId": TURN,
    "sourceEvents": len(events), "eventCounts": dict(Counter(e["method"] for e in events)),
    "selectedCommandEvents": len(selected), "completedCommands": 2,
    "commandCompletionCopyMatchesOriginalCapture": True,
    "unitTestsPassed": 5, "jsonAndMarkdownSemanticExitCodes": [1, 1],
    "ptyInput": "bonjour autonome\n", "ptyExpectedExitCode": 23,
    "initialChunksMissingInUiCapture": ["Python environment values", "command -v rg result", "FOLD_APP_READY"],
    "initialChunksRecoveredFromActualToolOutputs": True,
    "pythonEnvironment": {"sys.platform": "android", "platform.machine": "aarch64", "uid": 10412,
                          "source": "r26b-functional/tool-outputs.json, matched to original JSONL records"},
    "nativeOwner": {"pid": 29060, "parentPid": 28958, "uid": 10412, "state": "ready",
                    "cleanupComplete": False, "bootstrapReaped": False, "ownerRetained": True},
    "projectAliasesEqual": True, "projectRootDevice": canonical["dev"], "projectRootInode": canonical["ino"],
    "projectEntriesInSnapshot": len(canonical["entries"]),
    "history": history,
    "migration": {"sourceBeforeEqualsSourceAfter": True, "matchingContentSha256": migration_source["contentSha256"],
                  "directoriesIncludingRoot": len(migration_source["entries"]), "files": 0, "totalBytes": 0,
                  "nativeTestsPassed": 20, "nativeTestErrors": 1, "nativeSuiteExitCode": 1,
                  "error": "hardlink fixture os.link failed with EACCES before assertion"},
    "boundaries": ["initial app-origin native owner and UI command execution tested",
                   "UI and controller still use PRoot; native command path does not make whole application native",
                   "this turn executes an existing zipapp, not a fresh project creation or build",
                   "same-boot crash recovery and physical reboot recovery not demonstrated by these observations",
                   "owner snapshot is ready with retained owner, not a successful cleanup receipt"]}
emit("audit.json", audit, sorted(sources), "independent assertions and calculations described by evidence script")

# The later lifecycle incident is a separate observation, not a rewrite of the
# earlier ready snapshot. Retain only the package's causal timeline and status.
for name in ["unexpected-stop-r26b/status.txt", "unexpected-stop-r26b/marker.txt",
             "lifecycle-foreground-r2/report.json", "lifecycle-foreground-r2/test.log",
             "lifecycle-foreground-r2/compile.log", "lifecycle-foreground-service-r2/report.json",
             "lifecycle-foreground-service-r2/compile.log"]:
    copy(name)
exit_info = read("unexpected-stop-r26b/exit-info.txt").decode()
first_exit = exit_info.split("        ApplicationExitInfo #0:", 1)[1].split("        ApplicationExitInfo #1:", 1)[0]
assert "21:48:16.920" in first_exit and "reason=10 (USER REQUESTED) subreason=22 (REMOVE TASK)" in first_exit
emit("unexpected-stop-r26b/runtime-exit.json", {"text": "        ApplicationExitInfo #0:" + first_exit},
     "unexpected-stop-r26b/exit-info.txt", "exact text of first ApplicationExitInfo record only")
stop_log = read("unexpected-stop-r26b/lifecycle-logcat.txt").decode()
stop_lines = [{"sourceLine": i + 1, "text": line} for i, line in enumerate(stop_log.splitlines())
              if line.startswith("09-08 21:48:16.") and any(value in line for value in
                ["29060:28958:libfoldgpt_python_cli.so", "29066:28958:libproot.so", "Linux exited with 137",
                 "Killing 28958:app.foldgpt:runtime", "Changes in 10412"])]
assert len(stop_lines) >= 6
emit("unexpected-stop-r26b/causal-timeline.json", stop_lines,
     "unexpected-stop-r26b/lifecycle-logcat.txt", "exact selected package lifecycle lines from 21:48:16")

script_name = "package-r26b-evidence.py"
copy(script_name, script_name)
emit("provenance.json", {"base": "work/app-transport-20260908", "sources": sources, "outputs": origins,
                        "scope": "No full prompts, full conversations, UI body, credentials, third-party sources or full-device census copied.",
                        "integrity": "Copy entries preserve bytes; extracted JSON preserves selected values and array order, not source formatting."},
     sorted(sources), "source byte lengths and SHA256 plus per-output extraction description")
manifest = {"schema": "foldgpt.evidence-manifest.v1", "algorithm": "SHA256", "files": []}
for path in sorted(DEST.rglob("*")):
    if path.is_file() and path.name != "manifest.json":
        data = path.read_bytes()
        manifest["files"].append({"path": path.relative_to(DEST).as_posix(), "bytes": len(data), "sha256": sha256(data).hexdigest()})
(DEST / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
print(json.dumps({"evidence": str(DEST), "files": len(manifest["files"]), "selectedCommandEvents": len(selected),
                  "allAssertionsPassed": True, "migrationPassed": 20, "migrationErrors": 1}))
