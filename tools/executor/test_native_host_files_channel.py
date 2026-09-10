"""Actual nonroot socket/credential/helper qualification of host file transport."""
import array
import asyncio
import base64
import json
import os
from pathlib import Path
import socket
import struct
import unittest

from tools.executor import test_native_host_files as fixture
from tools.executor.native_bootstrap_files import create_bootstrap_read_authority
from tools.executor.native_host_files_channel import (
    HostFileChannel, ChannelViolation, SCHEMA, CHUNK_BYTES, MAX_DATA_BYTES, MAX_PACKET_BYTES, OPERATIONS,
)
from tools.executor.native_processes import _fd_ready


class HostChannelTests(fixture.HostFileTests):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.client = self.serving = None
        await self.reset_channel()

    async def reset_channel(self):
        if self.client is not None:
            self.client.close()
            await asyncio.wait_for(asyncio.gather(self.serving, return_exceptions=True), 5)
        self.client, endpoint = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        self.client.setsockopt(socket.SOL_SOCKET, socket.SO_PASSCRED, 1)
        self.client.setblocking(False)
        self.channel = HostFileChannel(endpoint, self.authority, peer=(os.getpid(), os.getuid(), os.getgid()))
        self.serving = asyncio.create_task(self.channel.run())
        self.number = 0
        self.assertEqual(await self.receive(), {
            "type": "ready", "schema": SCHEMA, "sessionId": self.server.session_id,
            "workspaceRoot": self.uri(), "chunkBytes": CHUNK_BYTES,
            "maxDataBytes": MAX_DATA_BYTES, "maxPacketBytes": MAX_PACKET_BYTES, "operations": list(OPERATIONS),
        })
        self.assertFalse(self.channel.socket.get_inheritable())

    async def asyncTearDown(self):
        self.client.close()
        await asyncio.wait_for(asyncio.gather(self.serving, return_exceptions=True), 5)
        await super().asyncTearDown()

    async def receive(self):
        async def packet():
            while True:
                try:
                    data, controls, flags, _ = self.client.recvmsg(MAX_PACKET_BYTES, socket.CMSG_SPACE(12))
                    break
                except BlockingIOError:
                    await _fd_ready(self.client.fileno())
            self.assertEqual(flags, 0)
            self.assertEqual(len(controls), 1)
            level, kind, payload = controls[0]
            self.assertEqual((level, kind), (socket.SOL_SOCKET, socket.SCM_CREDENTIALS))
            self.assertEqual(struct.unpack("iII", payload), (os.getpid(), os.getuid(), os.getgid()))
            return json.loads(data)
        return await asyncio.wait_for(packet(), 5)

    async def send(self, request):
        data = request if isinstance(request, bytes) else json.dumps(request).encode()
        await asyncio.wait_for(asyncio.get_running_loop().sock_sendall(self.client, data), 5)

    async def terminal(self, op):
        data, index = bytearray(), 0
        while True:
            packet = await self.receive()
            self.assertEqual(packet["id"], self.number)
            if packet["type"] == "chunk":
                self.assertEqual(set(packet), {"type", "id", "index", "dataBase64"})
                self.assertEqual(packet["index"], index)
                chunk = base64.b64decode(packet["dataBase64"], validate=True)
                self.assertTrue(0 < len(chunk) <= CHUNK_BYTES)
                data.extend(chunk); index += 1
            else:
                if packet["type"] == "result" and op in ("readFile", "readDirectory"):
                    self.assertEqual(packet["result"], {"bytes": len(data), "chunks": index})
                return packet, bytes(data)

    async def call(self, op, name="", **options):
        self.number += 1
        await self.send({"id": self.number, "op": op, "path": self.uri(name), **options})
        return await self.terminal(op)

    async def write_header(self, data, *, name="existing"):
        self.number += 1
        await self.send({"id": self.number, "op": "writeFile", "path": self.uri(name), "bytes": len(data),
                         "chunks": (len(data) + CHUNK_BYTES - 1) // CHUNK_BYTES})

    async def write(self, data, *, name="existing"):
        await self.write_header(data, name=name)
        for index, offset in enumerate(range(0, len(data), CHUNK_BYTES)):
            await self.send({"type": "chunk", "id": self.number, "index": index,
                            "dataBase64": base64.b64encode(data[offset:offset + CHUNK_BYTES]).decode()})
        await self.send({"type": "commit", "id": self.number})
        return await self.terminal("writeFile")

    async def violation(self):
        with self.assertRaises(ChannelViolation): await asyncio.wait_for(self.serving, 5)
        self.assertIsNone(self.owner.files.process)
        self.assertFalse(self.owner.files.lock.locked())
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
        fixture.OBSERVATIONS.append({"test": self.id(), "protocolRefused": True,
                                     "destinationUnchanged": True, "helperReaped": True})

    async def wait_for_helper(self):
        for _ in range(200):
            if self.owner.files.process is not None: break
            await asyncio.sleep(0.005)
        helper = self.owner.files.process
        self.assertIsNotNone(helper)
        self.assertIsNone(helper.returncode)
        return helper

    async def test_channel_real_chunked_write_read_metadata_directory_and_canonicalization(self):
        data = bytes(range(256)) * 513 + b"\x00\xffend"
        result, _ = await self.write(data, name="new binary")
        self.assertEqual(result["result"], {})
        self.assertEqual((self.workspace / "new binary").read_bytes(), data)
        result, read = await self.call("readFile", "new binary")
        self.assertEqual(read, data)
        self.assertEqual(result["result"]["chunks"], 5)
        result, _ = await self.call("getMetadata", "new binary", followSymlinks=False)
        self.assertEqual(result["result"]["size"], len(data))
        result, _ = await self.call("canonicalize", "new binary")
        self.assertEqual(result["result"], {"path": self.uri("new binary")})
        result, _ = await self.call("createDirectory", "project/nested", recursive=True)
        self.assertEqual(result["result"], {})
        _, read = await self.call("readDirectory", "project")
        self.assertEqual(json.loads(read), {"entries": [{"fileName": "nested", "isDirectory": True, "isFile": False}]})
        result, _ = await self.write(b"human edit", name="private/secret")
        self.assertEqual(result["result"], {})
        self.assertIn("error", await self.model("fs/readFile", "private/secret", sandbox=self.policy()))

    async def test_empty_write_requires_explicit_commit_before_truncation(self):
        await self.write_header(b"")
        await asyncio.sleep(0.02)
        self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
        self.assertIsNone(self.owner.files.process)
        await self.send({"type": "commit", "id": self.number})
        result, _ = await self.terminal("writeFile")
        self.assertEqual(result["result"], {})
        self.assertEqual((self.workspace / "existing").read_bytes(), b"")

    async def test_exact_maximum_payload_is_written_and_read_natively(self):
        data = bytes(range(256)) * (MAX_DATA_BYTES // 256)
        result, _ = await self.write(data, name="maximum")
        self.assertEqual(result["result"], {})
        self.assertEqual((self.workspace / "maximum").read_bytes(), data)
        result, actual = await self.call("readFile", "maximum")
        self.assertEqual(actual, data)
        self.assertEqual(result["result"], {"bytes": MAX_DATA_BYTES, "chunks": 512})

    async def test_native_refusal_preserves_channel_and_next_sequence(self):
        for op, options in (("readFile", {}), ("canonicalize", {}), ("getMetadata", {"followSymlinks": True}),
                            ("readDirectory", {})):
            result, _ = await self.call(op, "absent", **options)
            self.assertEqual(result["error"]["code"], -32004)
        result, _ = await self.write(b"bad", name="absent/child")
        self.assertEqual(result["error"]["code"], -32004)
        result, _ = await self.write(b"bad", name="../outside")
        self.assertNotEqual(result["error"]["code"], -32004)
        result, _ = await self.call("createDirectory", "absent/child", recursive=False)
        self.assertEqual(result["error"]["code"], -32004)
        self.assertFalse((self.workspace / "absent").exists())
        _, data = await self.call("readFile", "existing")
        self.assertEqual(data, b"old value")
        self.assertEqual((self.parent / "outside").read_bytes(), b"outside unchanged")

    async def test_bad_headers_and_json_never_admit_mutation(self):
        header = {"id": 1, "op": "writeFile", "path": self.uri("existing"), "bytes": 2, "chunks": 1}
        cases = [{**header, **change} for change in (
            {"bytes": MAX_DATA_BYTES + 1}, {"bytes": -1}, {"bytes": True}, {"chunks": True},
            {"chunks": 0}, {"chunks": 513}, {"id": True}, {"id": 0}, {"id": 2},
            {"sandbox": None}, {"authority": "host"}, {"sessionId": self.server.session_id},
            {"op": "unknown"}, {"path": None},
        )]
        cases += [b'{"id":1,"id":1}', b'{"id":NaN}', b'[]', b'\xff', b'{"id":']
        for case in cases:
            with self.subTest(case=str(case)[:120]):
                await self.reset_channel()
                await self.send(case)
                await self.violation()

    async def test_invalid_chunks_commit_and_replayed_indices_never_mutate(self):
        valid = {"type": "chunk", "id": 1, "index": 0, "dataBase64": "YWI="}
        cases = [[{**valid, **change}] for change in (
            {"id": 2}, {"id": True}, {"index": 1}, {"index": True}, {"type": "commit"},
            {"dataBase64": "YWJ="}, {"dataBase64": "!!!!"}, {"dataBase64": "YQ=="},
            {"dataBase64": "YWJj"}, {"dataBase64": "YWI=\n"}, {"extra": True},
        )]
        cases += [[valid, valid], [valid, {"type": "commit", "id": 2}],
                  [valid, {"type": "commit", "id": True}], [valid, {"type": "commit", "id": 1, "extra": 0}]]
        for packets in cases:
            with self.subTest(packets=packets):
                await self.reset_channel()
                await self.write_header(b"ab")
                for packet in packets: await self.send(packet)
                await self.violation()

    async def test_early_commit_and_new_request_during_payload_are_fatal(self):
        for packet in ({"type": "commit", "id": 1}, {"id": 2, "op": "readFile", "path": self.uri("existing")}):
            await self.reset_channel()
            await self.write_header(b"x" * (CHUNK_BYTES + 1))
            await self.send({"type": "chunk", "id": 1, "index": 0,
                             "dataBase64": base64.b64encode(b"x" * CHUNK_BYTES).decode()})
            await self.send(packet)
            await self.violation()

    async def test_replayed_request_id_is_refused_after_terminal_response(self):
        await self.call("readFile", "existing")
        await self.send({"id": 1, "op": "writeFile", "path": self.uri("existing"), "bytes": 0, "chunks": 0})
        await self.violation()

    async def test_eof_and_cancellation_before_commit_preserve_destination(self):
        for action in ("EOF", "cancel"):
            await self.reset_channel()
            await self.write_header(b"ab")
            await self.send({"type": "chunk", "id": 1, "index": 0, "dataBase64": "YWI="})
            await asyncio.sleep(0.02)
            self.assertIsNone(self.owner.files.process)
            self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
            if action == "EOF":
                self.client.close()
                await asyncio.wait_for(self.serving, 5)
            else:
                self.serving.cancel(); self.serving.cancel()
                with self.assertRaises(asyncio.CancelledError): await self.serving
            self.assertIsNone(self.owner.files.process)
            self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")

    async def test_foreign_process_credentials_on_chunk_are_rejected(self):
        await self.write_header(b"ab")
        process = os.fork()
        if process == 0:
            try:
                self.client.sendmsg([b'{"type":"chunk","id":1,"index":0,"dataBase64":"YWI="}'])
            except BaseException: os._exit(1)
            os._exit(0)
        _, status = await asyncio.to_thread(os.waitpid, process, 0)
        self.assertEqual(os.waitstatus_to_exitcode(status), 0)
        await self.violation()

    async def test_received_descriptors_are_closed_and_packet_truncation_refused(self):
        with (self.workspace / "existing").open("rb") as source:
            before = len(os.listdir("/proc/self/fd"))
            self.client.sendmsg([b"{}"], [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [source.fileno()]))])
            await self.violation()
            self.assertEqual(len(os.listdir("/proc/self/fd")), before - 1)
        await self.reset_channel()
        await self.send(b" " * (MAX_PACKET_BYTES + 1))
        await self.violation()

    async def test_eof_cancellation_and_pipelining_after_commit_reap_real_helper(self):
        original = self.owner.files.helper
        self.owner.files.helper = fixture.PAUSED
        try:
            for action in ("EOF", "cancel", "pipeline"):
                await self.reset_channel()
                await self.write_header(b"ab")
                await self.send({"type": "chunk", "id": 1, "index": 0, "dataBase64": "YWI="})
                await self.send({"type": "commit", "id": 1})
                helper = await self.wait_for_helper()
                if action == "EOF":
                    self.client.close()
                    await asyncio.wait_for(self.serving, 5)
                elif action == "cancel":
                    self.serving.cancel(); self.serving.cancel()
                    with self.assertRaises(asyncio.CancelledError): await self.serving
                else:
                    await self.send({"id": 2, "op": "readFile", "path": self.uri("existing")})
                    await self.violation()
                self.assertIsNotNone(helper.returncode)
                self.assertFalse(Path(f"/proc/{helper.pid}").exists())
                self.assertIsNone(self.owner.files.process)
                self.assertFalse(self.owner.files.lock.locked())
                self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
        finally:
            self.owner.files.helper = original

    async def test_constructor_does_not_accept_bootstrap_authority_or_stream_socket(self):
        bootstrap = create_bootstrap_read_authority(self.owner, session_id=self.server.session_id)
        with self.assertRaises(TypeError): HostFileChannel(self.client, bootstrap, peer=self.channel.peer)
        stream, other = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        with stream, other:
            with self.assertRaises(ValueError): HostFileChannel(stream, self.authority, peer=self.channel.peer)
        for peer in ((0, os.getuid(), os.getgid()), (True, os.getuid(), os.getgid()), [os.getpid(), os.getuid(), os.getgid()]):
            with self.assertRaises(ValueError): HostFileChannel(self.client, self.authority, peer=peer)

    async def test_committed_channel_write_waits_for_real_process_cleanup(self):
        params = {"processId": "channel-worker", "argv": ["bash", "--noprofile", "--norc", "-c", "printf READY; read value"],
            "cwd": self.uri(), "env": {"PATH": "/usr/bin:/bin", "HOME": str(self.workspace)},
            "tty": False, "pipeStdin": True, "sandbox": self.policy()}
        reply = await self.server.request({"id": 3, "method": "process/start", "params": params})
        self.assertIn("result", reply, reply)
        record = self.owner.processes.processes[(self.server.session_id, "channel-worker")]
        pending = None
        try:
            for _ in range(100):
                output = b"".join(base64.b64decode(chunk["chunk"]) for chunk, _ in record.output if chunk["stream"] == "stdout")
                if b"READY" in output: break
                await asyncio.sleep(0.01)
            self.assertIn(b"READY", output)
            pending = asyncio.create_task(self.write(b"after channel cleanup"))
            await asyncio.sleep(0.03)
            self.assertFalse(pending.done())
            self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
            result = await self.server.request({"id": 4, "method": "process/terminate", "params": {"processId": "channel-worker"}})
            self.assertIn("result", result)
            terminal, _ = await asyncio.wait_for(pending, 5)
            self.assertEqual(terminal["result"], {})
            await asyncio.wait_for(asyncio.shield(record.finished), 5)
            self.assertTrue(record.native_result["cleanupComplete"], record.native_result)
            self.assertEqual(record.native_result["outcome"], "cancelled")
            self.assertIsNotNone(record.process.returncode)
            self.assertFalse(Path(f"/proc/{record.process.pid}").exists())
            self.assertEqual((self.workspace / "existing").read_bytes(), b"after channel cleanup")
            fixture.OBSERVATIONS.append({"test": self.id(), "nativeResult": record.native_result,
                "supervisorReturncode": record.process.returncode, "throughHostChannel": True})
        finally:
            if not record.finished.done():
                await self.server.request({"id": 5, "method": "process/terminate", "params": {"processId": "channel-worker"}})
            if pending is not None and not pending.done():
                pending.cancel(); await asyncio.gather(pending, return_exceptions=True)

    async def test_quarantine_revokes_committed_channel_write_waiting_for_lease(self):
        await self.owner.processes.lease.acquire()
        pending = None
        try:
            pending = asyncio.create_task(self.write(b"bad"))
            await asyncio.sleep(0.03)
            self.assertFalse(pending.done())
            self.owner.processes.quarantined = True
            self.owner.processes.quarantine_event.set()
            terminal, _ = await asyncio.wait_for(pending, 5)
            self.assertEqual(terminal["error"]["code"], -32603)
            self.assertIsNone(self.owner.files.process)
            self.assertTrue(self.owner.files.lock.locked())
            self.assertEqual((self.workspace / "existing").read_bytes(), b"old value")
        finally:
            if pending is not None and not pending.done():
                pending.cancel(); await asyncio.gather(pending, return_exceptions=True)
            self.owner.processes.lease.release()


if __name__ == "__main__":
    try:
        unittest.main(verbosity=2)
    finally:
        output = os.environ.get("FOLDGPT_HOST_FILE_OBSERVATIONS")
        if output:
            Path(output).write_text(json.dumps({"uid": os.getuid(), "observations": fixture.OBSERVATIONS}, indent=2) + "\n")
