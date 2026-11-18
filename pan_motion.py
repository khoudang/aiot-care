"""Finite pan destinations, consumed by a separate monotonic 90 ms clock.

No hardware imports. Callers serialize access with the camera session lock.
Integer UART positions necessarily quantize this floating point trajectory.
"""
from math import copysign, isfinite, sqrt


class PanMotion:
    def __init__(self):
        self.clear()

    def clear(self):
        self.target = None
        self.velocity = 0.
        self.last_tick = None
        self.expires = 0.

    def set_target(self, angle, *, source_ts, speed=12.):
        if not all(isfinite(v) for v in (angle, source_ts, speed)) or speed <= 0:
            self.clear()
            return
        if self.target is None:
            self.last_tick = source_ts
        self.target = angle
        self.expires = source_ts + 1.
        self.speed = min(12., speed)

    def step(self, current, now):
        if self.target is None or now > self.expires:
            self.clear()
            return None
        dt = min(.1, max(0., now - self.last_tick))
        self.last_tick = now
        error = self.target - current
        if abs(error) < 1e-9 or dt <= 0:
            self.velocity = 0.
            return None
        # Bounded acceleration and remaining-distance braking, no idle catch-up.
        desired = copysign(min(self.speed, sqrt(2. * 48. * abs(error))), error)
        self.velocity += max(-48.*dt, min(48.*dt, desired-self.velocity))
        delta = self.velocity * dt
        # A new target can reverse direction: never coast away from it.
        if delta * error <= 0:
            return None
        delta = copysign(min(abs(error), abs(delta)), error)
        return current + delta
