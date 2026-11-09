"""Camera authorization regressions with hardware boundaries stubbed."""
import threading
from unittest.mock import Mock

import numpy as np  # Load before load_iot temporarily replaces sys.modules.
import pytest

from iot_fixture import load_iot


def gateway():
    iot = load_iot()
    iot.set_camera_mode = iot._real_set_camera_mode
    iot._start_worker_thread = Mock(return_value=None)
    return iot


@pytest.mark.parametrize('mode', ['off', 'auto', 'on'])
def test_emergency_preserves_camera_authorization(mode):
    iot = gateway()
    iot.set_camera_mode(mode)
    iot.set_device = Mock()
    iot._cancel_commands = Mock()
    starts = iot._start_worker_thread.call_count

    iot._enter_emergency()

    assert iot.camera_mode == mode
    assert iot.camera_active is (mode != 'off')
    assert iot._start_worker_thread.call_count == starts
    assert iot._camera_profile()['profile'] == ('off' if mode == 'off' else 'active')
    iot.set_device.assert_any_call('patient', 'buzzer', state=True, source='auto', silent=True)
    for room in ('patient', 'living'):
        iot.set_device.assert_any_call(room, 'fan', state=False, source='auto', silent=True)
    assert not any(call.args[0] == 'kitchen' for call in iot.set_device.call_args_list)


@pytest.mark.parametrize('request_kind', ['setter', 'automatic'])
def test_delayed_auto_start_cannot_reopen_after_off(request_kind):
    iot = gateway()
    iot.camera_mode = 'auto'
    entered, resume = threading.Event(), threading.Event()
    original_start = iot._start_camera
    errors = []

    def paused_start(*args, **kwargs):
        entered.set()
        if not resume.wait(2):
            raise AssertionError('start was not resumed')
        return original_start(*args, **kwargs)

    iot._start_camera = paused_start

    def request_auto():
        try:
            if request_kind == 'setter':
                iot.set_camera_mode('auto')
            else:
                iot._maybe_auto_camera_on()
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=request_auto, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        assert iot.set_camera_mode('off') == {'active': False, 'mode': 'off'}
    finally:
        resume.set()
        thread.join(2)
    assert not thread.is_alive()
    assert not errors
    assert iot.camera_mode == 'off'
    assert not iot.camera_active
    iot._start_worker_thread.assert_not_called()


def test_delayed_off_cannot_stop_a_newer_on_request():
    iot = gateway()
    iot.set_camera_mode('on')
    entered, resume = threading.Event(), threading.Event()
    original_stop = iot._stop_camera
    errors = []

    def paused_stop(*args, **kwargs):
        entered.set()
        if not resume.wait(2):
            raise AssertionError('stop was not resumed')
        return original_stop(*args, **kwargs)

    iot._stop_camera = paused_stop

    def request_off():
        try:
            iot.set_camera_mode('off')
        except BaseException as exc:
            errors.append(exc)

    thread = threading.Thread(target=request_off, daemon=True)
    thread.start()
    try:
        assert entered.wait(2)
        assert iot.set_camera_mode('on')['active']
    finally:
        resume.set()
        thread.join(2)
    assert not thread.is_alive()
    assert not errors
    assert iot.camera_mode == 'on'
    assert iot.camera_active


def test_delayed_publisher_cannot_open_capture_after_off():
    iot = gateway()
    iot.set_camera_mode('auto')
    old_session = iot._camera_session_id
    iot.set_camera_mode('off')
    iot.cv2.VideoCapture.return_value.isOpened.return_value = False

    iot._camera_pub_worker(old_session)

    iot.cv2.VideoCapture.assert_not_called()
    assert not iot.camera_active


def test_stop_joins_outside_session_lock_and_allows_reentrant_on():
    iot = gateway()
    iot.set_camera_mode('on')
    acquired = threading.Event()

    def worker_exit():
        with iot._camera_session_lock:
            acquired.set()

    def join(timeout):
        worker = threading.Thread(target=worker_exit, daemon=True)
        worker.start()
        worker.join(.5)
        assert acquired.is_set(), 'stop joined while holding the session lock'

    iot._pub_thread = Mock(join=join)
    iot._ai_thread = None
    restarted = []

    def emit(event, payload):
        if event == 'camera_sync' and not payload['active'] and not restarted:
            restarted.append(True)
            iot.set_camera_mode('on')

    iot._emit = emit
    iot.set_camera_mode('off')
    assert acquired.is_set()
    assert restarted
    assert iot.camera_active
    assert iot.camera_mode == 'on'
    assert iot._camera_session_id == 2
