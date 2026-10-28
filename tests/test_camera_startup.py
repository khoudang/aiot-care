import types
import unittest
from unittest.mock import Mock

from iot_fixture import load_iot


class CameraStartupTests(unittest.TestCase):
    def test_missing_mediapipe_solutions_does_not_kill_camera_capture(self):
        iot = load_iot()
        iot.mp = types.SimpleNamespace()
        iot.camera_active = True
        cap = Mock()
        cap.isOpened.return_value = True

        def finish_capture():
            iot.camera_active = False
            return False, None

        cap.read.side_effect = finish_capture
        iot.cv2.VideoCapture.return_value = cap
        iot._push_alert = Mock()
        iot.process_camera_stream()
        cap.read.assert_called_once()
        cap.release.assert_called_once()
        self.assertFalse(iot.AI['ai_available'])
        self.assertFalse(iot.camera_active)
        iot._push_alert.assert_called_once()
