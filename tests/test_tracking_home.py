"""Home timeout through the real worker, with simulated frames/clock/UART."""
from types import SimpleNamespace
from unittest.mock import Mock, patch
import numpy as np
import pytest
from iot_fixture import load_iot


def run_sequence(samples, *, observe=False, disabled=False, stale=False, fail=False,
                 supersede=False):
    iot = load_iot()
    iot.ENABLE_FALL = iot.ENABLE_GESTURE = False
    iot.ENABLE_TRACKING = True
    iot.tracking_enabled = not disabled
    iot.AI_OBSERVE_ONLY = observe
    iot.camera_active = True
    iot._camera_session_id = 1
    iot.SERVO_CENTER = 90
    iot.SERVO_MIN, iot.SERVO_MAX = 0, 180
    iot.SERVO_KP, iot.SERVO_SMOOTHING = .06, .35
    iot.SERVO_DEADZONE_PX, iot.SERVO_INVERT = 24, False
    iot.AI['angle'] = 120.
    iot._camera_profile = Mock(return_value={'profile': 'active', 'ai_fps': 0})
    clock = [100.]
    index = [0]
    tracker = SimpleNamespace(target=None, last_seen=None, work_ms=0.,
                              status='waiting', detections=[])
    def process(frame):
        _, status = samples[index[0]]
        tracker.status = status
        tracker.detections = [((0, 0, 10, 10), .9)] if status in ('detected', 'other_person') else []
        if supersede and index[0] == len(samples) - 1:
            iot._camera_session_id = 2
        if fail and index[0] == len(samples) - 1:
            raise RuntimeError('DNN failed')
        if status == 'detected':
            tracker.last_seen = clock[0]
            return 160.  # centered: resets absence without pan correction
        return None
    tracker.process = process
    iot.PersonTracker = Mock(return_value=tracker)
    def frame():
        clock[0] = 100. + samples[index[0]][0]
        iot._latest_raw_slot.update(frame=np.zeros((240, 320, 3), dtype=np.uint8),
            gen=index[0] + 1, session_id=1, w=320, h=240,
            ts=clock[0] - (10 if stale else 0))
    angles = []
    def emit(*args):
        angles.append(iot.AI['angle'])
        index[0] += 1
        if index[0] == len(samples):
            iot.camera_active = False
        else:
            frame()
    iot.uart_send_angle = Mock()
    iot._emit = Mock(side_effect=emit)
    iot.socketio = object()
    iot.STATUS_EMIT_INTERVAL = 0
    frame()
    with patch.object(iot.time, 'perf_counter', side_effect=lambda: clock[0]):
        iot._camera_ai_worker(1)
    return iot, angles


def test_home_starts_after_five_seconds_not_before():
    iot, angles = run_sequence([(0, 'not_detected'), (4.99, 'not_detected'),
                                (5, 'not_detected')])
    assert angles == [120., 120., 117.]
    iot.uart_send_angle.assert_called_once_with(117.)


def test_reacquisition_resets_absence_timer():
    _, angles = run_sequence([(0, 'not_detected'), (4, 'detected'),
        (5, 'not_detected'), (9.99, 'not_detected'), (10, 'not_detected')])
    assert angles == [120., 120., 120., 120., 117.]


@pytest.mark.parametrize('option', ['observe', 'disabled', 'stale', 'fail', 'supersede'])
def test_unsafe_or_inactive_worker_never_returns_home(option):
    iot, _ = run_sequence([(0, 'not_detected'), (5, 'not_detected')], **{option: True})
    iot.uart_send_angle.assert_not_called()


def test_skipped_detection_is_not_evidence_of_an_empty_room():
    iot, angles = run_sequence([(0, 'not_detected'), (5, 'skipped')])
    assert angles == [120., 120.]
    iot.uart_send_angle.assert_not_called()


def test_other_visible_person_cancels_home_even_when_target_lost():
    iot, angles = run_sequence([(0, 'not_detected'), (5, 'other_person'),
                                (6, 'not_detected'), (10.99, 'not_detected')])
    assert angles == [120.] * 4
    iot.uart_send_angle.assert_not_called()


def test_home_is_bounded_stops_at_center_and_does_not_repeat():
    samples = [(0, 'not_detected')] + [(5 + n * .5, 'not_detected') for n in range(12)]
    iot, angles = run_sequence(samples)
    assert angles[1:11] == [117., 114., 111., 108., 105., 102., 99., 96., 93., 90.]
    assert angles[-2:] == [90., 90.]
    assert iot.uart_send_angle.call_count == 10
