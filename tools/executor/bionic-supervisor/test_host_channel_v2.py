"""Real multiplexed host channel with the actual native human process owner."""
import asyncio
import base64
import importlib
import json
import os
from pathlib import Path
import socket
import struct
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
kernel = importlib.import_module("tools.executor.bionic-supervisor.test_host_kernel")
host = importlib.import_module("tools.executor.bionic-supervisor.host_processes")
from tools.executor.native_host_channel_v2 import HostChannelV2, SCHEMA
from tools.executor.native_processes import _fd_ready


class Client:
    def __init__(self, endpoint):
        self.socket = endpoint
        endpoint.setblocking(False)
        endpoint.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        self.sequence, self.pending = 0, {}
        self.sender = asyncio.Lock()
        self.ready = asyncio.get_running_loop().create_future()
        self.reader = asyncio.create_task(self.receive())

    async def receive(self):
        try:
            while True:
                try:
                    packet, controls, flags, _ = self.socket.recvmsg(65536, socket.CMSG_SPACE(12))
                except BlockingIOError:
                    await _fd_ready(self.socket.fileno())
                    continue
                if not packet:
                    return
                if flags or controls != [(socket.SOL_SOCKET, socket.SCM_CREDENTIALS, struct.pack("iII", os.getpid(), os.getuid(), os.getgid()))]:
                    raise ValueError("Unexpected actual host credentials")
                value = json.loads(packet)
                if value["type"] == "ready":
                    if value["schema"] != SCHEMA:
                        raise ValueError("Unexpected host schema")
                    self.ready.set_result(value)
                    continue
                future, chunks = self.pending[value["id"]]
                if value["type"] == "chunk":
                    if value["index"] != len(chunks):
                        raise ValueError("Unexpected native file chunk ordering")
                    chunks.append(base64.b64decode(value["dataBase64"], validate=True))
                else:
                    self.pending.pop(value["id"])
                    if value["type"] == "error":
                        future.set_exception(RuntimeError(value["error"]["message"]))
                    else:
                        future.set_result((value["result"], b"".join(chunks)))
        finally:
            for future, _ in self.pending.values():
                if not future.done():
                    future.set_exception(BrokenPipeError("Host transport ended"))

    async def _packet(self, packet):
        encoded = json.dumps(packet, separators=(",", ":")).encode()
        while True:
            try:
                count = self.socket.send(encoded)
                if count != len(encoded):
                    raise ValueError("Partial native host request")
                return
            except BlockingIOError:
                await _fd_ready(self.socket.fileno(), writing=True)

    async def request(self, op, *, upload=None, **params):
        async with self.sender:
            self.sequence += 1
            identifier = self.sequence
            future = asyncio.get_running_loop().create_future()
            self.pending[identifier] = (future, [])
            if upload is not None:
                params.update(bytes=len(upload), chunks=(len(upload) + 32767) // 32768)
            await self._packet({"id": identifier, "op": op, **params})
            if upload is not None:
                for index, offset in enumerate(range(0, len(upload), 32768)):
                    await self._packet({"type": "chunk", "id": identifier, "index": index,
                        "dataBase64": base64.b64encode(upload[offset:offset + 32768]).decode()})
                await self._packet({"type": "commit", "id": identifier})
        return await future

    async def close(self):
        self.socket.close()
        self.reader.cancel()
        await asyncio.gather(self.reader, return_exceptions=True)


class HostChannelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await kernel.HostKernelTests.asyncSetUp(self)
        self.processes = host.HostProcesses(self.authority, str(kernel.BUILD / "host-runner"),
            runtime=self.runtime, executables={"cat": "/usr/bin/cat", "sh": "/usr/bin/bash"})
        native, controller = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.client = Client(controller)
        self.channel = HostChannelV2(native, self.authority, processes=self.processes,
            peer=(os.getpid(), os.getuid(), os.getgid()))
        self.serving = asyncio.create_task(self.channel.run())
        await asyncio.wait_for(self.client.ready, 3)

    async def asyncTearDown(self):
        await self.client.close()
        await asyncio.wait_for(self.serving, 15)
        await kernel.HostKernelTests.asyncTearDown(self)

    async def start(self, command, *, stdin=False):
        result, _ = await self.client.request("processStart", command=command, cwd="/",
            environment={"PATH": "/usr/bin:/bin"}, pipeStdin=stdin)
        return result["processId"]

    async def finish(self, key, prior=()):
        events = list(prior)
        while not events or events[-1]["type"] != "closed":
            result, _ = await asyncio.wait_for(self.client.request("processRead", processId=key), 10)
            events.append(result["event"])
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        self.assertIsNone(events[-1]["failure"])
        self.results.append({"events": events})
        return events

    async def test_waiting_file_write_cannot_block_real_native_process_termination(self):
        key = await self.start(["sh", "-c", "printf ready; sleep 20"])
        first, _ = await self.client.request("processRead", processId=key)
        self.assertEqual(base64.b64decode(first["event"]["dataBase64"]), b"ready")
        path = self.workspace / "after-termination"
        writing = asyncio.create_task(self.client.request("writeFile", path=path.as_uri(), upload=b"saved after native cleanup"))
        await asyncio.sleep(0)
        self.assertTrue(self.owner.files.lock.locked())
        self.assertFalse(writing.done())
        self.assertEqual(await asyncio.wait_for(self.client.request("processTerminate", processId=key), 3), ({}, b""))
        await self.finish(key, [first["event"]])
        self.assertEqual(await asyncio.wait_for(writing, 5), ({}, b""))
        self.assertEqual(path.read_bytes(), b"saved after native cleanup")

    async def test_real_editor_shell_save_eof_and_filesystem_read_share_exact_bytes(self):
        path = self.workspace / "editor.bin"
        data = bytes(range(256)) * 8193
        key = await self.start(["sh", "-c", 'cat > "$1"', "sh", str(path)], stdin=True)
        for offset in range(0, len(data), 32768):
            await self.client.request("processWrite", processId=key,
                dataBase64=base64.b64encode(data[offset:offset + 32768]).decode(), closeStdin=False)
        await self.client.request("processWrite", processId=key, dataBase64="", closeStdin=True)
        events = await self.finish(key)
        self.assertEqual([event["exitCode"] for event in events if event["type"] == "exited"], [0])
        result, actual = await self.client.request("readFile", path=path.as_uri())
        self.assertEqual(actual, data)
        self.assertEqual(result, {"bytes": len(data), "chunks": (len(data) + 32767) // 32768})
        self.assertEqual(path.read_bytes(), data)


if __name__ == "__main__":
    unittest.main()
