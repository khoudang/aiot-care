import unittest
from iot_fixture import load_iot


class SupportedRoomsTests(unittest.TestCase):
    def test_removed_node_cannot_add_state_or_emit_alerts(self):
        iot = load_iot()
        before = iot.snapshot_all()
        iot.apply_node_payload('wearable', {'heart_rate': 20, 'spo2': 40})
        iot.set_node_online('wearable', True)
        self.assertEqual(iot.snapshot_all(), before)
        iot._emit.assert_not_called()
        iot.send_telegram_alert_async.assert_not_called()
        for collection in (iot.ROOMS, iot.NODE_ONLINE, iot.histories, iot.command_queues, iot.ble_clients):
            self.assertEqual(set(collection), {'patient', 'living', 'kitchen'})

    def test_remaining_rooms_still_accept_telemetry(self):
        iot = load_iot()
        iot.apply_node_payload('living', {'temp': 27.5, 'hum': 65})
        iot.set_node_online('living', True)
        state = iot.snapshot_all()
        self.assertEqual(state['rooms']['living']['temp'], 27.5)
        self.assertTrue(state['nodes']['living'])
        self.assertEqual(len(state['nodes']), 3)
