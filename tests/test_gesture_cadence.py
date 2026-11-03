"""Run the real AI worker with deterministic frames and hand model outputs."""
import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from iot_fixture import load_iot


def open_hand():
    points = [SimpleNamespace(x=.7, y=.8) for _ in range(21)]
    points[3].x = .5
    points[4].x = .1
    for tip in (8, 12, 16, 20):
        points[tip].y = .2
        points[tip - 2].y = .6
    return SimpleNamespace(landmark=points)


class GestureCadenceTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()
        self.iot.GESTURE_STABLE_CYCLES = 2
        self.iot.GESTURE_MIN_SIZE = 0.08

    def run_worker(self, hand_side_effects, max_cycles=7, expire_at_cycle=None):
        iot = load_iot()
        iot.GESTURE_STABLE_CYCLES = 2
        iot.GESTURE_MIN_SIZE = 0.08
        iot.PROCESS_EVERY_N_FRAMES = 3
        iot.ENABLE_GESTURE = True
        iot.ENABLE_TRACKING = True
        iot.ENABLE_FALL = False
        iot.camera_active = True
        iot._camera_session_id = 1
        iot.socketio = None
        iot._latest_raw_slot.update(
            frame=np.zeros((24, 32, 3), dtype=np.uint8),
            gen=1, session_id=1, w=32, h=24, ts=time.perf_counter()
        )
        observed = []

        def pose_process(_):
            observed.append(dict(iot.AI))
            if expire_at_cycle is not None and len(observed) == expire_at_cycle:
                iot.OVERLAY_MAX_AGE_SEC = 0
            iot._latest_raw_slot['gen'] += 1
            if len(observed) >= max_cycles:
                iot.camera_active = False
            return SimpleNamespace(pose_landmarks=None)

        hands = Mock(process=Mock(side_effect=hand_side_effects))
        iot.mp = SimpleNamespace(solutions=SimpleNamespace(
            pose=SimpleNamespace(Pose=lambda **kw: Mock(process=pose_process)),
            hands=SimpleNamespace(Hands=lambda **kw: hands)
        ))
        iot._apply_gesture = Mock()
        iot._camera_ai_worker(1)
        return observed, iot

    def test_hand_in_frame_and_size_validation(self):
        """In-frame check and minimum size gate for hand gestures."""
        # Valid hand
        self.assertEqual(self.iot.detect_gesture([open_hand()], 320, 240), 'open')

        # Out-of-frame coordinates (x < 0.0)
        oof_x = open_hand()
        oof_x.landmark[0].x = -0.05
        self.assertIsNone(self.iot.detect_gesture([oof_x], 320, 240), "Hand with x < 0 must be rejected")

        # Out-of-frame coordinates (y > 1.0)
        oof_y = open_hand()
        oof_y.landmark[8].y = 1.05
        self.assertIsNone(self.iot.detect_gesture([oof_y], 320, 240), "Hand with y > 1 must be rejected")

        # Undersized hand (< GESTURE_MIN_SIZE = 0.08)
        tiny_pts = [SimpleNamespace(x=0.5 + (i * 0.001), y=0.5 + (i * 0.001)) for i in range(21)]
        tiny_hand = SimpleNamespace(landmark=tiny_pts)
        self.assertIsNone(self.iot.detect_gesture([tiny_hand], 320, 240), "Hand < 0.08 span must be rejected")

        # Multiple hands: out-of-frame hand is filtered out, remaining valid hand is recognized
        self.assertEqual(self.iot.detect_gesture([oof_x, open_hand()], 320, 240), 'open')

    def test_single_cycle_detection_is_not_actionable(self):
        """Single cycle detection (count=1 < 2) reflects in display but does NOT trigger actuation."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 3: 1st detection
            SimpleNamespace(multi_hand_landmarks=None),           # Cycle 6: true negative
        ]
        observed, iot = self.run_worker(effects, max_cycles=7)
        expected = iot.GESTURE_LABELS['open']
        self.assertEqual(observed[3]['gesture'], expected, "Cycle 3 must display recognized candidate")
        self.assertEqual(observed[3]['hand_status'], 'detected')
        iot._apply_gesture.assert_not_called()

    def test_two_consecutive_cycles_triggers_actionable_gesture(self):
        """Two consecutive cycles of the same gesture triggers actuation."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 3: count = 1
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 6: count = 2 -> trigger!
        ]
        observed, iot = self.run_worker(effects, max_cycles=8)
        expected = iot.GESTURE_LABELS['open']
        self.assertEqual(observed[3]['gesture'], expected)
        self.assertEqual(observed[6]['gesture'], expected)
        iot._apply_gesture.assert_called_once_with('open')

    def test_skipped_hands_cycles_preserve_result_without_repeating_actions(self):
        """Skipped inference cycles preserve display within TTL and do not reset stability or trigger actions."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 3: count = 1
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 6: count = 2 -> trigger!
            SimpleNamespace(multi_hand_landmarks=None),           # Cycle 9: clear!
        ]
        observed, iot = self.run_worker(effects, max_cycles=10)
        expected = iot.GESTURE_LABELS['open']
        self.assertEqual(observed[3]['gesture'], expected, 'Third cycle recognized open hand')
        self.assertEqual(observed[4]['gesture'], expected, 'Skipped cycle 4 must preserve hand result')
        self.assertEqual(observed[5]['gesture'], expected, 'Skipped cycle 5 must preserve hand result')
        self.assertEqual(observed[6]['gesture'], expected, 'Cycle 6 satisfied stability threshold')
        self.assertEqual(observed[7]['gesture'], expected, 'Skipped cycle 7 must preserve hand result')
        self.assertEqual(observed[8]['gesture'], expected, 'Skipped cycle 8 must preserve hand result')
        self.assertEqual(observed[9]['gesture'], '—', 'Empty hand inference at cycle 9 must clear result')
        iot._apply_gesture.assert_called_once_with('open')

    def test_latch_prevention_sustained_gesture_does_not_repeat_actuation(self):
        """Holding a gesture continuously across 3+ inference cycles does NOT repeat actuation."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 3: count = 1
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 6: count = 2 -> trigger!
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 9: count = 3 -> latched, no retrigger!
        ]
        observed, iot = self.run_worker(effects, max_cycles=11)
        expected = iot.GESTURE_LABELS['open']
        self.assertEqual(observed[3]['gesture'], expected)
        self.assertEqual(observed[6]['gesture'], expected)
        self.assertEqual(observed[9]['gesture'], expected)
        # Action must fire exactly once despite being held for 3 consecutive cycles
        iot._apply_gesture.assert_called_once_with('open')

    def test_true_negative_clears_display_and_resets_candidate(self):
        """True negative immediately clears display and resets candidate counter."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 3: count = 1
            SimpleNamespace(multi_hand_landmarks=None),           # Cycle 6: true negative -> count resets to 0
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),  # Cycle 9: count = 1 again -> no trigger!
        ]
        observed, iot = self.run_worker(effects, max_cycles=11)
        self.assertEqual(observed[6]['gesture'], '—', 'Negative detection must immediately clear display')
        self.assertEqual(observed[6]['hand_status'], 'not_detected')
        self.assertEqual(observed[6]['hands_detected'], 0)
        # Because candidate was reset at cycle 6, cycle 9 only brings count to 1 (< 2), so no actuation
        iot._apply_gesture.assert_not_called()

    def test_hand_diagnostics_distinguish_waiting_detection_and_no_hand(self):
        """Diagnostics correctly report waiting, detected, and not_detected states."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),
            SimpleNamespace(multi_hand_landmarks=None)
        ]
        observed, _ = self.run_worker(effects, max_cycles=7)
        self.assertEqual(observed[1].get('hand_status'), 'waiting')
        self.assertEqual(observed[3].get('hand_status'), 'detected')
        self.assertEqual(observed[3].get('hands_detected'), 1)
        self.assertEqual(observed[4].get('hands_detected'), 1)
        self.assertEqual(observed[6].get('hand_status'), 'not_detected')
        self.assertEqual(observed[6].get('hands_detected'), 0)

    def test_cached_result_expires_if_next_inference_is_late(self):
        """When overlay TTL expires, result clears to stale and candidate resets."""
        effects = [
            SimpleNamespace(multi_hand_landmarks=[open_hand()]),
            SimpleNamespace(multi_hand_landmarks=None)
        ]
        observed, iot = self.run_worker(effects, max_cycles=7, expire_at_cycle=4)
        self.assertEqual(observed[3]['gesture'], iot.GESTURE_LABELS['open'])
        self.assertEqual(observed[4]['gesture'], '—')
        self.assertEqual(observed[4]['hand_status'], 'stale')
        self.assertEqual(observed[4]['hands_detected'], 0)


if __name__ == '__main__':
    unittest.main()
