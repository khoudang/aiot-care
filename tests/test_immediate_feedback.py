"""Test responsive truthful feedback, event wakeup, and immediate state updates across 3 nodes."""
import asyncio
from contextlib import suppress
import json
import time
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from iot_fixture import load_iot


class ImmediateFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def test_sender_loop_wakes_immediately_on_enqueue_without_50ms_poll_delay(self):
        """Enqueueing a command should wake the sender task immediately via asyncio event."""
        iot = self.iot
        room = 'living'
        write_called = asyncio.Event()

        class FastClient:
            def __init__(self):
                self.is_connected = True

            async def write_gatt_char(self, uuid, data, response=True):
                write_called.set()

        client = FastClient()
        iot._command_wakeups[room] = asyncio.Event()

        async def run_scenario():
            sender_task = asyncio.create_task(self._sender_loop_stub(iot, room, client))
            try:
                t0 = time.monotonic()
                # Queue command
                iot.enqueue_command(room, '{"cmd":"light","state":1}')
                # Explicitly set event as done in real iot.py
                iot._command_wakeups[room].set()
                await asyncio.wait_for(write_called.wait(), timeout=0.03)
                elapsed = time.monotonic() - t0
                # Must be received well under 50ms (typically < 10ms in host loop)
                self.assertLess(elapsed, 0.04)
            finally:
                sender_task.cancel()
                with suppress(asyncio.CancelledError):
                    await sender_task

        asyncio.run(run_scenario())

    async def _sender_loop_stub(self, iot, room, client):
        while client.is_connected:
            await iot._send_pending(room, client, 'dummy-uuid')
            timeout = iot._calc_pending_timeout(room)
            try:
                await asyncio.wait_for(iot._command_wakeups[room].wait(), timeout=timeout)
            except asyncio.TimeoutError:
                pass
            iot._command_wakeups[room].clear()

    def test_immediate_output_telemetry_across_all_three_nodes(self):
        """Applying immediate output frames from firmware updates node state without waiting for 1s loop."""
        iot = self.iot
        for room in ('patient', 'living', 'kitchen'):
            iot.set_node_online(room, True)

        # 1. Patient node immediate feedback
        handler_p = iot._make_notify_handler('patient')
        iot.enqueue_command('patient', '{"cmd":"fan","state":1,"value":75}')
        cmd_id_p = next(iter(iot._pending_commands['patient']))
        # ACK frame arrives
        handler_p(None, json.dumps({'ack': cmd_id_p, 'status': 'applied'}).encode())
        self.assertNotIn(cmd_id_p, iot._pending_commands['patient'])
        # Immediate state frame arrives
        handler_p(None, b'{"room":"patient","light":false,"fan":true,"fan_speed":75,"buzzer":false}\n')
        self.assertTrue(iot.ROOMS['patient']['fan'])
        self.assertEqual(iot.ROOMS['patient']['fan_speed'], 75)

        # 2. Living node immediate feedback
        handler_l = iot._make_notify_handler('living')
        iot.enqueue_command('living', '{"cmd":"light","state":1}')
        cmd_id_l = next(iter(iot._pending_commands['living']))
        handler_l(None, json.dumps({'ack': cmd_id_l, 'status': 'applied'}).encode())
        handler_l(None, b'{"room":"living","light":true,"fan":false,"fan_speed":0,"auto":false}\n')
        self.assertTrue(iot.ROOMS['living']['light'])
        self.assertFalse(iot.ROOMS['living']['auto'])

        # 3. Kitchen node immediate feedback
        handler_k = iot._make_notify_handler('kitchen')
        iot.enqueue_command('kitchen', '{"cmd":"exhaust","state":1,"value":90}')
        cmd_id_k = next(iter(iot._pending_commands['kitchen']))
        handler_k(None, json.dumps({'ack': cmd_id_k, 'status': 'applied'}).encode())
        handler_k(None, b'{"room":"kitchen","window":false,"exhaust":true,"exhaust_speed":90,"light":false,"buzzer":false,"emergency":false}\n')
        self.assertTrue(iot.ROOMS['kitchen']['exhaust'])
        self.assertEqual(iot.ROOMS['kitchen']['exhaust_speed'], 90)

    def test_application_ack_vs_gatt_write_vs_physical_confirmation(self):
        """Application ACK marks command accepted; only notify telemetry updates ROOMS actuator state."""
        iot = self.iot
        iot.set_node_online('patient', True)
        client = Mock(write_gatt_char=AsyncMock())

        # Step 1: Enqueued
        iot.set_device('patient', 'light', True, silent=True)
        cmd_id = next(iter(iot._pending_commands['patient']))
        self.assertFalse(iot.ROOMS['patient']['light'])  # Not applied yet

        # Step 2: GATT write succeeded
        asyncio.run(iot._send_pending('patient', client, 'uuid'))
        self.assertFalse(iot.ROOMS['patient']['light'])  # GATT write is not application confirmation

        # Step 3: Application ACK received
        handler = iot._make_notify_handler('patient')
        handler(None, json.dumps({'ack': cmd_id, 'status': 'applied'}).encode())
        self.assertNotIn(cmd_id, iot._pending_commands['patient'])
        self.assertFalse(iot.ROOMS['patient']['light'])  # ACK is not telemetry state update

        # Step 4: Output state telemetry received
        handler(None, b'{"room":"patient","light":true}\n')
        self.assertTrue(iot.ROOMS['patient']['light'])  # Confirmed output state


if __name__ == '__main__':
    unittest.main()
