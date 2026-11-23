"""Chart-history cadence validation; does not touch hardware sampling."""
import unittest
from unittest.mock import patch

from iot_fixture import load_iot


class HistorySamplingTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def test_configured_interval_is_cached_for_five_seconds_then_reloaded(self):
        iot = self.iot
        iot._history_interval_checked_at = None
        with patch.object(iot, "get_config_value", side_effect=["30", "10"]) as get_value:
            with patch.object(iot.time, "monotonic", side_effect=[100.0, 104.9, 105.0]):
                self.assertEqual(iot._history_interval_seconds(), 30)
                self.assertEqual(iot._history_interval_seconds(), 30)
                self.assertEqual(iot._history_interval_seconds(), 10)
        self.assertEqual(get_value.call_count, 2)

    def test_invalid_interval_falls_back_to_sixty_seconds(self):
        for value in ("bad", "4", "3601", None):
            with self.subTest(value=value):
                iot = load_iot()
                iot._history_interval_checked_at = None
                with patch.object(iot, "get_config_value", return_value=value):
                    with patch.object(iot.time, "monotonic", return_value=100.0):
                        self.assertEqual(iot._history_interval_seconds(), 60)


if __name__ == "__main__":
    unittest.main()
