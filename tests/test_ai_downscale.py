"""AI inference must run on a downscaled frame, without changing geometry semantics."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from iot_fixture import load_iot


def standing():
    pts = [SimpleNamespace(x=.5, y=.5) for _ in range(33)]
    pts[0] = SimpleNamespace(x=.5, y=.3)
    pts[11] = SimpleNamespace(x=.45, y=.35); pts[12] = SimpleNamespace(x=.55, y=.35)
    pts[23] = SimpleNamespace(x=.45, y=.6); pts[24] = SimpleNamespace(x=.55, y=.6)
    for i in (27, 28):
        pts[i] = SimpleNamespace(x=.45, y=.9)
    return SimpleNamespace(landmark=pts)


class AIDownscaleTests(unittest.TestCase):
    def test_inference_frame_is_downscaled_and_geometry_follows(self):
        iot = load_iot()
        iot.AI_INFERENCE_WIDTH = 320
        iot.PROCESS_EVERY_N_FRAMES = 1
        iot.camera_active = True; iot._camera_session_id = 1; iot.socketio = None
        iot._latest_raw_slot.update(frame=np.zeros((480, 640, 3), dtype=np.uint8), gen=1,
                                    session_id=1, w=640, h=480)
        seen = {}
        iot.cv2 = SimpleNamespace(
            COLOR_BGR2RGB=1, INTER_AREA=2,
            cvtColor=lambda img, code: img,
            resize=lambda img, size, interpolation=None: np.zeros((size[1], size[0], 3), dtype=np.uint8),
        )

        def pose_process(fr):
            seen['pose'] = fr.shape
            iot._latest_raw_slot['gen'] += 1
            return SimpleNamespace(pose_landmarks=standing())

        def hands_process(fr):
            seen['hands'] = fr.shape
            iot.camera_active = False
            return SimpleNamespace(multi_hand_landmarks=None)

        hands = Mock(process=Mock(side_effect=hands_process))
        iot.mp = SimpleNamespace(solutions=SimpleNamespace(
            pose=SimpleNamespace(Pose=lambda **kw: Mock(process=pose_process)),
            hands=SimpleNamespace(Hands=lambda **kw: hands)))
        captured = {}
        iot.detect_fall = lambda lms, w, h: captured.update(w=w, h=h) or False
        iot.ENABLE_FALL = True; iot.ENABLE_GESTURE = True; iot.ENABLE_TRACKING = False
        iot._apply_gesture = Mock()
        iot._camera_ai_worker(1)

        self.assertEqual(seen['pose'][1], 320, 'pose must receive the downscaled width')
        self.assertEqual(seen['pose'][0], 240, 'aspect ratio must be preserved')
        self.assertEqual(seen['hands'][1], 320, 'hands must share the downscaled frame')
        self.assertEqual((captured['w'], captured['h']), (320, 240), 'fall geometry must use inference pixels')

    def test_small_frames_are_not_upscaled(self):
        iot = load_iot()
        iot.AI_INFERENCE_WIDTH = 320
        iot.PROCESS_EVERY_N_FRAMES = 1
        iot.camera_active = True; iot._camera_session_id = 1; iot.socketio = None
        iot._latest_raw_slot.update(frame=np.zeros((240, 320, 3), dtype=np.uint8), gen=1,
                                    session_id=1, w=320, h=240)
        calls = []
        iot.cv2 = SimpleNamespace(COLOR_BGR2RGB=1, INTER_AREA=2,
                                  cvtColor=lambda img, code: img,
                                  resize=lambda *a, **k: calls.append(a) or a[0])

        def pose_process(fr):
            iot._latest_raw_slot['gen'] += 1
            iot.camera_active = False
            return SimpleNamespace(pose_landmarks=None)

        iot.mp = SimpleNamespace(solutions=SimpleNamespace(
            pose=SimpleNamespace(Pose=lambda **kw: Mock(process=pose_process)),
            hands=SimpleNamespace(Hands=lambda **kw: Mock(process=Mock(return_value=SimpleNamespace(multi_hand_landmarks=None))))))
        iot.ENABLE_FALL = True; iot.ENABLE_GESTURE = True; iot.ENABLE_TRACKING = False
        iot._camera_ai_worker(1)
        self.assertEqual(calls, [], 'a 320-wide frame must pass through untouched')


if __name__ == '__main__':
    unittest.main()
