"""Bounded offline CDP/ordering checks; no phone, account or paid requests."""
import asyncio
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from foldgpt_ime import HOOK, Keyboard, Page


def event(context, visible=True, reason="focus", sequence=1):
    return {"method": "Runtime.bindingCalled", "params": {
        "name": "__foldgptImeSignal", "executionContextId": context,
        "payload": json.dumps({"visible": visible, "reason": reason, "sequence": sequence}),
    }}


class Socket:
    def __init__(self):
        self.messages = asyncio.Queue()
        self.sent = asyncio.Queue()

    async def send(self, message):
        await self.sent.put(json.loads(message))

    def __aiter__(self):
        return self

    async def __anext__(self):
        message = await self.messages.get()
        if message is None:
            raise StopAsyncIteration
        return json.dumps(message)


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.keyboard = Keyboard()
        self.page = Page({"id": "main"}, self.keyboard)

    async def test_existing_default_frames_injected_and_isolated_world_skipped(self):
        self.page.call = AsyncMock(return_value={})
        for ident, default in [(1, True), (2, True), (3, False)]:
            await self.page.handle({"method": "Runtime.executionContextCreated", "params": {
                "context": {"id": ident, "auxData": {"isDefault": default, "frameId": str(ident)}}}})
        self.assertEqual(set(self.page.contexts), {1, 2})
        self.assertEqual(self.page.call.await_count, 2)
        self.page.call.assert_any_await("Runtime.evaluate", {"expression": HOOK, "contextId": 2})

    async def test_navigation_clears_old_owner_and_accepts_new_sequence(self):
        self.page.contexts[1] = "frame"
        await self.page.handle(event(1, sequence=10))
        await self.page.handle({"method": "Runtime.executionContextsCleared"})
        self.assertIsNone(self.keyboard.owner)
        self.assertFalse(self.page.sequences)
        self.page.contexts[2] = "frame"
        await self.page.handle(event(2))
        self.assertEqual(self.keyboard.owner, ("main", 2))

    async def test_old_frame_blur_cannot_hide_new_frame(self):
        self.page.contexts = {1: "frame1", 2: "frame2"}
        await self.page.handle(event(1))
        await self.page.handle(event(2))
        await self.page.handle(event(1, False, "blur", 2))
        self.assertEqual(self.keyboard.owner, ("main", 2))
        self.assertEqual(self.keyboard.queue.qsize(), 2)
        # A genuine outside tap in the parent must still dismiss the child IME.
        await self.page.handle(event(1, False, "pointer", 3))
        self.assertIsNone(self.keyboard.owner)
        self.assertEqual(self.keyboard.queue.get_nowait()[0], True)
        self.assertEqual(self.keyboard.queue.get_nowait()[0], True)
        self.assertEqual(self.keyboard.queue.get_nowait()[0], False)

    async def test_untrusted_or_stale_metadata_does_not_change_state(self):
        self.page.contexts[1] = "frame"
        await self.page.handle(event(1, sequence=2))
        for invalid in [event(1, False, sequence=1), event(2), event(1, "true", sequence=3),
                        event(1, True, "UNEXPECTED_FIELD_CONTENT", 3), event(1, True, sequence=True)]:
            await self.page.handle(invalid)
        for payload in ["[]", "null", "not json", '"' + 'x' * 300 + '"']:
            invalid = event(1)
            invalid["params"]["payload"] = payload
            await self.page.handle(invalid)
        self.assertEqual(self.keyboard.queue.qsize(), 1)
        self.assertEqual(self.page.sequences[1], 2)

    async def test_calls_match_out_of_order_responses_and_receive_events(self):
        self.page.ws = Socket()
        reader = asyncio.create_task(self.page.read())
        first = asyncio.create_task(self.page.call("first"))
        second = asyncio.create_task(self.page.call("second"))
        one = await self.page.ws.sent.get()
        two = await self.page.ws.sent.get()
        await self.page.ws.messages.put(event(1))
        await self.page.ws.messages.put({"id": two["id"], "result": {"order": 2}})
        await self.page.ws.messages.put({"id": one["id"], "result": {"order": 1}})
        self.assertEqual(await first, {"order": 1})
        self.assertEqual(await second, {"order": 2})
        self.assertEqual((await self.page.events.get())["method"], "Runtime.bindingCalled")
        await self.page.ws.messages.put(None)
        await reader

    async def test_disconnect_fails_pending_call_without_timeout(self):
        self.page.ws = Socket()
        reader = asyncio.create_task(self.page.read())
        call = asyncio.create_task(self.page.call("Runtime.enable"))
        await self.page.ws.sent.get()
        await self.page.ws.messages.put(None)
        with self.assertRaises(ConnectionError):
            await asyncio.wait_for(call, 0.5)
        await reader
        self.assertFalse(self.page.pending)

    async def test_worker_coalesces_stale_intents_but_repeats_a_new_tap(self):
        applied = []
        self.keyboard.apply = lambda visible: applied.append(visible) or True
        self.keyboard.signal(("main", 1), True, "focus")
        self.keyboard.signal(("main", 1), False, "blur")
        self.keyboard.signal(("main", 2), True, "focus")
        worker = asyncio.create_task(self.keyboard.run())
        try:
            async with asyncio.timeout(1):
                while not applied:
                    await asyncio.sleep(0)
            self.assertEqual(applied, [True])
            self.keyboard.signal(("main", 2), True, "pointer")
            async with asyncio.timeout(1):
                while len(applied) < 2:
                    await asyncio.sleep(0)
            self.assertEqual(applied, [True, True])
        finally:
            worker.cancel()
            await asyncio.gather(worker, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
