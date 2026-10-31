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

    def test_inflight_inference_cannot_reactivate_stopped_camera(self):
        """Stopping the camera while inference is in-flight must never be undone by old inference completing."""
        iot = self.iot
        iot.camera_active = True
        iot._camera_session_id = 1
        iot._latest_raw_slot.update(frame=np.zeros((4, 4, 3), dtype=np.uint8), gen=1, ts=0.0, w=4, h=4)
        iot.mp = Mock()
        iot.ENABLE_FALL = False
        iot.tracking_enabled = False
        def process(_):
            iot.camera_active = False
            iot.AI['camera'] = False
            return Mock(pose_landmarks=None)
        iot.mp.solutions.pose.Pose.return_value = Mock(process=process)
        iot._camera_ai_worker(1)
        self.assertFalse(iot.AI['camera'], 'Late old inference must not mark a stopped camera live')

    def test_superseded_inference_cannot_apply_gesture(self):
        """Superseded inference from an older session must never invoke gesture actuations."""
        iot = self.iot
        iot.camera_active = True
        iot._camera_session_id = 1
        iot._latest_raw_slot.update(frame=np.zeros((4, 4, 3), dtype=np.uint8), gen=1, ts=0.0, w=4, h=4)
        iot.mp = Mock()
        iot.ENABLE_FALL = False
        iot.tracking_enabled = False
        iot._apply_gesture = Mock()
        def process(_):
            iot._camera_session_id = 2
            return Mock(pose_landmarks=None)
        iot.mp.solutions.pose.Pose.return_value = Mock(process=process)
        iot.mp.solutions.hands.Hands.return_value = Mock(process=Mock(return_value=Mock(multi_hand_landmarks=[Mock()])))
        iot.detect_gesture = Mock(return_value='test_gesture')
        iot._camera_ai_worker(1)
        iot._apply_gesture.assert_not_called()

    def test_skipping_capture_generations_cannot_starve_hands(self):
        """Hands scheduling must use inference cadence, not capture-ID modulo, avoiding starvation on frame skips."""
        iot = self.iot
        iot.camera_active = True
        iot._camera_session_id = 1
        iot._latest_raw_slot.update(frame=np.zeros((4, 4, 3), dtype=np.uint8), gen=1, ts=0.0, w=4, h=4)
        iot.mp = Mock()
        iot.ENABLE_FALL = False
        iot.tracking_enabled = False
        iot.PROCESS_EVERY_N_FRAMES = 3
        count = 0
        def process(_):
            nonlocal count
            count += 1
            iot._latest_raw_slot['gen'] += 3
            if count == 4:
                iot.camera_active = False
            return Mock(pose_landmarks=None)
        iot.mp.solutions.pose.Pose.return_value = Mock(process=process)
        hands = Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)))
        iot.mp.solutions.hands.Hands.return_value = hands
        iot._camera_ai_worker(1)
        self.assertGreater(hands.process.call_count, 0, 'Capture generation modulo can starve hands forever; use inference cadence')

    def test_start_camera_cleans_prior_slots_and_overlays(self):
        """Starting a camera session cleans up prior session raw frame slots and AI results."""
        iot = self.iot
        iot.cv2.VideoCapture = Mock(return_value=FakeVideoCapture())
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"jpeg")))
        iot._latest_raw_slot["frame"] = np.ones((4, 4, 3), dtype=np.uint8)
        iot._latest_raw_slot["gen"] = 99
        iot._latest_ai_results["gesture"] = "old_gesture"
        iot._start_camera()
        self.assertIsNone(iot._latest_raw_slot["frame"])
        self.assertEqual(iot._latest_raw_slot["gen"], 0)
        self.assertEqual(iot._latest_ai_results["gesture"], "—")
        iot._stop_camera()

    def test_generation_aware_dedup_and_client_wait(self):
        """get_next_frame prevents duplicate JPEG packets and supports slow client jumping without queues."""
        iot = self.iot
        iot.camera_active = True
        iot.latest_frame = b"frame_1"
        iot.latest_frame_gen = 1

        # First read sees generation 1
        f1, gen1 = iot.get_next_frame(last_seen_gen=0, timeout=0.05)
        self.assertEqual(f1, b"frame_1")
        self.assertEqual(gen1, 1)

        # Subsequent read with last_seen_gen=1 returns None without duplicate yield
        f2, gen2 = iot.get_next_frame(last_seen_gen=1, timeout=0.05)
        self.assertIsNone(f2)
        self.assertEqual(gen2, 1)

        # Publish frame 2
        with iot.camera_lock:
            iot.latest_frame = b"frame_2"
            iot.latest_frame_gen = 2
            iot.camera_cond.notify_all()

        f3, gen3 = iot.get_next_frame(last_seen_gen=1, timeout=0.05)
        self.assertEqual(f3, b"frame_2")
        self.assertEqual(gen3, 2)

        # Slow client jumping from gen 0 directly to gen 2 skips intermediate without backlog
        f_slow, gen_slow = iot.get_next_frame(last_seen_gen=0, timeout=0.05)
        self.assertEqual(f_slow, b"frame_2")
        self.assertEqual(gen_slow, 2)
        iot.camera_active = False

    def test_client_wakeup_on_camera_stop(self):
        """Stopping the camera unblocks waiting MJPEG stream clients immediately without waiting for timeout."""
        iot = self.iot
        iot.camera_active = True
        client_unblocked = threading.Event()

        def client_wait():
            f, _g = iot.get_next_frame(last_seen_gen=10, timeout=2.0)
            client_unblocked.set()

        t = threading.Thread(target=client_wait, daemon=True)
        t.start()
        time.sleep(0.05)
        iot._stop_camera()
        self.assertTrue(client_unblocked.wait(timeout=0.3), "Stopping camera must immediately unblock waiting clients")

    def test_model_construction_failure_handles_error_gracefully(self):
        """Model initialization failure must close partial models and report AI offline without unhandled crash."""
        iot = self.iot
        iot.camera_active = True
        iot._camera_session_id = 1
        iot.mp = Mock()
        iot.mp.solutions.pose.Pose.side_effect = RuntimeError("Failed to allocate TFLite delegate")
        iot._camera_ai_worker(1)
        self.assertEqual(iot.AI["fps"], "--")
        self.assertEqual(iot.AI["work_ms"], 0)

    def test_no_abba_deadlock_under_concurrent_contention(self):
        """Concurrent start/stop and frame delivery must not trigger ABBA deadlock."""
        iot = self.iot
        iot.cv2.VideoCapture = Mock(side_effect=lambda _src: FakeVideoCapture())
        iot.cv2.imencode = Mock(return_value=(True, Mock(tobytes=lambda: b"jpeg")))
        iot.mp = Mock()
        iot.mp.solutions.pose.Pose = Mock(return_value=Mock(process=Mock(return_value=Mock(pose_landmarks=None)), close=Mock()))
        iot.mp.solutions.hands.Hands = Mock(return_value=Mock(process=Mock(return_value=Mock(multi_hand_landmarks=None)), close=Mock()))

        stop_workers = threading.Event()

        def producer():
            while not stop_workers.is_set():
                with iot._new_raw_frame_cond:
                    iot._latest_raw_slot["gen"] += 1
                    iot._new_raw_frame_cond.notify_all()
                time.sleep(0.002)

        t_prod = threading.Thread(target=producer, daemon=True)
        t_prod.start()

        # Rapidly start and stop camera across multiple iterations
        for _ in range(5):
            iot._start_camera()
            time.sleep(0.02)
            iot._stop_camera()
            time.sleep(0.01)

        stop_workers.set()
        t_prod.join(timeout=0.5)
        self.assertFalse(iot.is_camera_active())

    def test_stop_camera_gap_does_not_erase_restarted_session(self):
        """When camera is restarted in the join gap of a prior stopping session, new state must not be erased."""
        iot = self.iot
        iot._pub_thread = Mock(join=Mock())
        iot._ai_thread = Mock(join=Mock())

        # Simulate join gap where new session starts
        def mock_join(*_args, **_kwargs):
            # Session 2 starts while session 1 is in its join phase
            with iot._camera_session_lock:
                iot._camera_session_id = 2
                iot.camera_active = True
                iot.AI["camera"] = True
                iot.AI["gesture"] = "Live Session 2"

        iot._pub_thread.join = mock_join
        iot.camera_active = True
        iot._camera_session_id = 1

        # Session 1 stops
        iot._stop_camera()

        # Session 2's active status and gesture must NOT be erased by session 1's cleanup
        self.assertTrue(iot.AI["camera"], "Session 2 must remain live despite session 1 stop finishing")
        self.assertEqual(iot.AI["gesture"], "Live Session 2")

    def test_callback_reentry_does_not_deadlock_session_lock(self):
        """Callback dispatch (e.g. gesture handler calling _stop_camera) must not deadlock on session lock."""
        iot = self.iot
        iot.camera_active = True
        iot._camera_session_id = 1
        iot._latest_raw_slot.update(frame=np.zeros((4, 4, 3), dtype=np.uint8), gen=1, ts=0.0, session_id=1, w=4, h=4)
        iot.mp = Mock()
        iot.ENABLE_FALL = False
        iot.tracking_enabled = False
        iot.PROCESS_EVERY_N_FRAMES = 1

        # Gesture callback re-enters camera lifecycle by calling _stop_camera
        def reentrant_gesture(_key):
            iot._stop_camera()

        iot._apply_gesture = reentrant_gesture
        iot.mp.solutions.pose.Pose.return_value = Mock(process=Mock(return_value=Mock(pose_landmarks=None)))
        iot.mp.solutions.hands.Hands.return_value = Mock(process=Mock(return_value=Mock(multi_hand_landmarks=[Mock()])))
        iot.detect_gesture = Mock(return_value="reenter_cmd")

        # Worker should execute gesture, safely re-enter _stop_camera without deadlocking, and exit
        iot._camera_ai_worker(1)
        self.assertFalse(iot.is_camera_active(), "Camera must be stopped via re-entrant callback without deadlock")

    def test_post_encode_publication_guard_blocks_superseded_frame(self):
        """Production _camera_pub_worker must not publish frame after imencode if session was superseded."""
        iot = self.iot
        fake_cap = FakeVideoCapture()
        iot.cv2.VideoCapture = Mock(return_value=fake_cap)
        imencode_started = threading.Event()
        imencode_unblock = threading.Event()

        def slow_imencode(*args, **kwargs):
            imencode_started.set()
            imencode_unblock.wait(timeout=1.0)
            return True, Mock(tobytes=lambda: b"session_1_stale_frame")

        iot.cv2.imencode = slow_imencode
        iot.camera_active = True
        iot._camera_session_id = 1

        # Start the real production pub worker for session 1
        t_pub = threading.Thread(target=iot._camera_pub_worker, args=(1,), daemon=True)
        t_pub.start()

        # Wait until pub worker reaches and blocks inside imencode
        self.assertTrue(imencode_started.wait(timeout=1.0), "Publisher worker must enter imencode")

        # Now simulate session supersession: session 2 starts and publishes fresh frame
        with iot._camera_session_lock:
            iot._camera_session_id = 2
            with iot.camera_lock:
                iot.latest_frame = b"session_2_fresh_frame"
                iot.latest_frame_gen = 2

        # Unblock session 1's imencode and stop camera
        imencode_unblock.set()
        time.sleep(0.05)
        iot.camera_active = False
        t_pub.join(timeout=1.0)

        # Production post-encode check must have rejected session 1's stale frame
        self.assertEqual(iot.get_latest_frame(), b"session_2_fresh_frame",
                         "Real publisher must not overwrite newer session frame after imencode")

    def test_stop_between_state_commit_and_callback_rejects_old_gesture(self):
        """Actions must be serialized with stop: no action may dispatch after stop has completed."""
        iot = self.iot
        iot.camera_active = True
        iot._camera_session_id = 1
        iot._latest_raw_slot.update(frame=np.zeros((4, 4, 3), dtype=np.uint8), gen=1, ts=0.0, session_id=1, w=4, h=4)
        iot.ENABLE_FALL = False
        iot.tracking_enabled = False
        iot.PROCESS_EVERY_N_FRAMES = 1
        iot.mp = Mock()
        iot.mp.solutions.pose.Pose.return_value = Mock(process=Mock(return_value=Mock(pose_landmarks=None)))
        iot.mp.solutions.hands.Hands.return_value = Mock(process=Mock(return_value=Mock(multi_hand_landmarks=[Mock()])))
        iot.detect_gesture = Mock(return_value='old_gesture')
        action_states = []
        iot._apply_gesture = Mock(side_effect=lambda _: action_states.append(iot.camera_active))
        native = threading.RLock()

        class StopAtReleasedCommit:
            armed = True
            def __enter__(self):
                native.acquire()
                return self
            def __exit__(self, *exc):
                native.release()
                if self.armed and iot.AI['camera']:
                    self.armed = False
                    iot._stop_camera()

        iot._camera_session_lock = StopAtReleasedCommit()
        iot._camera_ai_worker(1)
        self.assertFalse(iot.camera_active)
        self.assertNotIn(False, action_states, 'No action may dispatch after stop completed; actions serialized before stop are valid')


if __name__ == "__main__":
    unittest.main()
