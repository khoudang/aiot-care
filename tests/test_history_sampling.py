"""Chart-history cadence validation; does not touch hardware sampling."""
import unittest
from unittest.mock import patch

from iot_fixture import load_iot


class HistorySamplingTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def test_interval_setting_is_bounded_and_updates_runtime_cache(self):
        iot = self.iot
        self.assertEqual(iot.set_history_sample_interval(5), 5)
        self.assertEqual(iot.set_history_sample_interval("3600"), 3600)
        for invalid in (True, 4, 3601, "bad", None):
            with self.subTest(invalid=invalid):
                self.assertEqual(iot.set_history_sample_interval(invalid), 60)

    def test_history_writer_is_locked_and_returns_when_a_sample_is_added(self):
        iot = self.iot
        iot._history_interval = 5
        with patch.object(iot.time, 'monotonic', return_value=0):
            self.assertTrue(iot._real_push_history('kitchen'))
        with patch.object(iot.time, 'monotonic', return_value=4):
            self.assertFalse(iot._real_push_history('kitchen'))
        with patch.object(iot.time, 'monotonic', return_value=5):
            self.assertTrue(iot._real_push_history('kitchen'))
        history = iot.snapshot_histories()['kitchen']
        self.assertEqual(len(history['labels']), 2)
        self.assertEqual(len(history['gas']), 2)

    def test_live_chart_updates_are_emitted_for_kitchen_samples(self):
        iot = self.iot
        iot._history_interval = 5
        with patch.object(iot.time, 'monotonic', return_value=0):
            iot.apply_node_payload('kitchen', {
                'gas': 700, 'smoke': False, 'mp2_do_alarm': False, 'flame': False,
            })
        self.assertTrue(any(call.args[0] == 'sensor_chart_update'
                            for call in iot._emit.call_args_list))

    def test_startup_reload_falls_back_when_database_is_unavailable(self):
        iot = self.iot
        with patch.object(iot, "get_config_value", side_effect=RuntimeError("db unavailable")):
            self.assertEqual(iot.reload_history_sample_interval(), 60)

    def test_startup_reload_uses_persisted_value(self):
        iot = self.iot
        with patch.object(iot, "get_config_value", return_value="15") as get_value:
            self.assertEqual(iot.reload_history_sample_interval(), 15)
        get_value.assert_called_once_with("history_sample_interval_sec", "60")


if __name__ == "__main__":
    unittest.main()
