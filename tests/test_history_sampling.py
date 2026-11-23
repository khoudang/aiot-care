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
