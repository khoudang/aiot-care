"""Adaptive camera behavior, with all hardware boundaries stubbed."""
import unittest
from unittest.mock import Mock, patch
import numpy as np  # Must be loaded before iot_fixture replaces sys.modules.
from iot_fixture import load_iot


import importlib.util


class AdaptiveCameraTests(unittest.TestCase):
    def test_idle_profile_reduces_video_and_inference_cadence(self):
        self.assertIsNotNone(importlib.util.find_spec('camera_cadence'),
                             'Adaptive camera cadence policy is not implemented')
        from camera_cadence import CadencePolicy
        policy = CadencePolicy()
        policy.activity(0.0)
        profile = policy.profile(31.0, mode='auto', pir_fresh=True)
        self.assertEqual(profile['profile'], 'idle')
        self.assertEqual(profile['video_fps'], 3.0)
        self.assertEqual(profile['ai_fps'], 2.0)

    def test_auto_publisher_does_not_close_on_pir_timeout(self):
        iot = load_iot()
        iot.camera_mode = 'auto'
        iot.camera_active = True
        iot._camera_session_id = 1
        iot.last_motion_ts = 0.0
        iot.now_ts = lambda: 1000.0
        iot.STREAM_SLEEP = .001
        reads = []

        def read():
            reads.append(1)
            if len(reads) >= 5:
                iot.camera_active = False
            return True, np.zeros((24, 32, 3), dtype=np.uint8)

        capture = Mock(isOpened=Mock(return_value=True), read=Mock(side_effect=read))
        iot.cv2.VideoCapture = Mock(return_value=capture)
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b'jpeg')))
        iot._camera_pub_worker(1)
        self.assertEqual(len(reads), 5, 'PIR inactivity must not shut down capture')
        capture.release.assert_called_once()

    def test_idle_publisher_encodes_less_but_keeps_draining_capture(self):
        iot = load_iot()
        iot.camera_active = True
        iot.camera_mode = 'auto'
        iot._camera_session_id = 1
        iot.STREAM_SLEEP = 0.001
        clock = [0.0]
        reads = []

        def read():
            reads.append(1)
            clock[0] = len(reads) * 0.1
            if len(reads) >= 11:
                iot.camera_active = False
            return True, np.zeros((24, 32, 3), dtype=np.uint8)

        capture = Mock(isOpened=Mock(return_value=True), read=Mock(side_effect=read))
        iot.cv2.VideoCapture = Mock(return_value=capture)
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b'jpeg')))
        profile = {'profile': 'idle', 'reason': 'inactivity', 'video_fps': 3., 'ai_fps': 2.}
        with patch.object(iot, '_camera_profile', return_value=profile, create=True), \
                patch.object(iot.time, 'perf_counter', side_effect=lambda: clock[0]):
            iot._camera_pub_worker(1)
        self.assertEqual(len(reads), 11)
        self.assertEqual(iot.cv2.imencode.call_count, 3,
                         'Idle must reduce encoding work, not just hide frames in the UI')

    def test_idle_worker_reduces_actual_pose_invocations(self):
        iot = load_iot()
        iot.ENABLE_TRACKING = False
        iot.ENABLE_GESTURE = False
        iot.camera_mode = 'auto'
        iot.camera_active = True
        iot._camera_session_id = 1
        frame = np.zeros((24, 32, 3), dtype=np.uint8)
        iot._latest_raw_slot.update(frame=frame, gen=1, ts=0., session_id=1, w=32, h=24)
        clock = [0.0]
        calls = []

        def process(_):
            calls.append(clock[0])
            return Mock(pose_landmarks=None)

        def next_frame(*args, **kwargs):
            clock[0] = round(clock[0] + .1, 2)
            iot._latest_raw_slot['gen'] += 1
            iot._latest_raw_slot['ts'] = clock[0]
            if clock[0] >= 1.2:
                iot.camera_active = False

        iot.mp.solutions.pose.Pose.return_value = Mock(process=process)
        profile = {'profile': 'idle', 'reason': 'inactivity', 'video_fps': 3., 'ai_fps': 2.}
        with patch.object(iot, '_camera_profile', return_value=profile), \
                patch.object(iot.time, 'perf_counter', side_effect=lambda: clock[0]), \
                patch.object(iot._new_raw_frame_cond, 'wait', side_effect=next_frame):
            iot._camera_ai_worker(1)
        self.assertEqual(len(calls), 3, 'Pose must run at 0.0, 0.5 and 1.0 seconds')
        self.assertEqual(calls, [0.0, 0.5, 1.0])

    def test_visual_change_is_an_independent_wakeup_source(self):
        import camera_cadence
        probe_type = getattr(camera_cadence, 'FrameMotionProbe', None)
        self.assertIsNotNone(probe_type, 'Visual wake-up must not depend only on PIR')
        probe = probe_type()
        frame = np.zeros((48, 64, 3), dtype=np.uint8)
        self.assertFalse(probe.changed(frame))
        self.assertFalse(probe.changed(frame.copy()))
        frame[10:30, 10:30] = 200
        self.assertTrue(probe.changed(frame))
        self.assertFalse(probe.changed(frame.copy()))

    def test_auto_default_starts_capture_at_boot(self):
        iot = load_iot()
        iot.CAMERA_ENABLED = True
        iot.CAMERA_MODE_DEFAULT = 'auto'
        iot.camera_mode = 'auto'
        iot._start_camera = Mock()
        with patch.object(iot.threading, 'Thread'):
            iot.start_background_services()
        iot._start_camera.assert_called_once_with()

    def test_offline_cleanup_clears_adaptive_metrics(self):
        iot = load_iot()
        iot.camera_active = True
        iot._camera_session_id = 1
        iot.AI.update(camera=True, camera_profile='idle', target_video_fps=3., target_ai_fps=2.)
        iot._CameraLifecycle.handle_pub_worker_exit(1)
        self.assertEqual(iot.AI['camera_profile'], 'off')
        self.assertEqual(iot.AI['target_video_fps'], 0.)
        self.assertEqual(iot.AI['target_ai_fps'], 0.)

    def test_selecting_auto_opens_camera_without_a_pir_event(self):
        iot = load_iot()
        iot.camera_mode = 'off'
        iot.last_motion_ts = 0.0
        iot._start_camera = Mock()
        iot._stop_camera = Mock()
        iot._real_set_camera_mode('auto', user_id=7)
        iot._start_camera.assert_called_once_with(7)
        iot._stop_camera.assert_not_called()

    def test_policy_wakes_on_pir_and_preserves_explicit_modes(self):
        from camera_cadence import CadencePolicy
        policy = CadencePolicy()
        policy.activity(0.)
        self.assertEqual(policy.profile(31., pir_fresh=True)['profile'], 'idle')
        policy.activity(32., 'pir')
        self.assertEqual(policy.profile(32., pir_fresh=True)['reason'], 'pir')
        self.assertEqual(policy.profile(100., mode='off', alarm=True)['profile'], 'off')
        self.assertEqual(policy.profile(100., mode='on', pir_fresh=True)['profile'], 'active')

    def test_pending_alarms_and_missing_pir_force_active(self):
        cases = [('motion_missing', None), ('offline', None), ('fall', None),
                 ('fall_suspected', None), ('_fall_since', 95.),
                 ('_fall_buzzer_saved', False), ('_emergency_snapshot', {}),
                 ('alert_level', 'light')]
        for field, value in cases:
            with self.subTest(field=field):
                iot = load_iot()
                iot.camera_mode = 'auto'
                iot.NODE_ONLINE['patient'] = True
                iot._sensor_seen_at['patient']['motion'] = 99.
                iot._camera_policy.activity(0.)
                if field == 'motion_missing':
                    iot._sensor_seen_at['patient']['motion'] = None
                elif field == 'offline':
                    iot.NODE_ONLINE['patient'] = False
                elif field in ('fall', 'fall_suspected'):
                    iot.AI[field] = True
                else:
                    setattr(iot, field, value)
                with patch.object(iot.time, 'monotonic', return_value=100.):
                    self.assertEqual(iot._camera_profile()['profile'], 'active')

    def test_visual_change_wakes_real_publisher_from_idle(self):
        iot = load_iot()
        iot.camera_mode, iot.camera_active, iot._camera_session_id = 'auto', True, 1
        iot.NODE_ONLINE['patient'] = True
        iot._sensor_seen_at['patient']['motion'] = 30.
        iot._camera_policy.activity(0.)
        iot.STREAM_SLEEP = .001
        reads, profiles = [], []

        def read():
            reads.append(1)
            frame = np.zeros((48, 64, 3), dtype=np.uint8)
            if len(reads) >= 2:
                frame[10:30, 10:30] = 200
            if len(reads) >= 3:
                iot.camera_active = False
            return True, frame

        def encode(*args):
            profiles.append(iot.AI['camera_profile'])
            return True, Mock(tobytes=lambda: b'jpeg')

        iot.cv2.VideoCapture = Mock(return_value=Mock(isOpened=lambda: True, read=read))
        iot.cv2.imencode = Mock(side_effect=encode)
        with patch.object(iot.time, 'monotonic', return_value=31.), \
                patch.object(iot.time, 'perf_counter', side_effect=lambda: len(reads) * .1):
            iot._camera_pub_worker(1)
        self.assertEqual(profiles, ['idle', 'active'])

    def test_invalid_cadence_configuration_is_rejected(self):
        from camera_cadence import CadencePolicy
        for value in (0., -1., float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                CadencePolicy(idle_ai_fps=value)
        with self.assertRaises(ValueError):
            CadencePolicy(active_video_fps=2., idle_video_fps=3.)


if __name__ == '__main__':
    unittest.main()
