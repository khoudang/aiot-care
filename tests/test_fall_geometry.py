"""Geometry checks for the pose-based fall heuristic (no camera, no alerts)."""
import unittest
import numpy as np  # Load NumPy before iot_fixture patches sys.modules.
from types import SimpleNamespace
from iot_fixture import load_iot


def person(shoulder_y=0.35, hip_y=0.62, spread=0.05, lean=0.0):
    pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(33)]
    pts[11] = SimpleNamespace(x=0.45, y=shoulder_y)
    pts[12] = SimpleNamespace(x=0.55, y=shoulder_y)
    pts[23] = SimpleNamespace(x=0.45 + lean, y=hip_y)
    pts[24] = SimpleNamespace(x=0.55 + lean, y=hip_y)
    for i in (0, 15, 16, 27, 28):
        pts[i] = SimpleNamespace(x=0.5 - spread, y=shoulder_y)
    for i in (17, 18, 19, 20, 21, 22):
        pts[i] = SimpleNamespace(x=0.5 + spread, y=hip_y)
    for i in (29, 30, 31, 32):
        pts[i] = SimpleNamespace(x=0.5, y=hip_y + 0.3)
    return pts


class FallGeometryTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def test_upright_person_is_not_a_fall(self):
        self.assertFalse(self.iot.detect_fall(person(), 640, 480))

    def test_lying_person_triggers_suspicion(self):
        lying = person(shoulder_y=0.55, hip_y=0.55, spread=0.35, lean=0.35)
        self.assertTrue(self.iot.detect_fall(lying, 640, 480))

    def test_missing_landmarks_do_not_raise(self):
        self.assertFalse(self.iot.detect_fall([], 640, 480))

    def test_observation_mode_only_flags_suspicion(self):
        self.iot.AI_OBSERVE_ONLY = True
        from unittest.mock import patch
        with patch.object(self.iot, 'now_ts', return_value=100.0):
            self.iot._handle_fall(True)
        self.assertFalse(self.iot.AI["fall_suspected"], "Brief pose must not raise suspicion")
        with patch.object(self.iot, 'now_ts', return_value=100.0 + self.iot.FALL_HOLD_SEC + 0.5):
            self.iot._handle_fall(True)
        self.assertTrue(self.iot.AI["fall_suspected"])
        self.assertFalse(self.iot.AI["fall"])


if __name__ == '__main__':
    unittest.main()
