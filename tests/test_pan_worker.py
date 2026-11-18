"""The real gateway functions loaded only through pre-import hardware mocks."""
import numpy as np
import pytest
from unittest.mock import Mock, patch
from iot_fixture import load_iot
from pan_motion import PanMotion


def test_tick_moves_between_yolo_runs_without_reapplying_error():
    iot = load_iot()
    assert hasattr(iot, '_pan_tick'), 'servo must have an independent session-guarded tick'
    pan = PanMotion()
    iot.camera_active = True
    iot.camera_mode = 'on'
    iot._camera_session_id = 7
    iot.tracking_enabled = True
    iot.AI['angle'] = 90.
    iot.uart_send_angle = Mock()
    pan.set_target(92., source_ts=100.)
    for n in range(1, 11):
        iot._pan_tick(7, pan, 100.+n*.09)
    assert iot.AI['angle'] == 92.
    assert 2 <= iot.uart_send_angle.call_count <= 10
    count = iot.uart_send_angle.call_count
    iot._pan_tick(7, pan, 100.99)
    assert iot.uart_send_angle.call_count == count


@pytest.mark.parametrize('guard', ['off', 'inactive', 'superseded', 'disabled', 'observe'])
def test_tick_revokes_pending_motion(guard):
    iot = load_iot()
    assert hasattr(iot, '_pan_tick'), 'servo tick guard missing'
    pan = PanMotion()
    pan.set_target(120., source_ts=100.)
    iot.camera_active, iot.camera_mode = True, 'on'
    iot._camera_session_id = 7
    iot.tracking_enabled = True
    iot.AI['angle'] = 90.
    iot.uart_send_angle = Mock()
    if guard == 'off': iot.camera_mode = 'off'
    if guard == 'inactive': iot.camera_active = False
    if guard == 'superseded': iot._camera_session_id = 8
    if guard == 'disabled': iot.tracking_enabled = False
    if guard == 'observe': iot.AI_OBSERVE_ONLY = True
    iot._pan_tick(7, pan, 100.09)
    assert pan.target is None
    assert iot.AI['angle'] == 90.
    iot.uart_send_angle.assert_not_called()


def test_queue_is_finite_bounded_inverted_and_deadzone_cancels():
    iot = load_iot()
    iot.SERVO_MIN, iot.SERVO_MAX = 0., 180.
    iot.SERVO_KP, iot.SERVO_SMOOTHING = 1., 1.
    iot.SERVO_DEADZONE_PX, iot.SERVO_INVERT = 24., False
    iot.AI['angle'] = 178.
    pan = PanMotion()
    iot._queue_tracking(300., 320., pan, 100.)
    assert pan.target == 180.
    assert iot.AI['angle'] == 178.
    iot.SERVO_INVERT = True
    iot._queue_tracking(300., 320., pan, 100.)
    assert pan.target == 172.
    iot._queue_tracking(160., 320., pan, 100.)
    assert pan.target is None


def test_pan_worker_startup_is_idle_and_shutdown_is_finite():
    iot = load_iot()
    import threading
    pan, stopped = PanMotion(), threading.Event()
    iot.camera_active, iot.camera_mode = True, 'on'
    iot._camera_session_id = 7
    iot.tracking_enabled = True
    iot.uart_send_angle = Mock()
    worker = iot._start_pan_worker(7, pan, stopped)
    stopped.set()
    worker.join(timeout=1.)
    assert not worker.is_alive()
    iot.uart_send_angle.assert_not_called()
