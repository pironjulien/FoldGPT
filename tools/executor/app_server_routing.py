"""Select a FoldGPT environment on the audited official app-server protocol.

This is routing, never permission enforcement. Policies and approval messages
remain unchanged. This module is intentionally separate from a launcher: host
RPCs, queued submissions before a resumed thread's first turn, and alternate
connections must be integrated before enabling it in the normal application.
"""
from copy import deepcopy
from dataclasses import dataclass
import re

from tools.executor.exec_server import RpcError


def absolute_path(value):
    # The environment and client share GNU path names. Do not reinterpret URI,
    # Windows, relative or normalized-looking paths as a different workspace.
    if not isinstance(value, str) or not value.startswith("/") or "\0" in value:
        raise RpcError(-32602, "FoldGPT routing requires an absolute GNU path")
    return value


def roots(value):
    if not isinstance(value, list):
        raise RpcError(-32602, "FoldGPT workspace roots must be an array")
    return [absolute_path(path) for path in value]


@dataclass(frozen=True)
class Location:
    cwd: str
    workspace_roots: tuple | None
    enabled: bool = True


def retarget(prior, cwd):
    if prior is None or prior.workspace_roots is None:
        return None
    return tuple(dict.fromkeys(cwd if root == prior.cwd else root for root in prior.workspace_roots))


class EnvironmentRouter:
    """Keep thread locations learned from successful official responses only.

    No transcript, command, credentials, approval fields or policy is retained.
    Failed starts/turns never change sticky location. Client-provided empty
    environments retain the official meaning: no environment access.
    """
    def __init__(self, environment_id, default_cwd):
        if (not isinstance(environment_id, str) or environment_id == "local"
                or environment_id.lower() == "none" or len(environment_id) > 64
                or re.fullmatch(r"[A-Za-z0-9_-]+", environment_id) is None):
            raise ValueError("A non-local FoldGPT environment ID is required")
        self.environment_id = environment_id
        self.default_cwd = absolute_path(default_cwd)
        self.locations = {}
        self.pending = {}

    def _selection(self, params, prior=None):
        supplied = params.get("environments")
        disabled = supplied == [] or supplied is None and prior is not None and not prior.enabled
        if supplied is not None and supplied != []:
            if not isinstance(supplied, list) or len(supplied) != 1:
                raise RpcError(-32602, "FoldGPT routing requires one explicit environment")
            item = supplied[0]
            if (not isinstance(item, dict) or set(item) - {"environmentId", "cwd", "runtimeWorkspaceRoots"}
                    or item.get("environmentId") not in {"local", self.environment_id}):
                raise RpcError(-32602, "Unrecognized FoldGPT environment selection")
            cwd = absolute_path(item.get("cwd"))
            selected_roots = item.get("runtimeWorkspaceRoots")
            selected_roots = None if selected_roots is None else roots(selected_roots)
            # Preserve upstream precedence without inventing a conflict rule.
            # Official resolution selects explicit environment paths; legacy
            # top-level cwd/workspace fields are forwarded byte-for-value.
        else:
            cwd = params.get("cwd")
            cwd = absolute_path(cwd) if cwd is not None else prior.cwd if prior else self.default_cwd
            selected_roots = params.get("runtimeWorkspaceRoots")
            if selected_roots is not None:
                selected_roots = roots(selected_roots)
            elif prior is not None:
                selected_roots = retarget(prior, cwd)
        item = {"environmentId": self.environment_id, "cwd": cwd}
        if selected_roots is not None:
            item["runtimeWorkspaceRoots"] = list(selected_roots)
        return ([] if disabled else [item]), Location(cwd,
            (cwd,) if selected_roots is None else tuple(selected_roots), not disabled)

    def outgoing(self, message):
        method = message.get("method")
        if method not in {"initialize", "thread/start", "turn/start", "thread/resume", "thread/fork", "thread/settings/update"}:
            return message
        params = message.get("params")
        if not isinstance(params, dict) or "id" not in message:
            raise RpcError(-32602, "Routing requires a request with object params")
        identifier = message["id"]
        if identifier in self.pending:
            raise RpcError(-32600, "Duplicate pending routing request ID")
        result = deepcopy(message)
        location = None
        thread_id = params.get("threadId")
        if method == "initialize":
            capabilities = result["params"].get("capabilities")
            if capabilities is None:
                capabilities = {}
            if not isinstance(capabilities, dict):
                raise RpcError(-32602, "Invalid initialize capabilities")
            capabilities["experimentalApi"] = True
            result["params"]["capabilities"] = capabilities
        elif method in {"thread/start", "turn/start"}:
            prior = self.locations.get(thread_id)
            if method == "turn/start" and prior is None and params.get("cwd") is None and not params.get("environments"):
                # A pipelined resume has not returned its real directory yet.
                # Do not substitute the launcher directory for an existing task.
                if params.get("environments") != []:
                    raise RpcError(-32602, "Thread location is not known before its successful start or resume")
            selected, location = self._selection(params, prior)
            result["params"]["environments"] = selected
        elif method == "thread/settings/update" and params.get("cwd") is not None:
            # The authoritative settings-updated notification also refreshes
            # this state; the response path covers notification opt-outs.
            cwd = absolute_path(params["cwd"])
            prior = self.locations.get(thread_id)
            location = Location(cwd, retarget(prior, cwd), prior.enabled if prior else True)
        # resume/fork carry no invented environments field. The next turn gets
        # the explicit override, after its actual official cwd has been read.
        self.pending[identifier] = (method, thread_id, location)
        return result

    def incoming(self, message):
        if message.get("method") == "thread/settings/updated":
            params = message.get("params", {})
            settings = params.get("threadSettings", {})
            if params.get("threadId") in self.locations and isinstance(settings, dict) and "cwd" in settings:
                cwd = absolute_path(settings["cwd"])
                prior = self.locations[params["threadId"]]
                self.locations[params["threadId"]] = Location(cwd, retarget(prior, cwd), prior.enabled)
            return message
        if "method" in message or "id" not in message:
            return message
        pending = self.pending.pop(message["id"], None)
        if pending is None or "error" in message:
            return message
        method, thread_id, location = pending
        result = message.get("result")
        if not isinstance(result, dict):
            raise RpcError(-32603, "Official routing response has an unexpected shape")
        if method in {"thread/start", "thread/resume", "thread/fork"}:
            thread = result.get("thread")
            if not isinstance(thread, dict) or not isinstance(thread.get("id"), str):
                raise RpcError(-32603, "Official thread response lacks its identity")
            cwd = absolute_path(result.get("cwd"))
            workspace_roots = result.get("runtimeWorkspaceRoots")
            workspace_roots = None if workspace_roots is None else tuple(roots(workspace_roots))
            prior = self.locations.get(thread_id)
            if location is not None and location.enabled:
                self.locations[thread["id"]] = location
            else:
                self.locations[thread["id"]] = Location(cwd, workspace_roots,
                    location.enabled if location else prior.enabled if prior else True)
        elif method in {"turn/start", "thread/settings/update"} and location is not None:
            self.locations[thread_id] = location
        return message
