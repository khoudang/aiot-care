"""Run the real AI worker with deterministic frames and hand model outputs."""
import unittest
import time
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from iot_fixture import load_iot


def open_hand():
    points=[SimpleNamespace(x=.7,y=.8) for _ in range(21)]
    points[3].x=.5;points[4].x=.1
    for tip in (8,12,16,20):
        points[tip].y=.2;points[tip-2].y=.6
    return SimpleNamespace(landmark=points)


class GestureCadenceTests(unittest.TestCase):
    def run_worker(self,expire=False):
        iot=load_iot();iot.PROCESS_EVERY_N_FRAMES=3
        iot.ENABLE_GESTURE=True;iot.ENABLE_TRACKING=True;iot.ENABLE_FALL=False
        iot.camera_active=True;iot._camera_session_id=1;iot.socketio=None
        iot._latest_raw_slot.update(frame=np.zeros((24,32,3),dtype=np.uint8),gen=1,session_id=1,w=32,h=24,ts=time.perf_counter())
        observed=[]
        def pose_process(_):
            observed.append(dict(iot.AI))
            if expire and len(observed)==4:iot.OVERLAY_MAX_AGE_SEC=0
            iot._latest_raw_slot['gen']+=1
            if len(observed)>=7:iot.camera_active=False
            return SimpleNamespace(pose_landmarks=None)
        hands=Mock(process=Mock(side_effect=[SimpleNamespace(multi_hand_landmarks=[open_hand()]),SimpleNamespace(multi_hand_landmarks=None)]))
        iot.mp=SimpleNamespace(solutions=SimpleNamespace(
            pose=SimpleNamespace(Pose=lambda **kw:Mock(process=pose_process)),
            hands=SimpleNamespace(Hands=lambda **kw:hands)))
        iot._apply_gesture=Mock()
        iot._camera_ai_worker(1)
        return observed,iot

    def test_skipped_hands_cycles_preserve_result_without_repeating_actions(self):
        observed,iot=self.run_worker()
        expected=iot.GESTURE_LABELS['open']
        self.assertEqual(observed[3]['gesture'],expected,'Positive control: third cycle recognized open hand')
        self.assertEqual(observed[4]['gesture'],expected,'Skipped cycle must not erase last hand result')
        self.assertEqual(observed[5]['gesture'],expected)
        self.assertEqual(observed[6]['gesture'],'—','A real empty hand inference must clear old result')
        iot._apply_gesture.assert_called_once_with('open')

    def test_hand_diagnostics_distinguish_waiting_detection_and_no_hand(self):
        observed,iot=self.run_worker()
        self.assertEqual(observed[1].get('hand_status'),'waiting')
        self.assertEqual(observed[3].get('hand_status'),'detected')
        self.assertEqual(observed[3].get('hands_detected'),1)
        self.assertEqual(observed[4].get('hands_detected'),1)
        self.assertEqual(observed[6].get('hand_status'),'not_detected')
        self.assertEqual(observed[6].get('hands_detected'),0)

    def test_cached_result_expires_if_next_inference_is_late(self):
        observed,iot=self.run_worker(expire=True)
        self.assertEqual(observed[3]['gesture'],iot.GESTURE_LABELS['open'])
        self.assertEqual(observed[4]['gesture'],'—')
        self.assertEqual(observed[4]['hand_status'],'stale')
        self.assertEqual(observed[4]['hands_detected'],0)

if __name__=='__main__':unittest.main()
