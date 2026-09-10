"""Real nonroot native helper and socket tests of the separate bootstrap channel."""
import array
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import unittest

from tools.executor import test_native_bootstrap_files as fixture
from tools.executor.native_bootstrap_channel import BootstrapReadChannel, ChannelViolation, MAX_PACKET_BYTES


class ChannelTests(fixture.BootstrapReadTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.client, endpoint = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        self.client.setblocking(False)
        self.channel = BootstrapReadChannel(endpoint, self.authority,
            peer=(os.getpid(), os.getuid(), os.getgid()))
        self.serving = asyncio.create_task(self.channel.run())
        self.number = 0
        ready = await self.receive()
        self.assertEqual(ready["sessionId"], self.server.session_id)
        self.assertEqual(ready["discoveryRoot"], self.workspace.as_uri())

    async def asyncTearDown(self):
        self.client.close()
        await asyncio.wait_for(asyncio.gather(self.serving, return_exceptions=True), 5)
        await super().asyncTearDown()

    async def receive(self):
        data = await asyncio.wait_for(asyncio.get_running_loop().sock_recv(self.client, MAX_PACKET_BYTES), 5)
        return json.loads(data)

    async def send(self, request):
        await asyncio.get_running_loop().sock_sendall(self.client, json.dumps(request).encode())

    async def call(self, operation, suffix, **options):
        self.number += 1
        await self.send(dict(id=self.number, op=operation, path=self.workspace.as_uri() + suffix, **options))
        data, index = bytearray(), 0
        while True:
            packet = await self.receive()
            self.assertEqual(packet["id"], self.number)
            if packet["type"] == "chunk":
                self.assertEqual(packet["index"], index)
                data.extend(base64.b64decode(packet["dataBase64"], validate=True)); index += 1
            else:
                if packet["type"] == "result" and operation in ("readFile", "readDirectory"):
                    self.assertEqual(packet["result"], dict(bytes=len(data), chunks=index))
                return packet, bytes(data)

    async def test_channel_reads_real_binary_metadata_directory_and_missing(self):
        expected = bytes(range(256)) * 273 + bytes(range(112))
        (self.workspace / "binary").write_bytes(expected)
        result, data = await self.call("readFile", "/binary")
        self.assertEqual(data, expected); self.assertEqual(result["result"]["chunks"], 3)
        result, _ = await self.call("getMetadata", "/binary", followSymlinks=False)
        self.assertEqual(result["result"]["size"], len(expected))
        result, _ = await self.call("canonicalize", "/.codex")
        self.assertEqual(result["result"], dict(path=(self.workspace / ".codex").as_uri()))
        _, data = await self.call("readDirectory", "/.codex")
        self.assertEqual(json.loads(data), dict(entries=[dict(fileName="config.toml", isDirectory=False, isFile=True)]))
        for operation, options in (("readDirectory", {}), ("readFile", {}), ("getMetadata", dict(followSymlinks=True))):
            result, _ = await self.call(operation, "/missing", **options)
            self.assertEqual(result["error"]["code"], -32004)
        result, _ = await self.call("getMetadata", "/../outside", followSymlinks=True)
        self.assertNotEqual(result["error"]["code"], -32004)
        _, actual = await self.call("readFile", "/binary")
        self.assertEqual(actual, expected)

    async def test_read_directory_checks_actual_kind_permissions_and_aliases(self):
        result, _ = await self.call("readDirectory", "/binary")
        self.assertIn("error", result)
        secret = self.workspace / "private/secret"; secret.chmod(0)
        try:
            result, _ = await self.call("readFile", "/private/secret")
            self.assertNotEqual(result["error"]["code"], -32004)
        finally:
            secret.chmod(0o600)
        alias = self.workspace / "alias"; alias.symlink_to(self.parent / "outside")
        try:
            for follow in (True, False):
                result, _ = await self.call("getMetadata", "/alias", followSymlinks=follow)
                self.assertIn("error", result)
            result, _ = await self.call("readDirectory", "")
            self.assertIn("error", result)
        finally:
            alias.unlink()

    async def test_forged_policy_or_bootstrap_fields_close_channel(self):
        await self.send(dict(id=1, op="readFile", path=self.workspace.as_uri() + "/binary", sandbox=None))
        with self.assertRaises(ChannelViolation): await asyncio.wait_for(self.serving, 5)
        self.assertIsNone(self.owner.files.process)

    async def test_peer_identity_is_checked_by_kernel_credentials(self):
        self.channel.peer = (os.getpid() + 1, os.getuid(), os.getgid())
        await self.send(dict(id=1, op="readFile", path=self.workspace.as_uri() + "/binary"))
        with self.assertRaises(ChannelViolation): await asyncio.wait_for(self.serving, 5)

    async def test_descriptor_transfer_is_closed_without_dispatch(self):
        with (self.workspace / "binary").open("rb") as source:
            before = len(os.listdir("/proc/self/fd"))
            self.client.sendmsg([b"{}"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [source.fileno()]))])
            with self.assertRaises(ChannelViolation): await asyncio.wait_for(self.serving, 5)
            self.assertEqual(len(os.listdir("/proc/self/fd")), before - 1)

    async def test_disconnect_and_pipelining_reap_actual_paused_helper(self):
        self.owner.files.helper = fixture.PAUSED
        await self.send(dict(id=1, op="readFile", path=self.workspace.as_uri() + "/binary"))
        for _ in range(200):
            if self.owner.files.process is not None: break
            await asyncio.sleep(0.005)
        helper = self.owner.files.process; self.assertIsNotNone(helper)
        await self.send(dict(id=2, op="readFile", path=self.workspace.as_uri() + "/binary"))
        with self.assertRaises(ChannelViolation): await asyncio.wait_for(self.serving, 5)
        self.assertIsNotNone(helper.returncode)
        self.assertFalse(Path(f"/proc/{helper.pid}").exists())
        self.assertIsNone(self.owner.files.process)
        self.assertFalse(self.owner.files.lock.locked())

    async def test_disconnect_reaps_actual_paused_helper(self):
        self.owner.files.helper = fixture.PAUSED
        await self.send(dict(id=1, op="readFile", path=self.workspace.as_uri() + "/binary"))
        for _ in range(200):
            if self.owner.files.process is not None: break
            await asyncio.sleep(0.005)
        helper = self.owner.files.process; self.assertIsNotNone(helper)
        self.client.close()
        await asyncio.wait_for(self.serving, 5)
        self.assertIsNotNone(helper.returncode)
        self.assertIsNone(self.owner.files.process)
        self.assertFalse(self.owner.files.lock.locked())


if __name__ == "__main__": unittest.main(verbosity=2)
