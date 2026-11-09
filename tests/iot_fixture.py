"""Load a fresh gateway with external dependencies stubbed before execution."""
import ast
from pathlib import Path
import sys
import types
from typing import Any
from unittest.mock import Mock, patch


def load_iot() -> Any:
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
    config.CAMERA_IDLE_AFTER_SEC = 30.0
    config.CAMERA_ACTIVE_VIDEO_FPS = 15.0
    config.CAMERA_IDLE_VIDEO_FPS = 3.0
    config.CAMERA_IDLE_AI_FPS = 2.0
    config.YOLO_CFG_PATH = 'missing-test-model.cfg'
    config.YOLO_WEIGHTS_PATH = 'missing-test-model.weights'
    config.YOLO_CONFIDENCE = .5
    config.YOLO_NMS_THRESHOLD = .4
    config.YOLO_INTERVAL_SEC = .5
    config.YOLO_TARGET_TTL_SEC = 1.5
    config.YOLO_INPUT_SIZE = 224
    config.NODES = []
    config.MAX_HISTORY = 10
    config.GAS_SMOOTH_WINDOW = 5
    config.GAS_WARN_THRESHOLD = 1500
    config.GAS_HIGH_THRESHOLD = 2500
    dependencies = {name: Mock() for name in (
        'cv2', 'requests', 'flask_socketio', 'mediapipe', 'bleak', 'serial', 'database')}
    dependencies['config'] = config
    module = types.ModuleType('isolated_iot')
    with patch.dict(sys.modules, dependencies):
        exec(compile(source, str(path), 'exec'), module.__dict__)
    module._real_set_camera_mode = module.set_camera_mode
    for name in ('_emit', 'log_audit', 'send_telegram_alert_async',
                 'set_camera_mode', 'push_history'):
        setattr(module, name, Mock())
    return module
