import copy
import json
import unittest
from unittest.mock import patch

import iot


class KitchenControlTests(unittest.TestCase):
    def setUp(self):
        self.rooms = copy.deepcopy(iot.ROOMS)
        self.level = iot.alert_level
        self.last_cmd = dict(iot._last_cmd)
        iot._last_cmd.clear()
        self.addCleanup(self.restore_state)
        for name in ("_emit", "log_audit", "send_telegram_alert_async", "set_camera_mode"):
            patcher = patch.object(iot, name)
            patcher.start()
            self.addCleanup(patcher.stop)

    def restore_state(self):
        iot.ROOMS.clear()
        iot.ROOMS.update(self.rooms)
        iot.alert_level = self.level
        iot._last_cmd.clear()
        iot._last_cmd.update(self.last_cmd)

    def test_kitchen_commands_include_flat_firmware_keys(self):
        with patch.object(iot, "enqueue_command") as send:
            for device in ("light", "buzzer", "window", "exhaust"):
                for enabled in (True, False):
                    iot.set_device("kitchen", device, state=enabled, silent=True)
                    room, payload = send.call_args.args
                    payload = json.loads(payload)
                    self.assertEqual(room, "kitchen")
                    self.assertEqual(payload["cmd"], device)
                    self.assertEqual(payload["state"], int(enabled))
                    self.assertIs(payload[device], enabled)
                    self.assertIs(iot.ROOMS["kitchen"][device], enabled)

    def test_emergency_commands_include_kitchen_buzzer_and_light(self):
        with patch.object(iot, "set_device") as command:
            iot._enter_emergency()
            for device in ("light", "buzzer", "window", "exhaust"):
                command.assert_any_call("kitchen", device, state=True,
                                        source="auto", silent=True)

    def test_confirm_safe_does_not_disable_outputs_during_alarm(self):
        for sensor_status in ((True, False), (False, True)):
            iot.alert_level = "emergency"
            with patch.object(iot, "_danger_warn", return_value=sensor_status), \
                    patch.object(iot, "set_device") as command:
                iot.confirm_safe()
                command.assert_not_called()
                self.assertEqual(iot.alert_level, "emergency")

    def test_confirm_safe_stops_kitchen_buzzer_and_keeps_light(self):
        iot.alert_level = "awaiting"
        with patch.object(iot, "_danger_warn", return_value=(False, False)), \
                patch.object(iot, "set_device") as command:
            iot.confirm_safe()
            for device in ("buzzer", "window", "exhaust"):
                command.assert_any_call("kitchen", device, state=False,
                                        source="auto", silent=True)
            self.assertFalse(any(c.args[:2] == ("kitchen", "light")
                                 for c in command.call_args_list))
            self.assertEqual(iot.alert_level, "normal")

    def test_device_states_from_firmware_update_dashboard(self):
        with patch.object(iot, "push_history"), patch.object(iot, "evaluate_alerts"):
            iot.apply_node_payload("kitchen", {"light": True, "buzzer": True})
            self.assertTrue(iot.ROOMS["kitchen"]["light"])
            self.assertTrue(iot.ROOMS["kitchen"]["buzzer"])
            iot.apply_node_payload("kitchen", {"light": False, "buzzer": False})
            self.assertFalse(iot.ROOMS["kitchen"]["light"])
            self.assertFalse(iot.ROOMS["kitchen"]["buzzer"])


if __name__ == "__main__":
    unittest.main()
