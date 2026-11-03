"""Geometry checks for the pose-based fall positive-evidence gates (no camera, no alerts)."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
import numpy as np  # Load NumPy before iot_fixture patches sys.modules.
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


def lying_person():
    return person(shoulder_y=0.55, hip_y=0.55, spread=0.35, lean=0.35)


class FallGeometryTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()

    def test_upright_person_is_not_a_fall(self):
        """Upright standing (angle < 55, aspect < 1.1) => no fall."""
        self.assertFalse(self.iot.detect_fall(person(), 640, 480))

    def test_upright_with_arms_spread_is_not_a_fall(self):
        """Upright with arms spread (aspect > 1.1, angle < 55) => no fall."""
        pts = person(shoulder_y=0.35, hip_y=0.65, spread=0.05, lean=0.0)
        # Stretch wrists horizontally so width >> height (aspect > 1.1)
        pts[15] = SimpleNamespace(x=0.05, y=0.35)
        pts[16] = SimpleNamespace(x=0.95, y=0.35)
        self.assertFalse(self.iot.detect_fall(pts, 640, 480))

    def test_forward_bend_is_not_a_fall(self):
        """Forward bend (angle > 55, aspect < 1.1) => no fall."""
        pts = [SimpleNamespace(x=0.5, y=0.5) for _ in range(33)]
        # Torso tilted horizontal (angle ~ 90 deg > 55)
        pts[11] = SimpleNamespace(x=0.45, y=0.45)
        pts[12] = SimpleNamespace(x=0.45, y=0.47)
        pts[23] = SimpleNamespace(x=0.65, y=0.45)
        pts[24] = SimpleNamespace(x=0.65, y=0.47)
        # Narrow feet / legs down at y=0.85
        pts[27] = SimpleNamespace(x=0.64, y=0.85)
        pts[28] = SimpleNamespace(x=0.66, y=0.85)
        for i in range(33):
            if i not in (11, 12, 23, 24, 27, 28):
                pts[i] = SimpleNamespace(x=0.55, y=0.50)
        self.assertFalse(self.iot.detect_fall(pts, 640, 480))

    def test_horizontal_posture_triggers_suspicion(self):
        """Horizontal posture with both angle > 55 and aspect > 1.1 => suspect."""
        lying = lying_person()
        self.assertTrue(self.iot.detect_fall(lying, 640, 480))

    def test_sustained_horizontal_posture_triggers_fall_alert(self):
        """Sustained suspect posture across hold window triggers actionable fall alert."""
        self.iot.AI_OBSERVE_ONLY = False
        with patch.object(self.iot, 'now_ts', return_value=100.0):
            self.iot._handle_fall(True)
        self.assertFalse(self.iot.AI["fall"], "Brief suspect posture must not trigger alarm")

        with patch.object(self.iot, 'now_ts', return_value=100.0 + self.iot.FALL_HOLD_SEC + 0.5):
            self.iot._handle_fall(True)
        self.assertTrue(self.iot.AI["fall"], "Sustained suspect posture must trigger fall alarm")

    def test_low_visibility_and_partial_body_rejects_fall(self):
        """Low visibility / partial body (< 0.5) => no fall."""
        # Low shoulder visibility
        pts = lying_person()
        pts[11].visibility = 0.2
        self.assertFalse(self.iot.detect_fall(pts, 640, 480), "Shoulder visibility < 0.5 must reject")

        # Low hip visibility
        pts = lying_person()
        pts[23].visibility = 0.3
        self.assertFalse(self.iot.detect_fall(pts, 640, 480), "Hip visibility < 0.5 must reject")

        # Both ankles low visibility
        pts = lying_person()
        pts[27].visibility = 0.2
        pts[28].visibility = 0.2
        self.assertFalse(self.iot.detect_fall(pts, 640, 480), "Both ankles < 0.5 must reject")

        # Single ankle visible (single-side occlusion tolerance)
        pts = lying_person()
        pts[27].visibility = 0.8
        pts[28].visibility = 0.1
        self.assertTrue(self.iot.detect_fall(pts, 640, 480), "Single visible ankle must pass confidence gate")

        # Missing landmarks array / fewer than 33
        self.assertFalse(self.iot.detect_fall([], 640, 480))
        self.assertFalse(self.iot.detect_fall(pts[:20], 640, 480))

    def test_implausible_body_size_rejects_fall(self):
        """Implausible body size (< 0.15 or > 1.25) => no fall."""
        # Tiny cluster (< 0.15)
        tiny = [SimpleNamespace(x=0.5 + (i * 0.001), y=0.5 + (i * 0.001)) for i in range(33)]
        self.assertFalse(self.iot.detect_fall(tiny, 640, 480), "Tiny body < 0.15 must reject")

        # Giant body (> 1.25)
        giant = lying_person()
        giant[15].x = -0.15
        giant[16].x = 1.20  # bw_norm = 1.35 > 1.25
        self.assertFalse(self.iot.detect_fall(giant, 640, 480), "Giant body > 1.25 must reject")

    def test_out_of_frame_pose_rejects_and_resets_hold_window(self):
        """Out-of-frame pose returns False and resets hold window timer in worker."""
        # Negative coordinates
        oof = lying_person()
        oof[11].x = -0.05
        self.assertFalse(self.iot.detect_fall(oof, 640, 480), "Landmark x < 0 must reject")

        # Coordinate > 1.0
        oof = lying_person()
        oof[27].y = 1.05
        self.assertFalse(self.iot.detect_fall(oof, 640, 480), "Landmark y > 1 must reject")

        # Out-of-frame pose in worker resets hold window timer:
        # 1. First suspect frame at t = 100.0
        with patch.object(self.iot, 'now_ts', return_value=100.0):
            self.iot._handle_fall(True)
        self.assertEqual(self.iot._fall_since, 100.0)

        # 2. Person leaves frame: worker sets fall_event=False, resetting _fall_since = 0.0
        with patch.object(self.iot, 'now_ts', return_value=102.0):
            self.iot._handle_fall(False)
        self.assertEqual(self.iot._fall_since, 0.0, "Out-of-frame / no-pose must reset _fall_since")

        # 3. New suspect frame at t = 104.0 starts fresh hold window, does NOT trigger immediate fall
        with patch.object(self.iot, 'now_ts', return_value=104.0):
            self.iot._handle_fall(True)
        self.assertFalse(self.iot.AI["fall"], "Timer was reset; must not trigger fall alarm prematurely")
        self.assertEqual(self.iot._fall_since, 104.0)

    def test_observation_mode_only_flags_suspicion(self):
        """Observation mode (AI_OBSERVE_ONLY=True) sets fall_suspected, no fall alert."""
        self.iot.AI_OBSERVE_ONLY = True
        with patch.object(self.iot, 'now_ts', return_value=100.0):
            self.iot._handle_fall(True)
        self.assertFalse(self.iot.AI["fall_suspected"], "Brief pose must not raise suspicion")

        with patch.object(self.iot, 'now_ts', return_value=100.0 + self.iot.FALL_HOLD_SEC + 0.5):
            self.iot._handle_fall(True)
        self.assertTrue(self.iot.AI["fall_suspected"])
        self.assertFalse(self.iot.AI["fall"], "Observation mode must never set AI['fall']")
        self.assertIsNone(self.iot._fall_buzzer_saved, "Observation mode must not save or lock buzzer")


if __name__ == '__main__':
    unittest.main()
