"""Opt-in stdio adapter around the untouched official Codex 0.153.4 binary.

Not installed by this module. Environment selection is the only modification;
host RPCs are passed through, retaining their current limitations. A production
launcher must additionally complete queued/Remote entry and native host routing.
"""
import argparse
import asyncio
import os
from pathlib import Path
import signal
import sys

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tools.executor.app_server_routing import EnvironmentRouter
from tools.executor.exec_server import MAX_MESSAGE_BYTES, RpcError, decode_message, encode_message

EXPECTED_VERSION = b"codex-cli 0.153.4"


async def relay(official, arguments, environment_id, cwd, reader, writer):
    """Bounded backpressure in both directions; no RPC payload is logged."""
    version = await asyncio.create_subprocess_exec(official, "--version", stdout=asyncio.subprocess.PIPE)
    try:
        data, _ = await asyncio.wait_for(version.communicate(), 15)
    except BaseException:
        if version.returncode is None:
            version.kill()
        await version.wait()
        raise
    if version.returncode != 0 or data.strip() != EXPECTED_VERSION:
        raise RuntimeError("Official Codex version needs a new FoldGPT routing review")
    router = EnvironmentRouter(environment_id, cwd)
    child = await asyncio.create_subprocess_exec(official, *arguments,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, limit=MAX_MESSAGE_BYTES + 1)
    output_lock = asyncio.Lock()

    async def output(data):
        async with output_lock:
            writer.write(data)
            await writer.drain()

    async def to_server():
        try:
            while line := await reader.readline():
                if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
                    raise RuntimeError("Incomplete or oversized client RPC frame")
                message = decode_message(line)
                try:
                    routed = router.outgoing(message)
                except RpcError as error:
                    if "id" not in message or "method" not in message:
                        raise
                    await output(encode_message(error.response(message["id"])) + b"\n")
                    continue
                child.stdin.write(line if routed is message else encode_message(routed) + b"\n")
                await child.stdin.drain()
        finally:
            child.stdin.close()

    async def to_client():
        while line := await child.stdout.readline():
            if len(line) > MAX_MESSAGE_BYTES or not line.endswith(b"\n"):
                raise RuntimeError("Incomplete or oversized official RPC frame")
            router.incoming(decode_message(line))
            # Every server response, error, approval request and notification
            # is forwarded byte-for-byte, including unknown future methods.
            await output(line)

    input_task = asyncio.create_task(to_server())
    output_task = asyncio.create_task(to_client())
    exit_task = asyncio.create_task(child.wait())
    loop = asyncio.get_running_loop()
    installed_signals = []

    def stop(signum):
        if child.returncode is None:
            child.send_signal(signum)

    try:
        for signum in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(signum, stop, signum)
            installed_signals.append(signum)
        done, _ = await asyncio.wait((input_task, output_task, exit_task), return_when=asyncio.FIRST_COMPLETED)
        for task in (input_task, output_task):
            if task in done:
                task.result()
        if input_task in done:
            # Official EOF owns its session teardown. No fake process exit or
            # local execution retry is emitted if it fails to finish.
            await asyncio.wait_for(asyncio.shield(exit_task), 15)
        elif output_task in done and not exit_task.done():
            await asyncio.wait_for(asyncio.shield(exit_task), 15)
        await output_task
        return await exit_task
    finally:
        for signum in installed_signals:
            loop.remove_signal_handler(signum)
        input_task.cancel()
        if child.returncode is None:
            child.terminate()
            try:
                await asyncio.wait_for(asyncio.shield(exit_task), 15)
            except asyncio.TimeoutError:
                child.kill()
                await exit_task
        output_task.cancel()
        await asyncio.gather(input_task, output_task, exit_task, return_exceptions=True)


async def stdio(official, arguments, environment_id, cwd):
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_MESSAGE_BYTES + 1)
    read_transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    write_transport, protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout.buffer)
    writer = asyncio.StreamWriter(write_transport, protocol, None, loop)
    try:
        return await relay(official, arguments, environment_id, cwd, reader, writer)
    finally:
        read_transport.close()
        writer.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official", type=Path, required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    official = str(args.official.resolve(strict=True))
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    if arguments in (["--version"], ["--help"], ["help"]):
        os.execv(official, [official, *arguments])
    if "app-server" not in arguments:
        raise RuntimeError("The FoldGPT adapter currently supports the app-server stdio launch only")
    for index, value in enumerate(arguments):
        if value.startswith("--listen=") and value != "--listen=stdio://":
            raise RuntimeError("The FoldGPT adapter requires a stdio app-server")
        if value == "--listen" and arguments[index + 1:index + 2] != ["stdio://"]:
            raise RuntimeError("The FoldGPT adapter requires a stdio app-server")
    return asyncio.run(stdio(official, arguments, args.environment, args.cwd))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        # Fixed error classes only: exceptions from a parser/transport can
        # contain user messages, paths or authentication data.
        print("FoldGPT routing failed (" + type(error).__name__ + "). See the routing contract.", file=sys.stderr)
        sys.exit(1)
