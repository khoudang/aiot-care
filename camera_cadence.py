"""Thread-safe camera scheduling policy; no camera, network or actuator I/O."""
import math
import threading
import numpy as np


class CadencePolicy:
    def __init__(self, *, idle_after=30.0, active_video_fps=15.0,
                 idle_video_fps=3.0, idle_ai_fps=2.0):
        values = (idle_after, active_video_fps, idle_video_fps, idle_ai_fps)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError('Camera cadence values must be finite and positive')
        if idle_video_fps > active_video_fps:
            raise ValueError('Idle video rate cannot exceed active video rate')
        self.idle_after = idle_after
        self.active_video_fps = active_video_fps
        self.idle_video_fps = idle_video_fps
        self.idle_ai_fps = idle_ai_fps
        self._last_activity = None
        self._reason = 'startup'
        self._lock = threading.Lock()

    def activity(self, now, reason='pir'):
        with self._lock:
            if self._last_activity is None or now >= self._last_activity:
                self._last_activity, self._reason = now, reason

    def profile(self, now, *, mode='auto', pir_fresh=False, alarm=False):
        with self._lock:
            if mode == 'off':
                return {'profile': 'off', 'reason': 'manual',
                        'video_fps': 0.0, 'ai_fps': 0.0}
            if self._last_activity is None:
                self._last_activity = now
            if mode == 'on' or alarm or not pir_fresh:
                self._last_activity = now
                self._reason = ('manual' if mode == 'on' else
                                'alarm' if alarm else 'pir_unavailable')
            idle = mode == 'auto' and now - self._last_activity >= self.idle_after
            return {'profile': 'idle' if idle else 'active',
                    'reason': 'inactivity' if idle else self._reason,
                    'video_fps': self.idle_video_fps if idle else self.active_video_fps,
                    # Zero means no extra AI cap in active mode; hardware is the limit.
                    'ai_fps': self.idle_ai_fps if idle else 0.0}


class FrameMotionProbe:
    """Cheap, conservative image-change wake-up, not a person detector."""
    def __init__(self):
        self._previous = None

    def changed(self, frame):
        h, w = frame.shape[:2]
        small = frame[::max(1, h // 24), ::max(1, w // 32)].astype(np.float32)
        if small.ndim == 3:
            small = small.mean(axis=2)
        previous, self._previous = self._previous, small
        if previous is None or previous.shape != small.shape:
            return False
        # Lighting/noise may also wake the camera; prefer extra work to sleeping.
        return bool(np.mean(np.abs(small - previous) >= 20.0) >= .02)
