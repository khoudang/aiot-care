"""Real worker integration without camera, UART, or model files."""
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from iot_fixture import load_iot


class TrackingWorkerTests(unittest.TestCase):
    def worker(self, center=240., observe=False, failure=None, supersede=False,
               runtime_failure=False, stale=False, no_pose=False, disabled=False,
               width=320):
        iot = load_iot()
        iot.ENABLE_FALL = not no_pose
        iot.ENABLE_GESTURE = False
        iot.ENABLE_TRACKING = True
        iot.tracking_enabled = not disabled
        iot.AI_OBSERVE_ONLY = observe
        iot.camera_active = True
        iot._camera_session_id = 1
        iot._latest_raw_slot.update(frame=np.zeros((240,width,3),dtype=np.uint8),
            gen=1,session_id=1,w=width,h=240,ts=time.perf_counter() - (10 if stale else 0))
        lms = [SimpleNamespace(x=.1, y=.5)] * 33
        pose = Mock(process=Mock(return_value=SimpleNamespace(pose_landmarks=SimpleNamespace(landmark=lms))))
        iot.mp = SimpleNamespace(solutions=SimpleNamespace(pose=SimpleNamespace(Pose=lambda **kw:pose)))
        tracker = SimpleNamespace(process=Mock(return_value=center), target=(200.,0.,280.,200.),
            last_seen=time.perf_counter(), work_ms=12., status='detected', detections=[])
        if supersede:
            def process(*args, **kwargs):
                iot._camera_session_id = 2
                return center
            tracker.process.side_effect = process
        if runtime_failure:
            tracker.process.side_effect = RuntimeError('DNN failed')
        iot.PersonTracker = Mock(return_value=tracker, side_effect=failure)
        iot.update_tracking = Mock(return_value=100.)
        iot.uart_send_angle = Mock()
        iot.detect_fall = Mock(return_value=False)
        iot._handle_fall = Mock()
        iot.socketio = object()
        iot.STATUS_EMIT_INTERVAL = 0
        def stop(*args):
            iot.camera_active = False
        iot._emit = Mock(side_effect=stop)
        iot._camera_ai_worker(1)
        return iot, pose

    def test_bbox_horizontal_center_not_pose_nose_and_fall_retained(self):
        iot, pose = self.worker()
        iot.update_tracking.assert_called_once_with(240., 320)
        iot.uart_send_angle.assert_called_once_with(100.)
        iot.detect_fall.assert_called_once()
        pose.process.assert_called_once()
        self.assertEqual(iot.AI['tracking_backend'], 'yolov3-tiny')

    def test_skip_or_loss_does_not_move(self):
        iot, _ = self.worker(center=None)
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()
        iot.detect_fall.assert_called_once()

    def test_observation_does_not_update_angle_or_send(self):
        iot, _ = self.worker(observe=True)
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()
        iot.detect_fall.assert_called_once()

    def test_missing_model_disables_tracking_not_fall(self):
        iot, _ = self.worker(failure=FileNotFoundError('model missing'))
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()
        iot.detect_fall.assert_called_once()
        self.assertEqual(iot.AI['tracking_backend'], 'unavailable')
        self.assertIn('model missing', iot.AI['tracking_error'])

    def test_runtime_dnn_failure_keeps_fall_and_disables_tracking(self):
        iot, _ = self.worker(runtime_failure=True)
        iot.detect_fall.assert_called_once()
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()
        self.assertEqual(iot.AI['tracking_backend'], 'unavailable')
        self.assertEqual(iot.AI['tracking_error'], 'DNN failed')

    def test_stale_capture_does_not_move(self):
        iot, _ = self.worker(stale=True)
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()

    def test_disabled_tracking_does_not_move(self):
        iot, _ = self.worker(disabled=True)
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()

    def test_tracking_without_pose_uses_original_frame_width(self):
        iot, pose = self.worker(no_pose=True, width=640, center=480.)
        pose.process.assert_not_called()
        iot.update_tracking.assert_called_once_with(480., 640)
        iot.uart_send_angle.assert_called_once_with(100.)

    def test_session_changed_during_dnn_does_not_move(self):
        iot, _ = self.worker(supersede=True)
        iot.update_tracking.assert_not_called()
        iot.uart_send_angle.assert_not_called()
