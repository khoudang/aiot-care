import copy
import asyncio
import json
import queue
import unittest
from unittest.mock import AsyncMock, Mock, patch

from iot_fixture import load_iot
from node_protocol import build_command


class KitchenControlTests(unittest.TestCase):
    def trigger_fall(self):
        with patch.object(self.iot, 'now_ts', return_value=10):
            self.iot._handle_fall(True)
        with patch.object(self.iot, 'now_ts', return_value=20):
            self.iot._handle_fall(True)
        self.assertTrue(self.iot.AI['fall'])

    def acknowledge(self, room):
        handler = self.iot._make_notify_handler(room)
        for ident in list(self.iot._pending_commands[room]):
            handler(None, json.dumps({'ack': ident, 'status': 'applied'}).encode())

    def safe_kitchen(self):
        iot = self.iot
        iot._kitchen_safe_since = 100
        iot._kitchen_sample_at = 113
        iot._kitchen_emergency = False
        iot.alert_level = 'awaiting'

    def test_fall_during_restoration_preserves_fan_command(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=113):
            iot.ROOMS['patient'].update(fan=True, fan_speed=50)
            iot._enter_emergency()
            self.safe_kitchen()
            iot.confirm_safe()
            fan_ids = {ident for ident, p in iot._pending_commands['patient'].items()
                       if json.loads(p['text'])['cmd'] == 'fan'}
            self.trigger_fall()
            self.assertTrue(fan_ids <= set(iot._pending_commands['patient']))
            self.assertIsNotNone(iot._restoration_started)
            for room in ('patient', 'living'):
                iot.set_node_online(room, True)
                self.acknowledge(room)
            iot.apply_node_payload('patient', {'fan': True, 'fan_speed': 50, 'buzzer': True})
            iot.apply_node_payload('living', {'auto': True})
            self.assertIsNone(iot._emergency_snapshot)

    def test_overlapping_alert_lifecycles_do_not_reactivate_buzzer(self):
        for kitchen_first in (False, True):
            for clear_before_ack in (False, True):
                for saved in (False, True):
                    with self.subTest(kitchen_first=kitchen_first,
                                      clear_before_ack=clear_before_ack, saved=saved):
                        self.iot = iot = load_iot()
                        with patch.object(iot.time, 'monotonic', return_value=113):
                            iot.ROOMS['patient']['buzzer'] = saved
                            if kitchen_first:
                                iot._enter_emergency()
                                iot.ROOMS['patient']['buzzer'] = True
                            self.trigger_fall()
                            iot.ROOMS['patient']['buzzer'] = True
                            if not kitchen_first:
                                iot._enter_emergency()
                            if clear_before_ack:
                                iot._handle_fall(False)
                            for room in ('patient', 'living'):
                                self.acknowledge(room)
                                iot.set_node_online(room, True)
                            iot._handle_fall(False)
                            self.safe_kitchen()
                            iot.confirm_safe()
                            self.assertEqual(iot._patient_buzzer_target(), saved)
                            for room in ('patient', 'living'):
                                self.acknowledge(room)
                            iot.apply_node_payload('living', {'auto': True})
                            iot.apply_node_payload('patient', {
                                'fan': False, 'fan_speed': 0, 'buzzer': saved})
                            self.assertIsNone(iot._emergency_snapshot)
                            self.assertIsNone(iot._fall_buzzer_saved)
                            iot._reconcile_safety('patient')
                            self.assertFalse(iot._pending_commands['patient'])

    def test_fall_clears_after_restoration_ack_requires_new_confirmation(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=113):
            self.trigger_fall()
            iot.ROOMS['patient']['buzzer'] = True
            iot._enter_emergency()
            self.safe_kitchen()
            iot.confirm_safe()
            for room in ('patient', 'living'):
                iot.set_node_online(room, True)
                self.acknowledge(room)
            iot._handle_fall(False)
            # Clearing the classifier alone must not silently clear its latch.
            iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
            iot.apply_node_payload('living', {'auto': True})
            self.assertIsNone(iot._emergency_snapshot)
            self.assertIsNotNone(iot._fall_buzzer_saved)
            iot.confirm_safe()
            self.assertFalse(iot._patient_buzzer_target())
            self.acknowledge('patient')
            self.assertIsNotNone(iot._fall_buzzer_saved)
            iot.apply_node_payload('patient', {'buzzer': False})
            self.assertIsNone(iot._fall_buzzer_saved)
            iot._resync_safety('patient')
            self.assertFalse(iot._pending_commands['patient'])

    def test_fall_only_confirmation_waits_for_telemetry_without_kitchen(self):
        for saved in (False, True):
            iot = load_iot()
            iot.ROOMS['patient']['buzzer'] = saved
            with patch.object(iot, 'now_ts', return_value=10):
                iot._handle_fall(True)
            with patch.object(iot, 'now_ts', return_value=20):
                iot._handle_fall(True)
            iot.confirm_safe()
            self.assertIsNone(iot._fall_restore_target)  # Still suspect.
            iot._handle_fall(False)
            iot.confirm_safe()
            self.assertEqual(iot._fall_restore_target, saved)
            self.assertIsNotNone(iot._fall_buzzer_saved)
            handler = iot._make_notify_handler('patient')
            for ident in list(iot._pending_commands['patient']):
                handler(None, json.dumps({'ack': ident, 'status': 'applied'}).encode())
            self.assertIsNotNone(iot._fall_buzzer_saved)
            iot.apply_node_payload('patient', {'buzzer': saved})
            self.assertIsNone(iot._fall_buzzer_saved)

    def setUp(self):
        self.iot = load_iot()

    def test_commands_wait_for_telemetry(self):
        iot = self.iot
        for device in ('light', 'buzzer', 'window', 'exhaust'):
            iot.set_device('kitchen', device, state=True, silent=True)
            payload = json.loads(iot.command_queues['kitchen'].get_nowait())
            self.assertTrue(payload[device])
            self.assertEqual(payload['state'], 1)
            self.assertFalse(iot.ROOMS['kitchen'][device])
        iot.apply_node_payload('kitchen', {'light': True})
        self.assertTrue(iot.ROOMS['kitchen']['light'])

    def test_pwm_alias_and_validation(self):
        for percent, pwm in ((0, 0), (50, 128), (100, 255)):
            room, cmd = build_command('bed', 'fan', value=percent)
            self.assertEqual((room, cmd['value']), ('patient', pwm))
        self.assertEqual(build_command('living', 'light', state=True)[1]['state'], 1)
        for args in (('patient', 'light', True), ('living', 'fan', 'false'),
                     ('living', 'fan', True, True), ('living', 'fan', True, 101),
                     ('living', 'light', True, 50)):
            with self.assertRaises(ValueError):
                build_command(*args)

    def test_full_queue_does_not_debounce_retry(self):
        iot = self.iot
        iot.command_queues['kitchen'] = queue.Queue(maxsize=1)
        iot.command_queues['kitchen'].put('occupied')
        self.assertFalse(iot.set_device('kitchen', 'light', True))
        self.assertNotIn(('kitchen', 'light'), iot._last_cmd)
        iot._emit.assert_called_with('command_error', {
            'room': 'kitchen', 'device': 'light', 'message': 'Command queue full'})
        iot.command_queues['kitchen'].get_nowait()
        iot.set_device('kitchen', 'light', True)
        self.assertFalse(iot.command_queues['kitchen'].empty())

    def test_emergency_saves_state_and_quiets_other_rooms(self):
        iot = self.iot
        with patch.object(iot, 'set_device') as command:
            iot._enter_emergency()
            saved = copy.deepcopy(iot._emergency_snapshot)
            iot.ROOMS['living']['light'] = True
            iot._enter_emergency()
            self.assertEqual(iot._emergency_snapshot, saved)
            command.assert_any_call('living', 'light', state=False, source='auto', silent=True)
            command.assert_any_call('patient', 'buzzer', state=True, source='auto', silent=True)
            self.assertFalse(any(c.args[0] == 'kitchen' for c in command.call_args_list))

    def test_safe_window_resets_on_gap_and_danger(self):
        iot = self.iot
        def sample(t, gas=0):
            with patch.object(iot.time, 'monotonic', return_value=t):
                iot.apply_node_payload('kitchen', {'gas': gas, 'smoke': False, 'flame': False})
        sample(10)
        sample(12)
        self.assertEqual(iot._kitchen_safe_since, 10)
        sample(16)
        self.assertEqual(iot._kitchen_safe_since, 16)
        sample(17, 2500)
        self.assertIsNone(iot._kitchen_safe_since)
        sample(18)
        self.assertEqual(iot._kitchen_safe_since, 18)

    def test_confirm_requires_fresh_continuous_samples(self):
        iot = self.iot
        iot.alert_level = 'awaiting'
        for since, last in ((None, None), (95, 100), (80, 95)):
            iot._kitchen_safe_since, iot._kitchen_sample_at = since, last
            with patch.object(iot.time, 'monotonic', return_value=100), patch.object(iot, 'set_device') as command:
                iot.confirm_safe()
                command.assert_not_called()
                self.assertEqual(iot.alert_level, 'awaiting')

    def begin_restoration(self, automatic=True):
        iot = self.iot
        for room in ('patient', 'living'):
            iot.set_node_online(room, True)
        iot.ROOMS['living'].update(auto=automatic, light=True, fan=True, fan_speed=50)
        iot.AI['fall'] = True
        iot.apply_node_payload('kitchen', {
            'gas': 2500, 'smoke': True, 'flame': False, 'emergency': True})
        self.assertEqual(iot.alert_level, 'emergency')
        for tick in range(101, 114):
            with patch.object(iot.time, 'monotonic', return_value=tick):
                iot.apply_node_payload('kitchen', {
                    'gas': 0, 'smoke': False, 'flame': False, 'emergency': False})
        iot.confirm_safe()
        self.assertIsNotNone(iot._restoration_started)
        # Simulate firmware acknowledgements through the actual notification parser.
        for room in ('patient', 'living'):
            handler = iot._make_notify_handler(room)
            for ident in list(iot._pending_commands[room]):
                handler(None, json.dumps({'ack': ident, 'status': 'applied'}).encode())

    def test_auto_restore_completes_from_telemetry_with_changed_outputs(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=113):
            self.begin_restoration()
            iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
            iot.apply_node_payload('living', {'auto': True, 'light': False, 'fan': False, 'fan_speed': 0})
            self.assertIsNone(iot._emergency_snapshot)
            self.assertEqual(iot.alert_level, 'normal')
            self.assertTrue(iot.ROOMS['patient']['buzzer'])

    def test_manual_restore_rejects_partial_and_incorrect_reports(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=113):
            self.begin_restoration(automatic=False)
            count = len(iot._pending_commands['living'])
            iot.confirm_safe()
            self.assertEqual(len(iot._pending_commands['living']), count)
            iot.apply_node_payload('patient', {'temp': 25})
            iot.apply_node_payload('living', {'auto': False})
            self.assertIsNotNone(iot._emergency_snapshot)
            iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
            iot.apply_node_payload('living', {'auto': False, 'light': False, 'fan': True, 'fan_speed': 50})
            self.assertIsNotNone(iot._emergency_snapshot)
            iot.apply_node_payload('living', {'auto': False, 'light': True, 'fan': True, 'fan_speed': 50})
            self.assertIsNone(iot._emergency_snapshot)

    def test_new_danger_cancels_restoration(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=113):
            self.begin_restoration()
            iot.apply_node_payload('kitchen', {'gas': 3000, 'smoke': False, 'flame': False})
            self.assertIsNone(iot._restoration_started)
            self.assertIsNotNone(iot._emergency_snapshot)
            self.assertEqual(iot.alert_level, 'emergency')
            commands = [json.loads(p['text']) for p in iot._pending_commands['living'].values()]
            self.assertTrue(commands)
            self.assertTrue(all(c['state'] == 0 for c in commands))

    def test_sample_gap_prevents_finishing_restoration(self):
        iot = self.iot
        with patch.object(iot.time, 'monotonic', return_value=113):
            self.begin_restoration()
        with patch.object(iot.time, 'monotonic', return_value=120):
            iot.apply_node_payload('kitchen', {'gas': 0, 'smoke': False, 'flame': False})
            iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
            iot.apply_node_payload('living', {'auto': True})
            self.assertIsNotNone(iot._emergency_snapshot)

    def test_failed_restoration_can_retry_and_complete(self):
        for failure in ('rejected', 'timeout', 'missing_telemetry'):
            with self.subTest(failure=failure):
                self.iot = load_iot()
                iot = self.iot
                with patch.object(iot.time, 'monotonic', return_value=113):
                    self.begin_restoration()
                    iot.set_device('patient', 'buzzer', True, source='auto')
                    ident = next(iter(iot._pending_commands['patient']))
                    if failure == 'rejected':
                        iot._make_notify_handler('patient')(None, json.dumps(
                            {'ack': ident, 'status': 'rejected'}).encode())
                with patch.object(iot.time, 'monotonic', return_value=144):
                    if failure == 'timeout':
                        asyncio.run(iot._send_pending('patient', Mock(write_gatt_char=AsyncMock()), 'uuid'))
                    self.assertIsNotNone(iot._emergency_snapshot)
                    iot._kitchen_sample_at = 144
                    iot.confirm_safe()
                    self.assertEqual(iot._restoration_started, 144)
                    for room in ('patient', 'living'):
                        handler = iot._make_notify_handler(room)
                        for command in list(iot._pending_commands[room]):
                            handler(None, json.dumps({'ack': command, 'status': 'applied'}).encode())
                    iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
                    iot.apply_node_payload('living', {'auto': True})
                    self.assertIsNone(iot._emergency_snapshot)

    def test_restoration_confirmation_expires_or_disconnects(self):
        for disconnect in (False, True):
            self.iot = load_iot()
            iot = self.iot
            with patch.object(iot.time, 'monotonic', return_value=113):
                self.begin_restoration()
                iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
                if disconnect:
                    iot.set_node_online('patient', False)
                    iot.set_node_online('patient', True)
            with patch.object(iot.time, 'monotonic', return_value=114 if disconnect else 117):
                iot._kitchen_sample_at = iot.time.monotonic()
                iot.apply_node_payload('living', {'auto': True})
                self.assertIsNotNone(iot._emergency_snapshot)
                iot.apply_node_payload('patient', {'fan': False, 'fan_speed': 0, 'buzzer': True})
                self.assertIsNone(iot._emergency_snapshot)

    def test_fragmented_invalid_and_wrong_room_notifications(self):
        iot = self.iot
        handler = iot._make_notify_handler('living')
        with patch.object(iot, 'apply_node_payload') as apply:
            handler(None, b'{"room":"living",')
            apply.assert_not_called()
            handler(None, b'"light":true}\n')
            apply.assert_called_once_with('living', {'room': 'living', 'light': True})
            apply.reset_mock()
            handler(None, b'invalid\n{"room":"kitchen","light":true}\n')
            apply.assert_not_called()
            handler(None, b'{"light":false}\n')
            apply.assert_called_once_with('living', {'light': False})


if __name__ == '__main__':
    unittest.main()
