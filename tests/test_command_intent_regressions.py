"""Command regressions run with fake BLE and no hardware startup."""
import asyncio
import json
import unittest
import numpy  # Load before the fixture swaps sys.modules.
from unittest.mock import AsyncMock, Mock, patch
from iot_fixture import load_iot


class CommandIntentTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()
        self.iot.COMMAND_DEBOUNCE_SEC = 1.0

    def commands(self, room='living'):
        return [(ident, json.loads(p['text'])) for ident, p in self.iot._pending_commands[room].items()]

    def test_same_state_new_request_is_not_silently_dropped(self):
        with patch.object(self.iot, 'now_ts', return_value=100):
            self.iot.set_device('living', 'light', True, request_id='first', silent=True)
            self.iot.set_device('living', 'light', True, request_id='latest', silent=True)
        latest = [(ident, cmd) for ident, cmd in self.commands() if cmd.get('request_id') == 'latest']
        self.assertEqual(len(latest), 1, 'Each new correlated request must be acknowledged or explicitly rejected')
        handler = self.iot._make_notify_handler('living')
        handler(None, json.dumps({'ack':latest[0][0], 'status':'applied'}).encode())
        results = [c.args[1] for c in self.iot._emit.call_args_list if c.args[0] == 'command_result']
        self.assertTrue(any(r.get('request_id') == 'latest' and r.get('status') == 'applied' for r in results))

    def test_errors_identify_the_exact_request(self):
        for kind in ['invalid', 'locked', 'full', 'expired', 'rejected']:
            with self.subTest(kind=kind):
                iot = load_iot()
                room, device, request = 'living', 'auto', 'request-' + kind
                if kind == 'invalid':
                    device = 'not-a-device'
                if kind == 'locked':
                    iot._emergency_snapshot = {}
                if kind == 'full':
                    for _ in range(20):
                        self.assertTrue(iot.enqueue_command(room, '{"cmd":"auto","state":1}'))
                with patch.object(iot.time, 'monotonic', return_value=0):
                    iot.set_device(room, device, True, request_id=request, silent=True)
                if kind == 'expired':
                    with patch.object(iot.time, 'monotonic', return_value=31):
                        asyncio.run(iot._send_pending(room, Mock(write_gatt_char=AsyncMock()), 'uuid'))
                elif kind == 'rejected':
                    ident = next(iter(iot._pending_commands[room]))
                    iot._make_notify_handler(room)(None, json.dumps({'ack':ident,'status':'rejected'}).encode())
                errors = [c.args[1] for c in iot._emit.call_args_list if c.args[0] == 'command_error']
                self.assertTrue(errors)
                self.assertEqual((errors[-1].get('room'), errors[-1].get('device'), errors[-1].get('request_id')), (room, device, request))

    def test_relay_burst_keeps_latest_off_and_reports_superseded_requests(self):
        iot = self.iot
        iot.set_device('patient', 'buzzer', True, request_id='other-room', silent=True)
        burst_count = 100
        with patch.object(iot, 'now_ts', return_value=100):
            for n in range(burst_count):
                iot.set_device('living', 'light', bool(n % 2), request_id=f'burst-{n}', silent=True)
            iot.set_device('living', 'light', False, request_id='latest-off', silent=True)
        commands = self.commands()
        self.assertEqual(len(commands), 1, 'Do not replay a backlog of old relay transitions')
        self.assertEqual((commands[0][1]['request_id'], commands[0][1]['state']), ('latest-off', 0))
        self.assertEqual(iot.command_queues['living'].qsize(), 1)
        self.assertEqual(len(iot._pending_commands['patient']), 1)
        superseded = [c.args[1] for c in iot._emit.call_args_list if c.args[0] == 'command_result' and c.args[1].get('status') == 'superseded']
        self.assertEqual(len(superseded), burst_count)
        self.assertFalse(any(c.args[0] == 'command_error' for c in iot._emit.call_args_list))
        client = Mock(write_gatt_char=AsyncMock())
        asyncio.run(iot._send_pending('living', client, 'uuid'))
        self.assertEqual(json.loads(client.write_gatt_char.call_args.args[1])['state'], 0)

    def test_replaced_inflight_command_cannot_acknowledge_or_retry_the_new_intent(self):
        iot = self.iot
        client = Mock(write_gatt_char=AsyncMock())
        with patch.object(iot.time, 'monotonic', return_value=100):
            iot.set_device('living', 'light', True, request_id='old', silent=True)
            old = self.commands()[0][0]
            asyncio.run(iot._send_pending('living', client, 'uuid'))
            iot.set_device('living', 'light', False, request_id='new', silent=True)
            iot._make_notify_handler('living')(None, json.dumps({'ack':old,'status':'applied'}).encode())
        self.assertEqual(len(self.commands()), 1)
        self.assertEqual(self.commands()[0][1]['request_id'], 'new')
        applied = [c.args[1] for c in iot._emit.call_args_list if c.args[0] == 'command_result' and c.args[1].get('status') == 'applied']
        self.assertFalse(applied)

    def test_normal_relay_writes_are_spaced_without_delaying_safety_commands(self):
        iot = self.iot
        client = Mock(write_gatt_char=AsyncMock())
        handler = iot._make_notify_handler('living')
        with patch.object(iot.time, 'monotonic', return_value=100):
            iot.set_device('living', 'light', True, request_id='on', silent=True)
            ident = self.commands()[0][0]
            asyncio.run(iot._send_pending('living', client, 'uuid'))
            handler(None, json.dumps({'ack':ident,'status':'applied'}).encode())
        with patch.object(iot.time, 'monotonic', return_value=100.01):
            iot.set_device('living', 'light', False, request_id='off', silent=True)
            asyncio.run(iot._send_pending('living', client, 'uuid'))
            self.assertEqual(client.write_gatt_char.await_count, 1)
            self.assertGreaterEqual(iot._calc_pending_timeout('living'), .28)
        with patch.object(iot.time, 'monotonic', return_value=100.31):
            asyncio.run(iot._send_pending('living', client, 'uuid'))
            self.assertEqual(client.write_gatt_char.await_count, 2)
            ident = self.commands()[0][0]
            handler(None, json.dumps({'ack':ident,'status':'applied'}).encode())
            self.assertTrue(iot.enqueue_command('living', '{"cmd":"light","state":0}'))
            asyncio.run(iot._send_pending('living', client, 'uuid'))
            self.assertEqual(client.write_gatt_char.await_count, 3, 'Safety enqueue must bypass normal relay spacing')

    def test_legacy_retry_after_rejection_is_not_debounced(self):
        with patch.object(self.iot, 'now_ts', return_value=100):
            self.iot.set_device('living', 'light', True, silent=True)
        ident = self.commands()[0][0]
        self.iot._make_notify_handler('living')(None, json.dumps({'ack':ident,'status':'rejected'}).encode())
        with patch.object(self.iot, 'now_ts', return_value=100.5):
            self.iot.set_device('living', 'light', True, silent=True)
        self.assertEqual(len(self.commands()), 1, 'Rejected attempts must not suppress a real retry')
