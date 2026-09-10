"""Observe global AGENTS loading in one actual official Codex CLI model turn.

Run as the selected guest account. The prompt does not contain the expected
Android answer. Only this new turn and its matching rollout are inspected;
existing account credentials and conversations are never copied into evidence.
This is CLI loading evidence, not a Desktop route or command-sandbox test.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import selectors
import subprocess
import tempfile
import time

CODEX = Path("/usr/lib/chatgpt/resources/codex")
CODEX_SHA = "4d76e542c222ea8c75861d8c4ade60a1a332a63255ce1c60bdaebf7c2a2869e6"
PROMPT = ("Sans appeler aucun outil et uniquement d'après les instructions déjà chargées, "
          "indique l'hôte de cette interface, l'environnement des commandes, la différence entre "
          "le rendu graphique et le calcul du modèle, puis le chemin du manifeste décrivant tes capacités. "
          "N'invente pas de renseignement absent. Réponds brièvement en français.")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def require(value, message):
    if not value:
        raise RuntimeError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agents-sha256", required=True)
    parser.add_argument("--model", required=True)
    args = parser.parse_args()
    require(os.getuid() > 0 and sha(CODEX.read_bytes()) == CODEX_SHA, "Guest identity or official Codex differs")
    home = Path(os.environ["HOME"])
    codex_home = Path(os.environ.get("CODEX_HOME", str(home / ".codex")))
    agents = codex_home / "AGENTS.override.md"
    if not agents.is_file() or not agents.read_bytes().strip():
        agents = codex_home / "AGENTS.md"
    expected = agents.read_bytes()
    require(sha(expected) == args.agents_sha256, "Selected global instructions differ from deployment")
    start, end = b"<!-- foldgpt:environment:v1 begin -->", b"<!-- foldgpt:environment:v1 end -->"
    require(expected.count(start) == expected.count(end) == 1, "Missing unique FoldGPT block")
    block = expected[expected.index(start):expected.index(end) + len(end)].decode()
    state = home / ".local/state/foldgpt"
    state.mkdir(mode=0o700, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="context-check-", dir=state))
    work.chmod(0o700)
    (work / "prompt.txt").write_text(PROMPT + "\n")
    report = {"schema": "foldgpt.official-context-cli.v1", "status": "IN_PROGRESS", "work": str(work),
              "uid": os.getuid(), "codexSha256": CODEX_SHA, "agentsSha256": args.agents_sha256,
              "globalInstructionsPath": str(agents), "model": args.model,
              "modelDeliveryVerified": False, "scope": "One real CLI context-only turn; no Desktop/command-execution qualification"}
    events = []
    try:
        # No model/provider/security configuration file is changed. The request
        # explicitly asks for no tools; read-only remains the command policy.
        command = [str(CODEX), "--ask-for-approval", "never", "exec", "--json", "--skip-git-repo-check",
                   "--sandbox", "read-only", "--model", args.model, "--cd", str(work), PROMPT]
        with (work / "stderr.log").open("wb") as errors:
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=errors)
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            pending = bytearray()
            deadline = time.monotonic() + 180
            try:
                while True:
                    require(time.monotonic() < deadline, "Official context turn exceeded its deadline")
                    if not selector.select(min(5, max(0, deadline - time.monotonic()))):
                        continue
                    data = os.read(process.stdout.fileno(), 65536)
                    if not data:
                        break
                    pending.extend(data)
                    require(len(pending) <= 4 * 1024 * 1024 and len(events) < 10000, "Official event boundary exceeded")
                    while b"\n" in pending:
                        line, _, pending = pending.partition(b"\n")
                        if line:
                            events.append(json.loads(line))
                require(not pending, "Truncated official JSON event")
                process.wait(10)
                report["exitCode"] = process.returncode
            finally:
                selector.close()
                process.stdout.close()
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(10)
        report["eventTypes"] = [item.get("type") for item in events]
        report["errors"] = [item for item in events if item.get("type") in {"error", "turn.failed"}
                            or item.get("type") == "item.completed" and item.get("item", {}).get("type") == "error"]
        threads = [item["thread_id"] for item in events if item.get("type") == "thread.started"]
        require(len(threads) == 1 and re.fullmatch(r"[0-9a-f-]{36}", threads[0]), "No unique actual CLI thread")
        report["threadId"] = threads[0]
        items = [item["item"] for item in events if isinstance(item.get("item"), dict)]
        report["itemTypes"] = sorted({item.get("type", "") for item in items})
        forbidden = {"command_execution", "mcp_tool_call", "web_search", "file_change", "collab_tool_call"}
        require(not forbidden.intersection(report["itemTypes"]), "Context-only model unexpectedly used a tool")
        replies = [item["text"] for item in items if item.get("type") == "agent_message" and "text" in item]
        # Start/update/completion events can repeat a message; retain exact final text.
        report["answer"] = replies[-1] if replies else None
        matches = list((codex_home / "sessions").glob("*/*/*/*" + threads[0] + ".jsonl"))
        require(len(matches) == 1, "New turn has no unique persisted rollout")
        rollout = matches[0]
        loaded = []
        with rollout.open("rb") as stream:
            for number, line in enumerate(stream, 1):
                require(number < 20000 and len(line) <= 8 * 1024 * 1024, "New rollout exceeds context proof bounds")
                event = json.loads(line)
                payload = event.get("payload", {})
                if event.get("type") == "response_item" and payload.get("type") == "message":
                    for content in payload.get("content", []):
                        text = content.get("text", "")
                        if block in text:
                            loaded.append({"line": number, "role": payload.get("role"),
                                           "messageSha256": sha(text.encode()), "blockSha256": sha(block.encode())})
        report["rolloutPath"] = str(rollout)
        report["loadedContextMessages"] = loaded
        require(loaded and all(item["role"] == "user" for item in loaded), "Actual rollout lacks the exact global context block")
        require(report.get("exitCode") == 0 and "turn.completed" in report["eventTypes"] and replies,
                "Actual model context turn did not complete")
        answer = report["answer"].lower()
        require("android" in answer and "linux" in answer and "environment-" in answer,
                "Model answer does not identify the loaded host/guest/manifest")
        report["modelDeliveryVerified"] = True
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = type(error).__name__ + ": " + str(error)
        raise
    finally:
        if (work / "stderr.log").is_file():
            stderr = (work / "stderr.log").read_bytes()
            report["stderrBytes"] = len(stderr)
            report["stderrSha256"] = sha(stderr)
        (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
