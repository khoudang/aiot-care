"""Load a fresh gateway with external dependencies stubbed before execution."""
import ast
from pathlib import Path
import sys
import types
from unittest.mock import Mock, patch


def load_iot():
    path = Path(__file__).resolve().parents[1] / 'iot.py'
    source = path.read_text(encoding='utf-8')
    config = types.ModuleType('config')
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module == 'config':
            for name in node.names:
                setattr(config, name.name, 1)
    config.AI_OBSERVE_ONLY = False
    config.AI_INFERENCE_WIDTH = 320
    config.TELEMETRY_STALE_SEC = 10.0
    config.NODES = []
    config.MAX_HISTORY = 10
    config.GAS_SMOOTH_WINDOW = 5
    config.GAS_WARN_THRESHOLD = 1500
    config.GAS_HIGH_THRESHOLD = 2500
    config.FALL_HOLD_SEC = 3.5
    config.FALL_TORSO_DEG = 55.0
    config.FALL_ASPECT = 1.1
    config.FALL_MIN_CONFIDENCE = 0.5
    config.FALL_MIN_BODY_SIZE = 0.15
    config.FALL_MAX_BODY_SIZE = 1.25
    config.GESTURE_MIN_SIZE = 0.08
    config.GESTURE_STABLE_CYCLES = 1
    config.OVERLAY_MAX_AGE_SEC = 0.8
    config.PROCESS_EVERY_N_FRAMES = 3
    dependencies = {name: Mock() for name in (
        'cv2', 'requests', 'flask_socketio', 'mediapipe', 'bleak', 'serial', 'database')}
    dependencies['config'] = config
    module = types.ModuleType('isolated_iot')
    with patch.dict(sys.modules, dependencies):
        exec(compile(source, str(path), 'exec'), module.__dict__)
    for name in ('_emit', 'log_audit', 'send_telegram_alert_async',
                 'set_camera_mode', 'push_history'):
        setattr(module, name, Mock())
    return module
