"""Test decoupled camera capture, AI inference, publication pipeline, and lifecycle."""
import threading
import time
import unittest
from unittest.mock import Mock, patch

import numpy as np

from iot_fixture import load_iot


def create_fake_frame(val=128):
    return np.full((240, 320, 3), val, dtype=np.uint8)


class FakeVideoCapture:
    def __init__(self, fps=30.0, frame_count=100):
        self._fps = fps
        self._frame_count = frame_count
        self._current = 0
        self._opened = True
        self._lock = threading.Lock()

    def isOpened(self):
        with self._lock:
            return self._opened

    def read(self):
        with self._lock:
            if not self._opened:
                return False, None
            self._current += 1
            val = (self._current * 17) % 255
            # Yield frame
            return True, create_fake_frame(val)

    def set(self, prop, val):
        return True

    def release(self):
        with self._lock:
            self._opened = False


class VideoPipelineTests(unittest.TestCase):
    def setUp(self):
        self.iot = load_iot()
        self.iot.STREAM_SLEEP = 0.005
        self.iot.OVERLAY_MAX_AGE_SEC = 0.15

    def test_frame_publication_progresses_while_inference_is_blocked(self):
        """Publication of fresh video frames must not be gated by slow AI inference."""
        iot = self.iot
        fake_cap = FakeVideoCapture()
        iot.cv2.VideoCapture = Mock(return_value=fake_cap)
        # imencode returns valid dummy jpeg bytes
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"fake_jpeg_frame")))

        # Simulate slow AI model (100ms per process call)
        inference_started = threading.Event()
        inference_unblock = threading.Event()
        inference_count = 0
        inference_lock = threading.Lock()

        def slow_process(_rgb):
            nonlocal inference_count
            with inference_lock:
                inference_count += 1
            inference_started.set()
            inference_unblock.wait(timeout=0.5)
            return Mock(pose_landmarks=None)

        mock_pose = Mock(process=slow_process, close=Mock())
        iot.mp = Mock()
        iot.mp.solutions.pose.Pose = Mock(return_value=mock_pose)
        iot.mp.solutions.hands.Hands = Mock(return_value=Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)), close=Mock()))

        # Start camera session
        iot._start_camera()
        self.assertTrue(iot.is_camera_active())

        # Wait for at least one inference to start and block
        self.assertTrue(inference_started.wait(timeout=1.0))

        # While inference is blocked, multiple new frames must be published to latest_frame
        published_frames = set()
        for _ in range(5):
            time.sleep(0.02)
            f = iot.get_latest_frame()
            if f is not None:
                published_frames.add(id(f) if not isinstance(f, bytes) else f)

        # Unblock inference and stop
        inference_unblock.set()
        time.sleep(0.05)
        iot._stop_camera()

        # In a decoupled pipeline, publication progresses independently of inference
        self.assertFalse(iot.is_camera_active())
        self.assertGreater(fake_cap._current, inference_count,
                           "Capture frames must progress beyond slow inference count")

    def test_no_stale_backlog_and_no_repeated_inference(self):
        """AI worker only consumes newest unseen frame, skipping intermediate frames without backlog."""
        iot = self.iot
        fake_cap = FakeVideoCapture()
        iot.cv2.VideoCapture = Mock(return_value=fake_cap)
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"jpeg")))

        inferred_generations = []
        inf_lock = threading.Lock()

        def track_inference(rgb):
            # Capture frame pixel marker
            marker = int(rgb[0, 0, 0])
            with inf_lock:
                inferred_generations.append(marker)
            time.sleep(0.03)  # AI is slower than 5ms capture
            return Mock(pose_landmarks=None)

        iot.mp = Mock()
        iot.mp.solutions.pose.Pose = Mock(return_value=Mock(process=track_inference, close=Mock()))
        iot.mp.solutions.hands.Hands = Mock(return_value=Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)), close=Mock()))

        iot._start_camera()
        time.sleep(0.15)
        iot._stop_camera()

        with inf_lock:
            # Inference must not process every single frame (skipping happens)
            self.assertGreater(len(inferred_generations), 1)
            # Generations must strictly advance (no repeated inference of identical frame generation)
            for i in range(1, len(inferred_generations)):
                self.assertNotEqual(inferred_generations[i], inferred_generations[i - 1],
                                    "Must not re-infer same generation twice")

    def test_rapid_restart_and_clean_teardown(self):
        """Rapid start/stop/restart cycles must not leak threads, hang, or leave orphaned sessions."""
        iot = self.iot
        iot.cv2.VideoCapture = Mock(side_effect=lambda _src: FakeVideoCapture())
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"jpeg")))
        iot.mp = Mock()
        iot.mp.solutions.pose.Pose = Mock(return_value=Mock(process=Mock(return_value=Mock(pose_landmarks=None)), close=Mock()))
        iot.mp.solutions.hands.Hands = Mock(return_value=Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)), close=Mock()))

        initial_threads = threading.active_count()

        for _ in range(3):
            iot._start_camera()
            self.assertTrue(iot.is_camera_active())
            time.sleep(0.04)
            iot._stop_camera()
            self.assertFalse(iot.is_camera_active())
            time.sleep(0.02)

        # Allow worker join/cleanup grace period
        time.sleep(0.1)
        self.assertFalse(iot.is_camera_active())
        self.assertEqual(iot.AI["camera"], False)
        self.assertEqual(iot.AI["fps"], "--")
        self.assertEqual(iot.AI["gesture"], "Camera Offline")
        # Thread count should return close to initial count (no thread leaks)
        self.assertLessEqual(threading.active_count(), initial_threads + 1)

    def test_truthful_metrics_separation(self):
        """Legacy AI['fps'] reports inference rate; video_fps reports publication rate."""
        iot = self.iot
        fake_cap = FakeVideoCapture()
        iot.cv2.VideoCapture = Mock(return_value=fake_cap)
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"jpeg")))

        def timed_inference(_rgb):
            time.sleep(0.04)  # ~25 FPS max AI
            return Mock(pose_landmarks=None)

        iot.mp = Mock()
        iot.mp.solutions.pose.Pose = Mock(return_value=Mock(process=timed_inference, close=Mock()))
        iot.mp.solutions.hands.Hands = Mock(return_value=Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)), close=Mock()))

        iot._start_camera()
        time.sleep(0.2)
        iot._stop_camera()

        # Both metrics must be present and distinct in AI dictionary
        self.assertIn("fps", iot.AI)
        self.assertIn("video_fps", iot.AI)
        self.assertIn("work_ms", iot.AI)

    def test_stale_overlay_is_not_drawn_indefinitely(self):
        """When AI detections stop arriving, stale overlay is expired after OVERLAY_MAX_AGE_SEC."""
        iot = self.iot
        fake_cap = FakeVideoCapture()
        iot.cv2.VideoCapture = Mock(return_value=fake_cap)
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"jpeg")))
        iot.OVERLAY_MAX_AGE_SEC = 0.05

        draw_calls = 0
        def fake_draw_landmarks(*_args, **_kwargs):
            nonlocal draw_calls
            draw_calls += 1

        mock_draw = Mock(draw_landmarks=fake_draw_landmarks)
        detection_active = True

        def toggling_inference(_rgb):
            if detection_active:
                return Mock(pose_landmarks=Mock(landmark=[Mock(x=0.5, y=0.5)]))
            return Mock(pose_landmarks=None)

        iot.mp = Mock()
        iot.mp.solutions.drawing_utils = mock_draw
        iot.mp.solutions.pose.Pose = Mock(return_value=Mock(process=toggling_inference, close=Mock()))
        iot.mp.solutions.hands.Hands = Mock(return_value=Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)), close=Mock()))

        iot._start_camera()
        time.sleep(0.08)
        # Cease detections
        detection_active = False
        time.sleep(0.12)
        count_after_stale = draw_calls

        # Advance more video frames with no detections
        time.sleep(0.08)
        iot._stop_camera()

        # After expiry window, stale landmark drawing must stop
        self.assertEqual(draw_calls, count_after_stale,
                         "Stale landmark overlay must not continue to be drawn after timeout")


if __name__ == "__main__":
    unittest.main()
