"""Opt-in two-server host-RPC transport for the untouched official 0.153.4.

Only stateless host operations and connection-owned watches/processes go to the
host companion. Account and task state stay exclusively in the main server.
No thread is created/resumed in the host; thread/shellCommand stays with main.
This transport changes no command, environment override, policy or result.
"""
import argparse
import asyncio
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import signal
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.exec_server import MAX_MESSAGE_BYTES, decode_message

HOST_METHODS = frozenset({
    "fs/readFile", "fs/writeFile", "fs/createDirectory", "fs/getMetadata", "fs/readDirectory",
    "fs/remove", "fs/copy", "fs/watch", "fs/unwatch",
    "process/spawn", "process/writeStdin", "process/kill", "process/resizePty",
    "command/exec", "command/exec/write", "command/exec/resize", "command/exec/terminate",
})
HOST_NOTIFICATIONS = frozenset({"fs/changed", "process/outputDelta", "process/exited",
                                "command/exec/outputDelta", "configWarning"})


def destination(message):
    method = message.get("method")
    if method in HOST_METHODS:
        return "host"
    if method in {"environment/info", "environment/status"}:
        params = message.get("params")
        if type(params) is dict and params.get("environmentId") == "local":
            return "host"
    # In particular, responses to server-initiated approval requests always
    # return to their sole owner, main, with their original request IDs.
    return "main"


@dataclass(frozen=True)
class Launch:
    """Exact supervisor-owned launch, including an explicit environment map.

    A production supervisor can use independently attested native stdio bridges
    here when the two servers need different per-process PRoot file bindings.
    This transport neither invents those bindings nor authenticates that recipe.
    """
    argv: tuple[str, ...]
    cwd: str
    environment: dict[str, str]


async def relay(main_launch, host_launch, reader, writer):
    children = {}
    tasks = []
    output_lock = asyncio.Lock()
    initialized = asyncio.Event()
    initialization = None
    main_init = asyncio.get_running_loop().create_future()
    host_init = asyncio.get_running_loop().create_future()

    async def output(line):
        async with output_lock:
            writer.write(line)
            await writer.drain()

    async def send(role, line):
        children[role].stdin.write(line)
        await children[role].stdin.drain()

    def frame(line):
        if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
            raise RuntimeError("Incomplete or oversized multiplexed RPC frame")
        return decode_message(line)

    async def to_servers():
        nonlocal initialization
        try:
            while line := await reader.readline():
                message = frame(line)
                if initialization is None and message.get("method") == "initialize" and "id" in message:
                    initialization = message["id"]
                    await asyncio.gather(send("main", line), send("host", line))
                    # Publish one actual response only after both official
                    # initializations have succeeded. Never forge capabilities.
                    primary, companion = await asyncio.gather(main_init, host_init)
                    chosen = primary if "error" in frame(primary) else companion if "error" in frame(companion) else primary
                    await output(chosen)
                    initialized.set()
                    if "error" in frame(chosen):
                        raise RuntimeError("An official multiplexed initialization failed")
                    continue
                if message.get("method") == "initialized" and "id" not in message:
                    await asyncio.gather(send("main", line), send("host", line))
                else:
                    await send(destination(message), line)
        finally:
            for child in children.values():
                child.stdin.close()

    async def from_server(role):
        response = main_init if role == "main" else host_init
        while line := await children[role].stdout.readline():
            message = frame(line)
            if (initialization is not None and not response.done()
                    and "method" not in message and message.get("id") == initialization):
                response.set_result(line)
                # Keep each server's response-before-notification order even
                # if the companion takes longer to initialize.
                await initialized.wait()
                continue
            if role == "main" or "method" not in message:
                await output(line)
            elif "id" in message:
                # Audited host families emit responses/notifications, not
                # requests for UI decisions. Do not confuse a second server's
                # IDs with the main server's approval namespace.
                raise RuntimeError("Host companion emitted an unaudited server request")
            elif message["method"] in HOST_NOTIFICATIONS:
                await output(line)
            # Main is authoritative for account, task and global state. Host
            # startup notifications for those unrelated subsystems cannot
            # overwrite the main instance's UI state.
        if not response.done():
            response.set_exception(RuntimeError("Official child closed before initialize response"))

    loop = asyncio.get_running_loop()
    installed_signals = []
    try:
        for role, launch in (("main", main_launch), ("host", host_launch)):
            children[role] = await asyncio.create_subprocess_exec(*launch.argv,
                cwd=launch.cwd, env=dict(launch.environment), stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, limit=MAX_MESSAGE_BYTES + 1)
        def stop(signum):
            for child in children.values():
                if child.returncode is None:
                    child.send_signal(signum)
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop, signum)
            installed_signals.append(signum)
        inbound = asyncio.create_task(to_servers())
        outbound = [asyncio.create_task(from_server(role)) for role in ("main", "host")]
        exits = [asyncio.create_task(child.wait()) for child in children.values()]
        tasks = [inbound, *outbound, *exits]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if inbound in done:
            # Both official connection owners receive EOF and perform their
            # own watch/process cleanup. Their final output is still drained.
            await asyncio.wait_for(asyncio.gather(*exits), 30)
            await asyncio.gather(*outbound)
            return tuple(task.result() for task in exits)
        raise RuntimeError("An official child stopped before client EOF")
    finally:
        for signum in installed_signals:
            loop.remove_signal_handler(signum)
        initialized.set()
        for task in tasks:
            if task is not None:
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        async def discard_stdout(child):
            while await child.stdout.read(65536):
                pass
        drains = [asyncio.create_task(discard_stdout(child)) for child in children.values()]
        for child in children.values():
            if child.stdin is not None:
                child.stdin.close()
        # Close the surviving counterpart as well; do not leave one half of a
        # connection accepting operations after the other failed.
        for child in children.values():
            if child.returncode is None:
                try:
                    await asyncio.wait_for(child.wait(), 30)
                except asyncio.TimeoutError:
                    child.terminate()
                    try:
                        await asyncio.wait_for(child.wait(), 15)
                    except asyncio.TimeoutError:
                        child.kill()
                        await child.wait()
        await asyncio.gather(*drains, return_exceptions=True)
        for future in (main_init, host_init):
            if not future.done():
                future.cancel()
            elif not future.cancelled():
                future.exception()


async def stdio(main_launch, host_launch):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES + 1)
    transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    write_transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout.buffer)
    writer = asyncio.StreamWriter(write_transport, protocol, None, loop)
    try:
        return await relay(main_launch, host_launch, reader, writer)
    finally:
        transport.close()
        writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--official-sha256", required=True)
    parser.add_argument("--main-launch", type=Path, required=True)
    parser.add_argument("--host-launch", type=Path, required=True)
    args = parser.parse_args()
    official = args.official.resolve(strict=True)
    if hashlib.sha256(official.read_bytes()).hexdigest() != args.official_sha256:
        raise RuntimeError("Official executable differs from the supervisor's authenticated digest")
    launches = []
    for path in (args.main_launch, args.host_launch):
        value = json.loads(path.read_text())
        if type(value) is not dict or set(value) != {"argv", "cwd", "environment"}:
            raise ValueError("An exact supervisor-owned launch is required")
        if (type(value["argv"]) is not list or not value["argv"]
                or any(type(arg) is not str or "\0" in arg for arg in value["argv"])
                or Path(value["argv"][0]).resolve(strict=True) != official
                or type(value["environment"]) is not dict
                or any(type(key) is not str or not key or "=" in key or "\0" in key
                       or type(item) is not str or "\0" in item for key, item in value["environment"].items())
                or type(value["cwd"]) is not str or not Path(value["cwd"]).is_absolute()):
            raise ValueError("Invalid explicit official launch")
        if value["argv"][1:] != ["app-server", "--listen", "stdio://"]:
            raise ValueError("Diagnostic CLI requires the audited official stdio app-server launch")
        launches.append(Launch(tuple(value["argv"]), value["cwd"], value["environment"]))
    statuses = asyncio.run(stdio(*launches))
    return 0 if statuses == (0, 0) else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Exceptions can contain filesystem paths or user RPC data. Emit only
        # the class and leave detailed synthetic evidence to the verifier.
        print("FoldGPT host multiplexing failed (" + type(error).__name__ + ").", file=sys.stderr)
        raise SystemExit(1)
