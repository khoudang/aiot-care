import asyncio
import json
import unittest
from unittest.mock import AsyncMock, Mock, patch

from iot_fixture import load_iot


class DeliveryTests(unittest.TestCase):
    def test_safety_retries_without_disconnect_after_rejection_or_expiry(self):
        for failure in ('rejected', 'expired', 'exhausted', 'drift'):
            with self.subTest(failure=failure):
                iot = load_iot()
                client = Mock(write_gatt_char=AsyncMock())
                with patch.object(iot.time, 'monotonic', return_value=0):
                    iot._enter_emergency()
                snapshot = iot._emergency_snapshot
                handler = iot._make_notify_handler('patient')
                for ident in list(iot._pending_commands['patient']):
                    if failure == 'exhausted':
                        iot._pending_commands['patient'][ident].update(
                            created=39, sent=30, attempts=iot.COMMAND_ATTEMPTS)
                    elif failure != 'expired':
                        handler(None, json.dumps({'ack': ident, 'status':
                            'rejected' if failure == 'rejected' else 'applied'}).encode())
                iot.ROOMS['patient']['buzzer'] = False
                with patch.object(iot.time, 'monotonic', return_value=40):
                    for _ in range(4):
                        asyncio.run(iot._send_pending('patient', client, 'uuid'))
                commands = [json.loads(p['text']) for p in iot._pending_commands['patient'].values()]
                self.assertTrue(any(c['cmd'] == 'buzzer' and c['state'] == 1 for c in commands))
                self.assertIs(iot._emergency_snapshot, snapshot)
                iot.send_telegram_alert_async.assert_called_once()

    def setUp(self):
        self.iot = load_iot()

    def test_write_failure_reconnect_busy_then_application_ack(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=10):
            iot.set_device('patient', 'buzzer', True)
            first = Mock(write_gatt_char=AsyncMock(side_effect=OSError('disconnected')))
            with self.assertRaises(OSError):
                asyncio.run(iot._send_pending('patient', first, 'uuid'))
        ident = next(iter(iot._pending_commands['patient']))
        handler = iot._make_notify_handler('patient')
        handler(None, json.dumps({'ack': ident, 'status': 'busy'}).encode())
        second = Mock(write_gatt_char=AsyncMock())
        with patch.object(iot.time, 'monotonic', return_value=12):
            asyncio.run(iot._send_pending('patient', second, 'uuid'))
        self.assertEqual(first.write_gatt_char.call_args, second.write_gatt_char.call_args)
        handler(None, json.dumps({'ack': ident, 'status': 'applied'}).encode())
        self.assertFalse(iot._pending_commands['patient'])
        self.assertFalse(iot.ROOMS['patient']['buzzer'])  # ACK is not telemetry.

    def test_missing_ack_has_bounded_retries(self):
        iot = self.iot
        client = Mock(write_gatt_char=AsyncMock())
        with patch.object(iot.time, 'monotonic', return_value=0):
            iot.set_device('living', 'light', True)
        for tick in range(0, 12, 2):
            with patch.object(iot.time, 'monotonic', return_value=tick):
                asyncio.run(iot._send_pending('living', client, 'uuid'))
        self.assertEqual(client.write_gatt_char.await_count, iot.COMMAND_ATTEMPTS)
        self.assertFalse(iot._pending_commands['living'])
        self.assertTrue(any(c.args[0] == 'command_error' for c in iot._emit.call_args_list))

    def test_expired_commands_are_not_sent_after_reconnect(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=0):
            iot.set_device('living', 'light', True)
        client = Mock(write_gatt_char=AsyncMock())
        with patch.object(iot.time, 'monotonic', return_value=31):
            asyncio.run(iot._send_pending('living', client, 'uuid'))
        client.write_gatt_char.assert_not_awaited()

    def test_emergency_replaces_pending_manual_commands(self):
        iot = self.iot
        iot.set_device('living', 'light', True)
        old = set(iot._pending_commands['living'])
        iot._enter_emergency()
        self.assertFalse(old & set(iot._pending_commands['living']))
        self.assertTrue(all(json.loads(p['text'])['state'] == 0
                            for p in iot._pending_commands['living'].values()))

    def test_long_disconnect_rebuilds_current_safety_commands(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=0):
            iot._enter_emergency()
        snapshot = iot._emergency_snapshot
        old = set(iot._pending_commands['patient'])
        with patch.object(iot.time, 'monotonic', return_value=40):
            iot._resync_safety('patient')
            self.assertIs(iot._emergency_snapshot, snapshot)
            self.assertFalse(old & set(iot._pending_commands['patient']))
            commands = [json.loads(p['text']) for p in iot._pending_commands['patient'].values()]
            self.assertEqual([(c['cmd'], c['state']) for c in commands], [('fan', 0), ('buzzer', 1)])
            self.assertTrue(all(p['created'] == 40 for p in iot._pending_commands['patient'].values()))
        iot.send_telegram_alert_async.assert_called_once()

    def test_fall_reconnect_discards_stale_buzzer_off(self):
        iot = self.iot
        iot.set_device('patient', 'buzzer', False)
        iot.AI['fall'] = True
        iot._resync_safety('patient')
        commands = [json.loads(p['text']) for p in iot._pending_commands['patient'].values()]
        self.assertEqual(len(commands), 1)
        self.assertEqual((commands[0]['cmd'], commands[0]['state']), ('buzzer', 1))

    def test_malformed_and_wrong_node_ack_do_not_clear_command(self):
        iot = self.iot
        iot.set_device('living', 'light', True)
        ident = next(iter(iot._pending_commands['living']))
        handler = iot._make_notify_handler('living')
        handler(None, b'{"ack":[],"status":"applied"}\n')
        handler(None, json.dumps({'room': 'patient', 'ack': ident, 'status': 'applied'}).encode())
        self.assertIn(ident, iot._pending_commands['living'])
