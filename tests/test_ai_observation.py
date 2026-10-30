import unittest
from unittest.mock import Mock, patch
from iot_fixture import load_iot


class AIObservationSafetyTests(unittest.TestCase):
    def test_observation_runs_detection_without_ai_hardware_or_external_alerts(self):
        iot = load_iot()
        iot.AI_OBSERVE_ONLY = True
        iot._gesture_map = {'open': ('light', 'on')}
        iot.set_device = Mock()
        iot.uart = Mock()
        iot._apply_gesture('open')
        with patch.object(iot, 'now_ts', return_value=100.0):
            iot._handle_fall(True)
        with patch.object(iot, 'now_ts', return_value=110.0):
            iot._handle_fall(True)
            iot.uart_send_angle(90)
        iot.set_device.assert_not_called()
        iot.uart.write.assert_not_called()
        iot.send_telegram_alert_async.assert_not_called()
        self.assertFalse(iot.AI['fall'])
        self.assertTrue(iot.AI['fall_suspected'])
        self.assertIsNone(iot._fall_buzzer_saved)
        iot._handle_fall(False)
        self.assertFalse(iot.AI['fall_suspected'])

    def test_startup_honors_camera_on_once_without_affecting_auto(self):
        for mode in ('on', 'auto', 'off'):
            with self.subTest(mode=mode):
                iot = load_iot()
                iot.services_started = False
                iot.camera_mode = mode
                iot._start_camera = Mock()
                iot.init_uart = Mock()
                iot.load_gesture_map = Mock()
                with patch.object(iot.threading, 'Thread'):
                    iot.start_background_services()
                    iot.start_background_services()
                self.assertEqual(iot._start_camera.call_count, int(mode == 'on'))

    def test_observed_suspicion_cannot_reconcile_or_resync_into_an_alarm(self):
        iot = load_iot()
        iot.AI_OBSERVE_ONLY = True
        iot.set_node_online('patient', True)
        with patch.object(iot, 'now_ts', return_value=100.0):
            iot._handle_fall(True)
        with patch.object(iot, 'now_ts', return_value=110.0):
            iot._handle_fall(True)
        iot._resync_safety('patient')
        iot._reconcile_safety('patient')
        self.assertEqual(len(iot._pending_commands['patient']), 0)
        self.assertFalse(iot._patient_buzzer_target())
        iot.set_device('patient', 'buzzer', False, silent=True)
        self.assertEqual(len(iot._pending_commands['patient']), 1)

    def test_observation_preserves_independent_kitchen_emergency_safety(self):
        iot = load_iot()
        iot.AI_OBSERVE_ONLY = True
        iot.set_node_online('patient', True)
        iot.set_node_online('living', True)
        iot._enter_emergency()
        self.assertTrue(iot._patient_buzzer_target())
        import json
        queued = [json.loads(p['text']) for p in iot._pending_commands['patient'].values()]
        self.assertTrue(any(p.get('cmd') == 'buzzer' and p.get('state') == 1 for p in queued))

    def test_normal_mode_preserves_gesture_control(self):
        iot = load_iot()
        iot.AI_OBSERVE_ONLY = False
        iot._gesture_map = {'open': ('light', 'on')}
        iot.set_device = Mock()
        iot._apply_gesture('open')
        iot.set_device.assert_called_once()

    def test_observation_does_not_block_explicit_manual_commands(self):
        iot = load_iot()
        iot.AI_OBSERVE_ONLY = True
        iot.set_node_online('patient', True)
        iot.set_device('patient', 'light', False, silent=True)
        self.assertEqual(len(iot._pending_commands['patient']), 1)


if __name__ == '__main__':
    unittest.main()
