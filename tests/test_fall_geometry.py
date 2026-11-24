"""Geometry checks for the pose-based fall heuristic (no camera, no alerts)."""
import unittest
import numpy as np  # Load NumPy before iot_fixture patches sys.modules.
from types import SimpleNamespace
from iot_fixture import load_iot


def person(shoulder_y=0.35, hip_y=0.62, spread=0.05, lean=0.0):
    pts = [SimpleNamespace(visibility=1.0, x=0.5, y=0.5) for _ in range(33)]
    pts[11] = SimpleNamespace(visibility=1.0, x=0.45, y=shoulder_y)
    pts[12] = SimpleNamespace(visibility=1.0, x=0.55, y=shoulder_y)
    pts[23] = SimpleNamespace(visibility=1.0, x=0.45 + lean, y=hip_y)
    pts[24] = SimpleNamespace(visibility=1.0, x=0.55 + lean, y=hip_y)
    for i in (0, 15, 16, 27, 28):
        pts[i] = SimpleNamespace(visibility=1.0, x=0.5 - spread, y=shoulder_y)
    for i in (17, 18, 19, 20, 21, 22):
        pts[i] = SimpleNamespace(visibility=1.0, x=0.5 + spread, y=hip_y)
    for i in (29, 30, 31, 32):
        pts[i] = SimpleNamespace(visibility=1.0, x=0.5, y=hip_y + 0.3)
    return pts


class FallGeometryTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()
        self.iot.FALL_TORSO_DEG = 55
        self.iot.FALL_HIP_SPEED = .8
        self.iot.FALL_MOTION_WINDOW_SEC = .8
        self.iot.FALL_VISIBILITY = .7
        self.iot.FALL_MAX_GAP_SEC = .8
        self.iot.FALL_HOLD_SEC = 3.5

    def test_upright_person_is_not_a_fall(self):
        self.assertFalse(self.iot.detect_fall(person(), 640, 480))

    def test_lying_person_triggers_suspicion(self):
        lying = person(shoulder_y=0.55, hip_y=0.55, spread=0.35, lean=0.35)
        self.assertTrue(self.iot.detect_fall(lying, 640, 480))

    def event(self, fsm, pose, ts, moving=False):
        return fsm.update(pose, 640, 480, ts,
                          self.iot.detect_fall(pose, 640, 480), moving)

    def test_lying_at_start_never_becomes_event(self):
        fsm = self.iot.FallEventFSM()
        lying = person(shoulder_y=.65, hip_y=.65, lean=.35)
        for i in range(30):
            self.assertFalse(self.event(fsm, lying, i * .2))
        self.assertFalse(fsm.confirmed)

    def test_fast_descent_then_tilt_confirms_once_after_hold(self):
        fsm = self.iot.FallEventFSM()
        self.assertFalse(self.event(fsm, person(), 0.))
        lying = person(shoulder_y=.85, hip_y=.85, lean=.35)
        self.assertTrue(self.event(fsm, lying, .2))
        self.assertFalse(fsm.confirmed)
        for i in range(2, 20):
            self.assertTrue(self.event(fsm, lying, i * .2))
        self.assertTrue(fsm.confirmed)
        self.assertIsNone(fsm.unknown())
        self.assertTrue(fsm.confirmed)
        self.assertFalse(self.event(fsm, person(), 4.))
        self.assertFalse(fsm.confirmed)

    def test_slow_lying_does_not_trigger(self):
        fsm = self.iot.FallEventFSM()
        for i in range(12):
            y = .62 + i * .006
            self.assertFalse(self.event(fsm, person(shoulder_y=y-.27, hip_y=y), i*.2))
        self.assertFalse(self.event(fsm, person(shoulder_y=.69, hip_y=.69, lean=.35), 2.4))

    def test_invalid_landmark_and_camera_motion_reset_candidate(self):
        fsm = self.iot.FallEventFSM()
        lying = person(shoulder_y=.85, hip_y=.85, lean=.35)
        self.event(fsm, person(), 0.)
        self.assertFalse(self.event(fsm, lying, .2, moving=True))
        self.assertFalse(self.event(fsm, lying, .4))
        fsm = self.iot.FallEventFSM()
        self.event(fsm, person(), 0.)
        self.assertTrue(self.event(fsm, lying, .2))
        lying[11].visibility = .1
        self.assertFalse(self.event(fsm, lying, .4))
        self.assertFalse(fsm.confirmed)

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
