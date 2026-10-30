import unittest
from unittest.mock import patch
from iot_fixture import load_iot


class TelemetryFreshnessTests(unittest.TestCase):
    def test_fresh_to_stale_is_read_only_and_accepts_zero_clock(self):
        iot = load_iot()
        iot.TELEMETRY_STALE_SEC = 10.0
        iot.set_node_online('patient', True)
        self.assertIn('telemetry', iot.snapshot_all())
        self.assertEqual(iot.snapshot_all()['telemetry']['patient']['status'], 'awaiting')
        with patch.object(iot.time, 'monotonic', return_value=0.0):
            iot.apply_node_payload('patient', {'temp': 28.0, 'hum': 60.0, 'motion': False})
            self.assertEqual(iot.snapshot_all()['telemetry']['patient']['status'], 'fresh')
        iot.ROOMS['kitchen']['phase'] = 'emergency'
        iot.alert_level = 'emergency'
        iot.enqueue_command('patient', '{"cmd":"light","state":0}')
        pending = dict(iot._pending_commands['patient'])
        with patch.object(iot.time, 'monotonic', return_value=11.0):
            quality = iot.snapshot_all()['telemetry']['patient']
        self.assertEqual(quality['status'], 'stale')
        self.assertEqual(quality['age_sec'], 11.0)
        self.assertTrue(iot.NODE_ONLINE['patient'])
        self.assertEqual(iot._pending_commands['patient'], pending)
        self.assertEqual(iot.ROOMS['kitchen']['phase'], 'emergency')
        self.assertEqual(iot.alert_level, 'emergency')
    def test_ack_output_and_safety_frames_do_not_refresh_sensor_age(self):
        iot = load_iot()
        iot.set_node_online('patient', True)
        with patch.object(iot.time, 'monotonic', return_value=0.0):
            iot.apply_node_payload('patient', {'temp': 28.0, 'hum': 60.0, 'motion': False})
        with patch.object(iot.time, 'monotonic', return_value=9.0):
            iot.apply_node_payload('patient', {'light': True, 'buzzer': False})
            iot._make_notify_handler('patient')(None, b'{"ack":999,"status":"applied"}\n')
        with patch.object(iot.time, 'monotonic', return_value=11.0):
            self.assertEqual(iot.telemetry_status()['patient']['status'], 'stale')
        self.assertTrue(all(v is None for v in iot._sensor_seen_at['kitchen'].values()))
        iot.apply_node_payload('kitchen', {'phase': 'normal', 'event_id': 10})
        self.assertTrue(all(v is None for v in iot._sensor_seen_at['kitchen'].values()))

    def test_partial_fields_and_invalid_samples_remain_visible(self):
        iot = load_iot()
        iot.set_node_online('patient', True)
        iot.apply_node_payload('patient', {'temp': True, 'hum': float('nan'), 'motion': False})
        status = iot.telemetry_status()['patient']
        self.assertEqual(status['status'], 'partial')
        self.assertEqual(status['fields']['temp']['status'], 'missing')
        self.assertEqual(status['fields']['hum']['status'], 'missing')
        self.assertEqual(status['fields']['motion']['status'], 'fresh')
        iot.set_node_online('patient', False)
        self.assertEqual(iot.telemetry_status()['patient']['status'], 'offline')


if __name__ == '__main__':
    unittest.main()
