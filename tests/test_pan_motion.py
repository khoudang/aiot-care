"""Pure motion model; no hardware imports or UART."""
import pytest
import importlib.util


def test_destination_is_consumed_once_at_twelve_degrees_per_second():
    assert importlib.util.find_spec('pan_motion') is not None, 'decoupled motion controller missing'
    from pan_motion import PanMotion
    pan = PanMotion()
    pan.set_target(120., source_ts=100., speed=12.)
    angle = 90.
    steps = []
    for i in range(1, 11):
        new = pan.step(angle, 100. + i * .09)
        if new is not None:
            steps.append(new-angle)
            angle = new
    assert len(steps) == 10
    assert 0 < steps[0] < steps[3]
    assert max(steps) <= 1.080001
    assert 98 < angle < 101
    assert pan.step(angle, 101.01) is None  # source capture expired
    assert pan.step(angle, 101.1) is None


def test_home_speed_no_overshoot_and_no_idle_catchup():
    from pan_motion import PanMotion
    pan = PanMotion()
    pan.set_target(90., source_ts=100., speed=6.)
    angle = 92.
    for n in range(1, 11):
        new = pan.step(angle, 100.+n*.09)
        if new is not None:
            assert 0 < angle-new <= .540001
            assert new >= 90.
            angle = new
    assert angle == 90.
    assert pan.step(angle, 100.99) is None
    pan.set_target(120., source_ts=102.)
    assert pan.step(angle, 102.9)-angle <= 1.200001


def test_acceleration_braking_reversal_and_target_clamping():
    from pan_motion import PanMotion
    pan = PanMotion()
    pan.set_target(93., source_ts=100.)
    angle, deltas = 90., []
    for n in range(1, 11):
        new = pan.step(angle, 100.+n*.09)
        if new is not None:
            deltas.append(new-angle)
            assert new <= 93.
            angle = new
    assert angle == 93.
    assert deltas[-1] < max(deltas)
    pan.set_target(90., source_ts=101.)
    for n in range(1, 10):
        new = pan.step(angle, 101.+n*.09)
        if new is not None:
            assert 90. <= new <= angle
            angle = new
    assert angle == 90.
