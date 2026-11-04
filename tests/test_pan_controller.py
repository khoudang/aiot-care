"""Pure pan control: synthetic coordinates and time; no hardware imports."""
import unittest
import numpy as np  # Preload before any iot_fixture dependency replacement.
import person_tracker


class PanControllerTests(unittest.TestCase):
    def step(self, center=640., width=640., current=90., elapsed=.5, **kwargs):
        return person_tracker.bounded_pan_step(center, width, current, elapsed,
            kp=.06, smoothing=.35, deadzone=24., minimum=0., maximum=180.,
            invert=False, **kwargs)

    def test_large_error_is_limited_to_three_degrees(self):
        self.assertAlmostEqual(self.step(), 93.)

    def test_elapsed_time_scales_motion_without_idle_catchup(self):
        # Same error: ten 50-ms updates equal one 500-ms update.
        self.assertAlmostEqual(self.step(elapsed=.05) - 90., .3)
        self.assertAlmostEqual(self.step(elapsed=50.), 93.)
        self.assertIsNone(self.step(elapsed=0.))
        self.assertIsNone(self.step(elapsed=-.1))

    def test_deadzone_includes_boundary_and_saturated_angle_sends_nothing(self):
        for center in (296., 320., 344.):
            with self.subTest(center=center):
                self.assertIsNone(self.step(center=center))
        self.assertIsNone(self.step(current=180.))
        self.assertAlmostEqual(self.step(current=179.), 180.)
        self.assertAlmostEqual(self.step(center=0., current=1.), 0.)


    def test_invalid_measurement_is_not_a_motion_command(self):
        for center in (float('nan'), float('inf'), -1., 641.):
            with self.subTest(center=center):
                self.assertIsNone(self.step(center=center))
        self.assertIsNone(self.step(width=0.))
        self.assertIsNone(self.step(elapsed=float('nan')))


    def test_cadence_and_inversion_preserve_proportional_response(self):
        # Constant measured error, not a simulated moving camera or accuracy claim.
        angle = 90.
        for _ in range(10):
            angle = self.step(center=400., current=angle, elapsed=.05)
        self.assertAlmostEqual(angle, self.step(center=400., elapsed=.5))
        self.assertAlmostEqual(person_tracker.bounded_pan_step(640., 640., 90., .5,
            kp=.06, smoothing=.35, deadzone=24., minimum=0., maximum=180.,
            invert=True), 87.)

    def test_gateway_uses_bounded_time_aware_pan(self):
        from iot_fixture import load_iot
        from unittest.mock import patch
        iot = load_iot()
        iot.SERVO_KP, iot.SERVO_SMOOTHING = .06, .35
        iot.SERVO_DEADZONE_PX = 24
        iot.SERVO_MIN, iot.SERVO_MAX = 0., 180.
        iot.SERVO_INVERT = False
        iot.AI['angle'] = 90.
        with patch.object(iot.time, 'perf_counter', side_effect=[10., 10.05, 60.]):
            self.assertAlmostEqual(iot.update_tracking(640., 640), 93.)
            self.assertAlmostEqual(iot.update_tracking(640., 640), 93.3)
            self.assertAlmostEqual(iot.update_tracking(640., 640), 96.3)
        self.assertAlmostEqual(iot.AI['angle'], 96.3)
        with patch.object(iot.time, 'perf_counter', return_value=60.5):
            self.assertIsNone(iot.update_tracking(320., 640))
        self.assertAlmostEqual(iot.AI['angle'], 96.3)


if __name__ == '__main__':
    unittest.main()
