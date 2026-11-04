"""YOLO tracker tests: network boundary only is mocked; no model/hardware needed."""
import importlib
import unittest
from unittest.mock import Mock
import numpy as np


class PersonTrackerTests(unittest.TestCase):
    def tracker(self, rows, **kwargs):
        module = importlib.import_module('person_tracker')
        net = Mock()
        net.getUnconnectedOutLayersNames.return_value = ['out']
        net.forward.return_value = [np.array(rows, dtype=float)]
        cv = Mock()
        cv.dnn.readNet.return_value = net
        tracker = module.PersonTracker(__file__, __file__, cv=cv, **kwargs)
        return tracker, net, cv

    def test_confidence_uses_objectness_times_person_score_and_nms(self):
        tracker, net, cv = self.tracker([
            [.2,.5,.2,.6,.4,.9,.1],  # .36: below threshold
            [.6,.5,.3,.6,.9,.9,.1],
            [.61,.5,.3,.6,.8,.9,.1], # duplicate suppressed
            [.9,.5,.1,.2,.9,.1,.9],  # non-person
        ])
        result = tracker.process(np.zeros((100,200,3), dtype=np.uint8), now=1.)
        self.assertEqual(len(tracker.detections), 1)
        self.assertAlmostEqual(result, 120.)
        self.assertAlmostEqual(tracker.detections[0][1], .81)
        cv.dnn.readNet.assert_called_once_with(__file__, __file__)
        self.assertTrue(cv.dnn.blobFromImage.call_args.kwargs['swapRB'])

    def test_largest_initial_target_retained_then_lost_without_replaying_motion(self):
        small = [.2,.5,.15,.4,.9,.9]
        large = [.7,.5,.25,.8,.9,.9]
        tracker, net, _ = self.tracker([small, large], interval=.5, ttl=1.5)
        frame = np.zeros((100,200,3), dtype=np.uint8)
        self.assertAlmostEqual(tracker.process(frame, now=1.), 140.)
        self.assertIsNone(tracker.process(frame, now=1.1))
        self.assertEqual(net.forward.call_count, 1)
        # A different person grows larger, but the matching box remains selected.
        net.forward.return_value = [np.array([[.2,.5,.35,.9,.9,.9], large])]
        self.assertAlmostEqual(tracker.process(frame, now=1.6), 140.)
        net.forward.return_value = [np.array([small])]
        self.assertIsNone(tracker.process(frame, now=2.2))
        self.assertIsNone(tracker.process(frame, now=2.8))
        self.assertAlmostEqual(tracker.process(frame, now=3.4), 40.)
        net.forward.return_value = [np.empty((0,6))]
        self.assertIsNone(tracker.process(frame, now=4.))
        self.assertIsNone(tracker.process(frame, now=5.6))
        self.assertIsNone(tracker.target)
        self.assertEqual(tracker.status, 'not_detected')
        self.assertGreaterEqual(tracker.work_ms, 0)

    def test_missing_model_is_explicit(self):
        module = importlib.import_module('person_tracker')
        with self.assertRaisesRegex(FileNotFoundError, 'YOLO tracking model missing'):
            module.PersonTracker('not-present.cfg', 'not-present.weights', cv=Mock())


if __name__ == '__main__':
    unittest.main()
