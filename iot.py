"""
iot.py — Lớp IoT của AIoT Care Station.

Chức năng:
  * Kết nối BLE tới 3 node (patient / living / kitchen), nhận telemetry JSON,
    gửi lệnh điều khiển thiết bị theo từng phòng.
  * Camera phòng người bệnh: bật theo PIR (auto) hoặc toggle thủ công qua web;
    chạy MediaPipe Pose để bám người (tracking) + phát hiện té ngã, và
    MediaPipe Hands (giãn cách frame) để nhận cử chỉ điều khiển đèn/quạt.
  * Gửi góc servo pan qua UART tới ESP(1) để camera bám người trái/phải.
  * Máy trạng thái cảnh báo 3 mức (bình thường / nhẹ / khẩn cấp) + chờ xác nhận,
    tích hợp Telegram.

Không dùng MQTT. Toàn bộ realtime đẩy lên web bằng Socket.IO.
"""

import asyncio
import json
import math
import queue
import sys
import threading
import time
from node_protocol import build_command
from collections import deque

import cv2
import numpy as np
import requests
from flask_socketio import emit

try:
    import mediapipe as mp
except Exception:                       # cho phép chạy web khi thiếu mediapipe
    mp = None

try:
    from bleak import BleakClient, BleakScanner
except Exception:
    BleakClient = None
    BleakScanner = None

try:
    import serial                       # pyserial cho UART
except Exception:
    serial = None

from config import (
    ALERT_COOLDOWN_SEC,
    AI_OBSERVE_ONLY,
    OVERLAY_MAX_AGE_SEC,
    TELEMETRY_STALE_SEC,
    BLE_RECONNECT_DELAY,
    CAMERA_HEIGHT,
    CAMERA_MODE_DEFAULT,
    CAMERA_MOTION_TIMEOUT,
    CAMERA_WIDTH,
    COMMAND_DEBOUNCE_SEC,
    ENABLE_FALL,
    ENABLE_GESTURE,
    ENABLE_TRACKING,
    FALL_ASPECT,
    FALL_HOLD_SEC,
    FALL_TORSO_DEG,
    GAS_HIGH_THRESHOLD,
    GAS_SMOOTH_WINDOW,
    GAS_WARN_THRESHOLD,
    GESTURE_COOLDOWN_SEC,
    JPEG_QUALITY,
    MAX_HISTORY,
    NODES,
    PROCESS_EVERY_N_FRAMES,
    SERVO_CENTER,
    SERVO_DEADZONE_PX,
    SERVO_INVERT,
    SERVO_KP,
    SERVO_MAX,
    SERVO_MIN,
    SERVO_SEND_INTERVAL,
    SERVO_SMOOTHING,
    STATUS_EMIT_INTERVAL,
    STREAM_SLEEP,
    UART_BAUD,
    UART_ENABLE,
    UART_PORT,
    VIDEO_SOURCE,
)
from database import (
    get_config_value, log_audit, vn_now_sql, fetch_gesture_mappings,
)


# ================================================================== #
#  Khởi tạo
# ================================================================== #
socketio = None


def init_iot(socketio_instance):
    global socketio
    socketio = socketio_instance


def _emit(event, data):
    """Phát sự kiện lên tất cả client (an toàn khi gọi từ thread nền)."""
    if socketio is not None:
        socketio.emit(event, data)


def now_ts():
    return time.time()


def safe_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "on", "open", "yes"}
    return False


def as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ================================================================== #
#  Trạng thái toàn hệ thống
# ================================================================== #
state_lock = threading.Lock()
camera_lock = threading.Lock()

ROOMS = {
    "patient": {
        "temp": None, "hum": None, "motion": False,
        "light": False, "fan": False, "fan_speed": 0, "buzzer": False,
        "updated_at": 0,
    },
    "living": {
        "temp": None, "hum": None, "motion": False, "lux": None,
        "light": False, "light_level": 0, "fan": False, "fan_speed": 0,
        "auto": True, "updated_at": 0,
    },
    "kitchen": {
        "gas": None, "smoke": False, "flame": False,
        "window": False, "exhaust": False, "exhaust_speed": None,
        "light": False, "buzzer": False, "phase": "unknown", "event_id": None,
        "gas_unit": "raw_adc", "calibration_status": "uncalibrated", "ppm_c3h8": None,
        "updated_at": 0,
    },
}

NODE_ONLINE = {"patient": False, "living": False, "kitchen": False}
# Node connectivity state machine:
# Active states: "disconnected", "connecting", "subscribing", "ready".
# Sensor freshness is reported separately; it never resets transport or safety state.
# "ready" indicates successful GATT start_notify subscription, not guaranteed continuous telemetry freshness.
NODE_STATES = {"patient": "disconnected", "living": "disconnected", "kitchen": "disconnected"}
_SENSOR_FIELDS = {"patient": ("temp", "hum", "motion"),
                  "living": ("temp", "hum", "lux", "motion"),
                  "kitchen": ("gas", "flame")}
_sensor_seen_at = {room: dict.fromkeys(fields) for room, fields in _SENSOR_FIELDS.items()}

AI = {
    "gesture": "—", "fps": "--", "video_fps": "--", "latency": "--", "work_ms": 0,
    "angle": SERVO_CENTER, "fall": False, "camera": False,
    "observe_only": AI_OBSERVE_ONLY, "fall_suspected": False,
}

# Camera / tracking
camera_active = False
camera_mode = CAMERA_MODE_DEFAULT          # auto | on | off
tracking_enabled = ENABLE_TRACKING
last_motion_ts = 0.0
camera_thread = None
latest_frame = None
camera_owner_user_id = None

# Decoupled camera pipeline synchronization
_camera_session_lock = threading.Lock()
_camera_session_id = 0
_pub_thread = None
_ai_thread = None
_raw_frame_lock = threading.Lock()
_new_raw_frame_cond = threading.Condition(_raw_frame_lock)
_latest_raw_slot = {"frame": None, "gen": 0, "ts": 0.0, "w": CAMERA_WIDTH, "h": CAMERA_HEIGHT}
_ai_results_lock = threading.Lock()
_latest_ai_results = {
    "pose_landmarks": None,
    "multi_hand_landmarks": None,
    "gesture": "—",
    "ts": 0.0,
}

# Cảnh báo
alert_level = "normal"                     # normal | light | emergency | awaiting
_emergency_snapshot = None
_restoration_started = None
_restoration_seen = {}
_kitchen_safe_since = None
_kitchen_sample_at = None
_kitchen_emergency = False
_alarm_silenced = False
_fall_buzzer_saved = None
_fall_restore_target = None
_safety_retry_at = {}
SAFETY_RECHECK_SEC = 5.0
KITCHEN_SAFE_HOLD_SEC = 10.0
KITCHEN_SAMPLE_TIMEOUT_SEC = 3.0
gas_window = {"kitchen": deque(maxlen=GAS_SMOOTH_WINDOW)}

services_started = False

# Lịch sử cho biểu đồ (mỗi phòng giữ các trường số cần vẽ)
histories = {
    "patient": {"labels": deque(maxlen=MAX_HISTORY), "temp": deque(maxlen=MAX_HISTORY),
                "hum": deque(maxlen=MAX_HISTORY)},
    "living": {"labels": deque(maxlen=MAX_HISTORY), "temp": deque(maxlen=MAX_HISTORY),
               "hum": deque(maxlen=MAX_HISTORY), "lux": deque(maxlen=MAX_HISTORY)},
    "kitchen": {"labels": deque(maxlen=MAX_HISTORY), "gas": deque(maxlen=MAX_HISTORY)},
}

# Hàng đợi lệnh BLE theo từng phòng
command_queues = {room: queue.Queue(maxsize=20) for room in ROOMS}
_delivery_lock = threading.RLock()
_pending_commands = {room: {} for room in ROOMS}
_command_sequence = 0
COMMAND_ATTEMPTS = 4
COMMAND_ACK_TIMEOUT = 2.0
COMMAND_TTL = 30.0
ble_clients = {room: None for room in ROOMS}
_connected_ble_devices = {room: None for room in ROOMS}
ble_loop = None
BLE_MAC_CONFIG_KEYS = {room: f"ble_mac_{room}" for room in ROOMS}
_ble_reconfigure = {room: threading.Event() for room in ROOMS}
_ble_devices = {}
_ble_devices_seen_at = 0.0
_ble_discovery_lock = None
BLE_SCAN_CACHE_TTL = 10.0
MANUAL_SCAN_RATE_LIMIT = 2.0
_last_manual_scan_at = 0.0


class CommandTimingTracer:
    """Bounded in-memory timing trace for BLE commands using monotonic clock.

    Deltas are strictly calculated using same-process time.monotonic() to avoid
    clock skew across independent Pi / ESP32 / browser boundaries.
    Both storage structures (_traces deque and _active dict) are bounded.
    """

    def __init__(self, maxlen=200):
        self._maxlen = maxlen
        self._traces = deque(maxlen=maxlen)
        self._active = {}
        self._lock = threading.Lock()

    def record_enqueued(self, room, command_id, device, sig):
        now = time.monotonic()
        rec = {
            "id": command_id,
            "room": room,
            "device": device,
            "sig": sig,
            "enqueued_at": now,
            "write_start_at": None,
            "first_write_start_at": None,
            "write_done_at": None,
            "ack_at": None,
            "ack_status": None,
            "applied_at": None,
            "status": "enqueued",
            "attempts": 0,
            "error": None,
        }
        with self._lock:
            if len(self._active) >= self._maxlen:
                oldest_k = next(iter(self._active))
                self._active.pop(oldest_k, None)
            self._active[(room, command_id)] = rec
            self._traces.append(rec)

    def record_write_start(self, room, command_id, attempt):
        now = time.monotonic()
        with self._lock:
            rec = self._active.get((room, command_id))
            if rec:
                if rec["first_write_start_at"] is None:
                    rec["first_write_start_at"] = now
                rec["write_start_at"] = now
                rec["write_done_at"] = None
                rec["ack_at"] = None
                rec["ack_status"] = None
                rec["attempts"] = attempt
                rec["status"] = "writing"

    def record_write_done(self, room, command_id, error=None):
        now = time.monotonic()
        with self._lock:
            rec = self._active.get((room, command_id))
            if rec is None:
                for r in reversed(self._traces):
                    if r["room"] == room and r["id"] == command_id:
                        rec = r
                        break
            if rec:
                rec["write_done_at"] = now
                if error:
                    if rec["status"] not in ("ack_applied", "ack_rejected", "canceled", "timeout_error"):
                        rec["status"] = "write_error"
                    rec["error"] = str(error)
                    # Transport failure is retryable; terminal ACK/cancel/TTL removes it.
                elif not rec["status"].startswith("ack_") and rec["status"] not in ("canceled", "timeout_error"):
                    rec["status"] = "written"

    def record_ack(self, room, command_id, status):
        now = time.monotonic()
        with self._lock:
            rec = self._active.get((room, command_id))
            if rec is None:
                for r in reversed(self._traces):
                    if r["room"] == room and r["id"] == command_id:
                        rec = r
                        break
            if rec:
                rec["ack_at"] = now
                rec["ack_status"] = status
                rec["status"] = f"ack_{status}"
                if status in ("applied", "rejected"):
                    self._active.pop((room, command_id), None)

    def record_applied(self, room, device):
        """Retained for backwards-compatibility; exact acceptance requires record_ack."""
        pass

    def record_canceled(self, room, command_id=None, device=None):
        now = time.monotonic()
        with self._lock:
            for (r, cid), rec in list(self._active.items()):
                if r == room and (command_id is None or cid == command_id) and (device is None or rec.get("device") == device):
                    rec["status"] = "canceled"
                    self._active.pop((r, cid), None)

    def record_error(self, room, command_id, error_msg):
        now = time.monotonic()
        with self._lock:
            rec = self._active.pop((room, command_id), None)
            if rec is None:
                for r in reversed(self._traces):
                    if r["room"] == room and r["id"] == command_id:
                        rec = r
                        break
            if rec:
                rec["status"] = "timeout_error"
                rec["error"] = str(error_msg)

    def get_summary(self, target_room=None):
        with self._lock:
            records = [dict(r) for r in self._traces if target_room is None or r["room"] == target_room]

        queue_latencies = []
        gatt_latencies = []
        ack_latencies = []
        total_latencies = []
        errors = 0

        for r in records:
            if r.get("error") or r.get("status") in ("write_error", "timeout_error", "ack_rejected"):
                errors += 1
            first_write = r.get("first_write_start_at")
            if first_write is not None and r.get("enqueued_at") is not None:
                queue_latencies.append((first_write - r["enqueued_at"]) * 1000.0)
            if r.get("write_done_at") is not None and r.get("write_start_at") is not None:
                gatt_latencies.append((r["write_done_at"] - r["write_start_at"]) * 1000.0)
            terminal_ack = r.get("status") in ("ack_applied", "ack_rejected")
            if terminal_ack and r.get("ack_at") is not None and r.get("write_start_at") is not None:
                # A notification may arrive before the awaited write returns.
                # Anchor ACK timing to write START, never to write completion.
                ack_latencies.append((r["ack_at"] - r["write_start_at"]) * 1000.0)
            end_time = r.get("ack_at") if terminal_ack else None
            if end_time is not None and r.get("enqueued_at") is not None:
                total_latencies.append((end_time - r["enqueued_at"]) * 1000.0)

        def calc_stats(arr):
            if not arr:
                return {"count": 0, "median_ms": None, "p95_ms": None, "min_ms": None, "max_ms": None}
            s = sorted(arr)
            n = len(s)
            p95_idx = int(math.ceil(0.95 * n)) - 1
            med_idx = n // 2
            median = s[med_idx] if n % 2 != 0 else (s[med_idx - 1] + s[med_idx]) / 2.0
            return {
                "count": n,
                "median_ms": round(median, 2),
                "p95_ms": round(s[min(max(p95_idx, 0), n - 1)], 2),
                "min_ms": round(s[0], 2),
                "max_ms": round(s[-1], 2),
            }

        queue_len = {}
        with _delivery_lock:
            for rm in ROOMS:
                if target_room is None or rm == target_room:
                    queue_len[rm] = len(_pending_commands.get(rm, {}))

        return {
            "room": target_room or "all",
            "total_commands": len(records),
            "errors": errors,
            "error_rate": round(errors / len(records), 4) if records else 0.0,
            "queue_lengths": queue_len,
            "queue_latency": calc_stats(queue_latencies),
            "gatt_write_latency": calc_stats(gatt_latencies),
            "ack_rtt_latency": calc_stats(ack_latencies),
            "total_latency": calc_stats(total_latencies),
            "recent_traces": [
                {
                    "id": r["id"],
                    "room": r["room"],
                    "device": r["device"],
                    "attempts": r["attempts"],
                    "status": r["status"],
                    "error": r["error"],
                    "total_ms": round(((r["ack_at"] - r["enqueued_at"]) * 1000.0), 2)
                    if r.get("status") in ("ack_applied", "ack_rejected") and r.get("ack_at") is not None and r.get("enqueued_at") is not None else None
                }
                for r in list(records)[-20:]
            ],
            "source": "gateway_monotonic",
            "ack_rtt_anchor": "gatt_write_start",
            "measurement_scope": "gateway_to_firmware_ack_not_physical_output",
        }


timing_tracer = CommandTimingTracer(maxlen=200)
_command_wakeups = {room: None for room in ROOMS}


def get_command_timing_stats(room=None):
    return timing_tracer.get_summary(room)

# UART
uart = None
_last_servo_send = 0.0

# Chống dội lệnh / cử chỉ
_last_cmd = {}                             # (room, device) -> (payload, ts)
_last_gesture_action = {"key": None, "ts": 0.0}

# Chống spam cảnh báo
_last_alert_at = {}


def snapshot_histories():
    with state_lock:
        return {room: {k: list(v) for k, v in series.items()}
                for room, series in histories.items()}


def telemetry_status():
    """Read-only sensor freshness; never disconnect, cancel or clear safety state."""
    now = time.monotonic()
    result = {}
    with state_lock:
        for room, samples in _sensor_seen_at.items():
            fields = {}
            ages = []
            for key, seen in samples.items():
                age = max(0.0, now - seen) if seen is not None else None
                if age is not None:
                    ages.append(age)
                fields[key] = {"age_sec": round(age, 2) if age is not None else None,
                               "status": "missing" if age is None else
                               ("fresh" if age <= TELEMETRY_STALE_SEC else "stale")}
            fresh = sum(field["status"] == "fresh" for field in fields.values())
            status = ("offline" if not NODE_ONLINE[room] else
                      "awaiting" if not ages else
                      "fresh" if fresh == len(fields) else
                      "partial" if fresh else "stale")
            result[room] = {"status": status, "transport_state": NODE_STATES[room],
                            "transport_connected": bool(NODE_ONLINE[room]),
                            "age_sec": round(min(ages), 2) if ages else None,
                            "stale_after_sec": TELEMETRY_STALE_SEC, "fields": fields}
    return result


def _record_sensor_sample(room, payload):
    now = time.monotonic()
    with state_lock:
        for source, value in payload.items():
            key = _NUMERIC_ALIASES.get(source, source)
            if key not in _sensor_seen_at[room]:
                continue
            valid = (type(value) is bool if key in ("motion", "flame") else
                     type(value) in (int, float) and math.isfinite(value))
            if key == "gas":
                valid = valid and 0 <= value <= 4095
            if valid:
                _sensor_seen_at[room][key] = now


def snapshot_all():
    with state_lock:
        rooms = {r: dict(v) for r, v in ROOMS.items()}
        ai = dict(AI)
        nodes = dict(NODE_ONLINE)
        node_states = dict(NODE_STATES)
        cam = {"active": camera_active, "mode": camera_mode, "tracking": tracking_enabled}
        alert = {"level": alert_level}
    return {"rooms": rooms, "nodes": nodes, "node_states": node_states, "ai": ai, "camera": cam,
            "alert": alert, "histories": snapshot_histories(), "telemetry": telemetry_status()}


def push_history(room):
    label = time.strftime("%H:%M:%S")
    r = ROOMS[room]
    h = histories[room]
    h["labels"].append(label)
    for key in h:
        if key == "labels":
            continue
        h[key].append(r.get(key))


# ================================================================== #
#  Áp dụng telemetry từ node BLE
# ================================================================== #
_NUMERIC_ALIASES = {
    "temp": "temp", "temperature": "temp",
    "hum": "hum", "humi": "hum", "humidity": "hum",
    "gas": "gas", "ppm": "gas",
    "lux": "lux", "light_level": "light_level", "brightness": "light_level",
    "fan_speed": "fan_speed", "speed": "fan_speed",
    "exhaust_speed": "exhaust_speed",
}
_BOOL_KEYS = ["motion", "light", "fan", "buzzer", "smoke", "flame", "window", "exhaust", "auto"]


def apply_node_payload(room, payload):
    """Nhận dict telemetry từ 1 node, cập nhật state phòng tương ứng."""
    global last_motion_ts
    global _kitchen_safe_since, _kitchen_sample_at, _kitchen_emergency

    if room not in ROOMS:
        return
    _record_sensor_sample(room, payload)

    if room == "kitchen" and any(key in payload for key in ("gas", "smoke", "flame")):
        sample_time = time.monotonic()
        gas = payload.get("gas")
        valid = (type(gas) in (int, float) and math.isfinite(gas) and 0 <= gas <= 4095
                 and type(payload.get("smoke")) is bool
                 and type(payload.get("flame")) is bool)
        continuous = (_kitchen_sample_at is not None and
                      sample_time - _kitchen_sample_at <= KITCHEN_SAMPLE_TIMEOUT_SEC)
        safe = valid and gas < GAS_WARN_THRESHOLD and not payload["smoke"] and not payload["flame"]
        if not safe:
            _kitchen_safe_since = None
        elif _kitchen_safe_since is None or not continuous:
            _kitchen_safe_since = sample_time
        _kitchen_sample_at = sample_time if valid else None
        if type(payload.get("emergency")) is bool:
            _kitchen_emergency = payload["emergency"]

    with state_lock:
        r = ROOMS[room]
        for src, dst in _NUMERIC_ALIASES.items():
            if src in payload and dst in r and payload[src] is not None:
                num = as_number(payload[src])
                if num is not None:
                    r[dst] = round(num, 2) if dst in ("temp", "hum") else num
        for key in _BOOL_KEYS:
            if key in payload and key in r:
                r[key] = safe_bool(payload[key])
        if room == "kitchen":
            if payload.get("phase") in ("normal", "warning", "emergency", "wait_confirm"):
                r["phase"] = payload["phase"]
            if type(payload.get("event_id")) is int and 0 <= payload["event_id"] <= 0xFFFFFFFF:
                r["event_id"] = payload["event_id"]
        r["updated_at"] = now_ts()

    # trung bình trượt cho gas (giảm báo giả)
    if room in gas_window and ROOMS[room].get("gas") is not None:
        gas_window[room].append(as_number(ROOMS[room]["gas"]) or 0)

    push_history(room)

    # PIR phòng bệnh -> bật camera theo chế độ auto
    if room == "patient" and ROOMS["patient"]["motion"]:
        last_motion_ts = now_ts()
        _maybe_auto_camera_on()

    evaluate_alerts()
    _observe_restoration(room, payload)
    _observe_fall_restoration(room, payload)

    _emit("room_update", {"room": room, "data": dict(ROOMS[room])})
    if room == "patient":
        _emit("sensor_chart_update", snapshot_histories())


def _gas_avg(room):
    w = gas_window.get(room)
    if w and len(w) > 0:
        return sum(w) / len(w)
    return as_number(ROOMS[room].get("gas"))


# ================================================================== #
#  Node online / offline
# ================================================================== #
def set_node_online(room, online, state=None):
    if room not in ROOMS:
        return
    resolved_state = state or ("ready" if online else "disconnected")
    is_ready = (resolved_state == "ready")
    NODE_STATES[room] = resolved_state
    _restoration_seen.pop(room, None)
    if room == "kitchen" and not is_ready:
        _cancel_commands("kitchen")
        ROOMS["kitchen"]["phase"] = "unknown"
        ROOMS["kitchen"]["event_id"] = None
    changed = NODE_ONLINE.get(room) != is_ready
    NODE_ONLINE[room] = is_ready
    if changed:
        _emit("node_status", dict(NODE_ONLINE))
        _emit("node_state", dict(NODE_STATES))
        if not is_ready and resolved_state == "disconnected":
            log_audit(f"Node {room} mất kết nối (BLE offline)", user_id=None)
            _push_alert("node_" + room,
                        f"Node {room_name(room)} mất kết nối.", "node")
    else:
        _emit("node_state", dict(NODE_STATES))


def room_name(room):
    return {"patient": "phòng người bệnh", "living": "phòng khách",
            "kitchen": "phòng bếp"}.get(room, room)


# ================================================================== #
#  BLE — kết nối 3 node đồng thời
# ================================================================== #
def _make_notify_handler(room):
    buffer = bytearray()

    def apply_frame(frame):
        payload = json.loads(frame.decode("utf-8"))
        if isinstance(payload, dict):
            target = payload.get("room", room)
            target = "patient" if target == "bed" else target
            if target == room:
                if "ack" in payload:
                    if type(payload["ack"]) is not int:
                        return
                    with _delivery_lock:
                        pending = _pending_commands[room].get(payload["ack"])
                        if pending and payload.get("status") in ("applied", "rejected"):
                            del _pending_commands[room][payload["ack"]]
                            timing_tracer.record_ack(room, payload["ack"], payload["status"])
                            if payload["status"] == "rejected":
                                _fail_restoration(room)
                                _emit("command_error", {"room": room, "message": "Node rejected command"})
                            # Wake up sender loop immediately to dispatch next queued command
                            wakeup = _command_wakeups.get(room)
                            if wakeup is not None and ble_loop is not None and ble_loop.is_running():
                                ble_loop.call_soon_threadsafe(wakeup.set)
                            elif wakeup is not None:
                                wakeup.set()
                        elif pending and payload.get("status") == "busy":
                            timing_tracer.record_ack(room, payload["ack"], "busy")
                            now = time.monotonic()
                            attempts = pending.get("attempts", 1)
                            backoff = min(0.2 * (2 ** (attempts - 1)), 1.0)
                            pending["retry_at"] = now + backoff
                            pending["sent"] = None
                            wakeup = _command_wakeups.get(room)
                            if wakeup is not None and ble_loop is not None and ble_loop.is_running():
                                ble_loop.call_later(backoff, wakeup.set)
                            elif wakeup is not None:
                                wakeup.set()
                else:
                    apply_node_payload(room, payload)

    def handler(_sender, data):
        buffer.extend(data)
        if len(buffer) > 2048:
            buffer.clear()
            return
        while b"\n" in buffer:
            frame, _, remainder = buffer.partition(b"\n")
            buffer[:] = remainder
            if not frame.strip():
                continue
            try:
                apply_frame(frame)
            except (ValueError, UnicodeError):
                pass
        # Compatibility with old firmware sending one complete JSON notification.
        try:
            json.loads(buffer.decode("utf-8"))
        except (ValueError, UnicodeError):
            return
        frame = bytes(buffer)
        buffer.clear()
        apply_frame(frame)
    return handler


def _configured_mac(node):
    """SQLite override, falling back to the address supplied by config.py."""
    return get_config_value(BLE_MAC_CONFIG_KEYS[node["room"]], node["mac"])


def ble_node_settings():
    return [{"room": node["room"], "mac": _configured_mac(node),
             "online": bool(NODE_ONLINE[node["room"]]),
             "state": NODE_STATES.get(node["room"], "disconnected")} for node in NODES]


def _connected_macs():
    macs = set()
    for room, dev in _connected_ble_devices.items():
        c = ble_clients.get(room)
        if dev is not None and c is not None and getattr(c, "is_connected", False):
            if hasattr(dev, "address"):
                macs.add(dev.address.upper())
    return macs


async def _scan_ble_devices():
    global _last_manual_scan_at
    now = time.monotonic()
    if now - _last_manual_scan_at < MANUAL_SCAN_RATE_LIMIT:
        devices = await _discover_ble_devices(force=False)
    else:
        _last_manual_scan_at = now
        devices = await _discover_ble_devices(force=True)
    return sorted([{"name": device.name or "Thiết bị BLE", "mac": device.address.upper()}
                   for device in devices], key=lambda device: (device["name"], device["mac"]))


async def _discover_ble_devices(force=False):
    """Cache BLEDevice objects so concurrent clients don't start implicit scans."""
    global _ble_discovery_lock, _ble_devices_seen_at
    if _ble_discovery_lock is None:
        _ble_discovery_lock = asyncio.Lock()
    async with _ble_discovery_lock:
        now = time.monotonic()
        cache_ttl = getattr(sys.modules.get("iot"), "BLE_SCAN_CACHE_TTL", BLE_SCAN_CACHE_TTL)
        # A recent scan is useful even when it found no devices. Without this,
        # absent nodes trigger back-to-back scans and starve the other nodes.
        if not force and now - _ble_devices_seen_at < cache_ttl:
            return list(_ble_devices.values())
        devices = await BleakScanner.discover(timeout=5.0)
        # Preserve already-connected nodes absent from advertisements
        connected_devices = {}
        for r, dev in _connected_ble_devices.items():
            c = ble_clients.get(r)
            if dev is not None and c is not None and getattr(c, "is_connected", False):
                if hasattr(dev, "address"):
                    connected_devices[dev.address.upper()] = dev
        _ble_devices.clear()
        _ble_devices.update(connected_devices)
        _ble_devices.update({device.address.upper(): device for device in devices})
        _ble_devices_seen_at = now
        return list(_ble_devices.values())


async def _find_ble_device(mac):
    if not mac:
        return None
    target = mac.strip().upper()
    now = time.monotonic()
    cache_ttl = getattr(sys.modules.get("iot"), "BLE_SCAN_CACHE_TTL", BLE_SCAN_CACHE_TTL)
    dev = _ble_devices.get(target)
    if dev is not None and (now - _ble_devices_seen_at < cache_ttl or target in _connected_macs()):
        return dev
    await _discover_ble_devices(force=False)
    return _ble_devices.get(target)


def scan_ble_devices():
    if BleakScanner is None or ble_loop is None or not ble_loop.is_running():
        raise RuntimeError("BLE chưa sẵn sàng trên gateway.")
    future = asyncio.run_coroutine_threadsafe(_scan_ble_devices(), ble_loop)
    try:
        return future.result(timeout=9)
    except Exception:
        future.cancel()
        raise


def reconnect_ble_node(room):
    """Ask the node loop to close its current link and read the new MAC."""
    global _ble_devices_seen_at
    _ble_reconfigure[room].set()
    _cancel_commands(room)
    _ble_devices_seen_at = 0.0
    for key in list(_last_cmd):
        if key[0] == room:
            _last_cmd.pop(key, None)


def _calc_pending_timeout(room):
    with _delivery_lock:
        if not _pending_commands[room]:
            return 2.0
        ident, pending = next(iter(_pending_commands[room].items()))
        now = time.monotonic()
        retry_at = pending.get("retry_at", 0.0)
        if retry_at > now:
            return min(2.0, max(0.01, retry_at - now))
        sent = pending.get("sent")
        if sent is None:
            return 0.01
        elapsed = now - sent
        rem = max(0.01, COMMAND_ACK_TIMEOUT - elapsed)
        return min(rem, 2.0)


async def _node_loop(node):
    room = node["room"]
    notify_uuid = node["notify_uuid"]
    command_uuid = node["command_uuid"]

    if BleakClient is None:
        print("[BLE] bleak chưa được cài — bỏ qua node", room)
        set_node_online(room, False, state="disconnected")
        return

    _command_wakeups[room] = asyncio.Event()
    reconnect_delay = BLE_RECONNECT_DELAY

    while True:
        try:
            _ble_reconfigure[room].clear()
            mac = _configured_mac(node)
            if not mac or not mac.strip():
                set_node_online(room, False, state="disconnected")
                print(f"[BLE] MAC not configured; waiting for node {room}")
                for _ in range(20):
                    if _ble_reconfigure[room].is_set():
                        break
                    await asyncio.sleep(0.05)
                continue

            mac = mac.strip().upper()
            set_node_online(room, False, state="connecting")
            print(f"[BLE {room}] connecting to {mac} ...")
            device = await _find_ble_device(mac)
            if device is None:
                raise RuntimeError(f"BLE scan did not find configured device {mac}")

            async with BleakClient(device) as client:
                if _ble_reconfigure[room].is_set() or _configured_mac(node).strip().upper() != mac:
                    continue
                ble_clients[room] = client
                _connected_ble_devices[room] = device

                set_node_online(room, False, state="subscribing")
                await client.start_notify(notify_uuid, _make_notify_handler(room))

                # Online / ready ONLY after start_notify success!
                set_node_online(room, True, state="ready")
                print(f"[BLE {room}] ready (subscribed)")
                _resync_safety(room)
                reconnect_delay = BLE_RECONNECT_DELAY

                while client.is_connected and not _ble_reconfigure[room].is_set():
                    await _send_pending(room, client, command_uuid)
                    timeout = _calc_pending_timeout(room)
                    try:
                        await asyncio.wait_for(_command_wakeups[room].wait(), timeout=timeout)
                    except asyncio.TimeoutError:
                        pass
                    _command_wakeups[room].clear()

        except Exception as exc:
            print(f"[BLE {room}] disconnected / reconnect:", exc)
            reconnect_delay = min(reconnect_delay * 1.5, 10.0)
        finally:
            ble_clients[room] = None
            _connected_ble_devices[room] = None
            set_node_online(room, False, state="disconnected")
            await asyncio.sleep(reconnect_delay)


async def _ble_main():
    await asyncio.gather(*[_node_loop(node) for node in NODES])


def _ble_thread():
    global ble_loop
    ble_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(ble_loop)
    ble_loop.run_until_complete(_ble_main())


def enqueue_command(room, text):
    global _command_sequence
    if room not in command_queues:
        return False
    with _delivery_lock:
        if len(_pending_commands[room]) >= 20:
            return False
        command = json.loads(text)
        _command_sequence = _command_sequence % 0xFFFFFFFF + 1
        command["id"] = _command_sequence
        text = json.dumps(command, separators=(",", ":"))
        try:
            command_queues[room].put_nowait(text)
        except queue.Full:
            return False
        now = time.monotonic()
        _pending_commands[room][_command_sequence] = {
            "text": text, "created": now, "sent": None, "attempts": 0}
        cmd_name = command.get("cmd") or "unknown"
        sig = {k: v for k, v in command.items() if k not in ("id", "event_id")}
        timing_tracer.record_enqueued(room, _command_sequence, cmd_name, sig)
        wakeup = _command_wakeups.get(room)
        if wakeup is not None and ble_loop is not None and ble_loop.is_running():
            ble_loop.call_soon_threadsafe(wakeup.set)
        return True


def _cancel_commands(room, device=None):
    """A new safety phase invalidates queued and retrying older commands."""
    with _delivery_lock:
        for ident, pending in list(_pending_commands[room].items()):
            cmd_dev = None
            try:
                cmd_dev = json.loads(pending["text"]).get("cmd")
            except Exception:
                pass
            if device is None or cmd_dev == device:
                del _pending_commands[room][ident]
                timing_tracer.record_canceled(room, command_id=ident, device=cmd_dev)
        retained = []
        while True:
            try:
                text = command_queues[room].get_nowait()
                cmd_obj = {}
                try:
                    cmd_obj = json.loads(text)
                except Exception:
                    pass
                if device is not None and cmd_obj.get("cmd") != device:
                    retained.append(text)
                else:
                    timing_tracer.record_canceled(room, command_id=cmd_obj.get("id"), device=cmd_obj.get("cmd"))
            except queue.Empty:
                break
        for text in retained:
            command_queues[room].put_nowait(text)


async def _send_pending(room, client, command_uuid):
    _reconcile_safety(room)
    # One in-flight command per room preserves auto/manual command ordering.
    with _delivery_lock:
        while not command_queues[room].empty():
            command_queues[room].get_nowait()
        if not _pending_commands[room]:
            return
        ident, pending = next(iter(_pending_commands[room].items()))
        now = time.monotonic()
        retry_at = pending.get("retry_at", 0.0)
        if retry_at > now:
            return
        due = pending["sent"] is None or now - pending["sent"] >= COMMAND_ACK_TIMEOUT
        if now - pending["created"] >= COMMAND_TTL or (due and pending["attempts"] >= COMMAND_ATTEMPTS):
            del _pending_commands[room][ident]
            _fail_restoration(room)
            timing_tracer.record_error(room, ident, "Command acknowledgement timeout")
            _emit("command_error", {"room": room, "message": "Command acknowledgement timeout"})
            return
        if not due:
            return
        pending["sent"] = now
        pending["attempts"] += 1
        cmd_text = pending["text"]
        attempt = pending["attempts"]
    timing_tracer.record_write_start(room, ident, attempt)
    try:
        await client.write_gatt_char(command_uuid, cmd_text.encode("utf-8"), response=True)
        timing_tracer.record_write_done(room, ident)
    except Exception as exc:
        timing_tracer.record_write_done(room, ident, error=exc)
        # Retain the same ID across write errors and reconnect, until bounded expiry.
        raise


# ================================================================== #
#  Điều khiển thiết bị (web / cử chỉ / tự động)
# ================================================================== #
_DEVICE_LABELS = {
    ("patient", "light"): "đèn phòng bệnh",
    ("patient", "fan"): "quạt phòng bệnh",
    ("patient", "buzzer"): "buzzer phòng bệnh",
    ("living", "light"): "đèn phòng khách",
    ("living", "fan"): "quạt phòng khách",
    ("living", "auto"): "chế độ tự động phòng khách",
    ("kitchen", "window"): "cửa sổ bếp",
    ("kitchen", "exhaust"): "quạt hút bếp",
    ("kitchen", "light"): "đèn bếp",
    ("kitchen", "buzzer"): "còi báo động bếp",
}


def set_device(room, device, state=None, value=None, source="manual", user_id=None, silent=False):
    """Queue a validated command; only node telemetry confirms device state."""
    try:
        room, cmd = build_command(room, device, state, value)
    except ValueError as exc:
        _emit("command_error", {"room": room, "device": device, "message": str(exc)})
        return
    if source != "auto" and (_emergency_snapshot is not None or
                             room == "patient" and device == "buzzer" and
                             (AI.get("fall") or _fall_buzzer_saved is not None)):
        _emit("command_error", {"room": room, "device": device,
                                "message": "Điều khiển đang khóa do cảnh báo."})
        return

    # chống dội lệnh trùng
    key = (room, device)
    sig = (state, value)
    prev = _last_cmd.get(key)
    now = now_ts()
    if prev and prev[0] == sig and (now - prev[1]) < COMMAND_DEBOUNCE_SEC and source != "auto":
        return
    # Fan sliders can produce many values in quick succession. Keep only the
    # newest desired speed so stale pending writes cannot fill the BLE queue.
    if device in ("fan", "exhaust"):
        _cancel_commands(room, device)
    if not enqueue_command(room, json.dumps(cmd, ensure_ascii=False)):
        _emit("command_error", {"room": room, "device": device, "message": "Command queue full"})
        return False
    _last_cmd[key] = (sig, now)

    if not silent:
        label = _DEVICE_LABELS.get(key, f"{device} {room}")
        act = "Bật" if state else ("Tắt" if state is not None else "Chỉnh")
        detail = f" ({value}%)" if value is not None else ""
        suffix = " bằng cử chỉ" if source == "gesture" else ""
        log_audit(f"{act} {label}{detail}{suffix}", user_id=user_id)

    _emit("room_update", {"room": room, "data": dict(ROOMS[room])})


def queue_command(command, source="manual", gesture="manual_click", user_id=None):
    """Tương thích ngược: nhận mã lệnh cũ (L1/L0/S180/S0) từ web.control_device."""
    mapping = {
        "L1": ("patient", "light", True),
        "L0": ("patient", "light", False),
        "S180": ("kitchen", "window", True),
        "S0": ("kitchen", "window", False),
    }
    if command in mapping:
        room, device, state = mapping[command]
        set_device(room, device, state=state, source=source, user_id=user_id)


# ================================================================== #
#  UART servo tracking
# ================================================================== #
def init_uart():
    global uart
    if not UART_ENABLE:
        print("[UART] disabled by config")
        return
    if serial is None:
        print("[UART] pyserial chưa cài — bỏ qua UART")
        return
    try:
        uart = serial.Serial(UART_PORT, UART_BAUD, timeout=0.2)
        print(f"[UART] opened {UART_PORT} @ {UART_BAUD}")
    except Exception as exc:
        uart = None
        print(f"[UART] open failed ({UART_PORT}):", exc)


def uart_send_angle(angle):
    """Gửi góc servo (0..180) qua UART, giới hạn tần suất."""
    global _last_servo_send
    if AI_OBSERVE_ONLY:
        return
    now = now_ts()
    if now - _last_servo_send < SERVO_SEND_INTERVAL:
        return
    _last_servo_send = now

    line = "A{:03d}\n".format(int(round(angle)))
    if uart is not None:
        try:
            uart.write(line.encode("ascii"))
        except Exception as exc:
            print("[UART] write error:", exc)


def update_tracking(center_x, frame_w):
    """Điều khiển tỉ lệ (P) + vùng chết + làm mượt EMA -> góc servo."""
    err = center_x - frame_w / 2.0
    with state_lock:
        cur = AI["angle"]

    if abs(err) < SERVO_DEADZONE_PX:
        return cur

    step = SERVO_KP * err
    if SERVO_INVERT:
        step = -step

    target = cur + step
    target = max(SERVO_MIN, min(SERVO_MAX, target))
    smoothed = cur * (1 - SERVO_SMOOTHING) + target * SERVO_SMOOTHING
    smoothed = max(SERVO_MIN, min(SERVO_MAX, smoothed))

    with state_lock:
        AI["angle"] = round(smoothed, 1)
    return smoothed


# ================================================================== #
#  Cảnh báo (Telegram + state machine)
# ================================================================== #
def _should_alert(key):
    now = now_ts()
    if now - _last_alert_at.get(key, 0) >= ALERT_COOLDOWN_SEC:
        _last_alert_at[key] = now
        return True
    return False


def _push_alert(key, message, atype):
    if _should_alert(key):
        _emit("system_alert", {"type": atype, "message": message})


def build_alert_message(reason):
    with state_lock:
        p = dict(ROOMS["patient"])
        k = dict(ROOMS["kitchen"])
    return (
        "canh bao AIoT Care Station\n"
        f"- su kien: {reason}\n"
        f"- gas bep: {k.get('gas')}  khoi: {k.get('smoke')}  lua: {k.get('flame')}\n"
        f"- phong benh: nhiet do {p.get('temp')} do am {p.get('hum')} te nga {AI.get('fall')}\n"
        f"- thoi gian: {vn_now_sql()} (gmt+7)"
    )


def send_telegram_alert_async(reason):
    def worker():
        token = get_config_value("telegram_bot_token", "").strip()
        chat_id = get_config_value("telegram_chat_id", "").strip()
        if not token or not chat_id:
            print("[telegram] thiếu bot token / chat id")
            return
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{token}/sendMessage",
                json={"chat_id": chat_id, "text": build_alert_message(reason)},
                timeout=8,
            )
            print("[telegram] status:", resp.status_code)
        except Exception as exc:
            print("[telegram] send error:", exc)

    threading.Thread(target=worker, daemon=True).start()


def _danger_warn():
    """Trả về (danger, warn) dựa trên gas/khói/lửa (đã lọc trung bình trượt)."""
    with state_lock:
        k = dict(ROOMS["kitchen"])
    gas_k = _gas_avg("kitchen") or 0
    danger = bool(k["flame"] or k["smoke"] or gas_k >= GAS_HIGH_THRESHOLD
                  or (as_number(k.get("gas")) or 0) >= GAS_HIGH_THRESHOLD
                  or _kitchen_emergency)
    warn = bool(gas_k >= GAS_WARN_THRESHOLD)
    return danger, warn


def _set_alert(level, message=None):
    global alert_level
    if alert_level == level and message is None:
        return
    alert_level = level
    _emit("alert_state", {"level": level, "message": message})


def _fail_restoration(room):
    """Keep the snapshot/lock, but allow explicit confirmation to start again."""
    global _restoration_started
    if _restoration_started is None or room not in ("patient", "living"):
        return
    _restoration_started = None
    _restoration_seen.clear()
    for target in ("patient", "living"):
        _cancel_commands(target)
    _emit("command_error", {"room": room,
                            "message": "Khôi phục chưa được xác nhận; hãy xác nhận an toàn để thử lại."})


def _patient_buzzer_target():
    """Resolve active alerts, acknowledged recovery intent, then saved baseline."""
    if _alarm_silenced:
        return False
    if AI.get("fall"):
        return True
    if _emergency_snapshot is not None and _restoration_started is None:
        return True
    if _fall_restore_target is not None:
        return _fall_restore_target
    if _fall_buzzer_saved is not None:
        return True
    if _emergency_snapshot is not None:
        return bool(_emergency_snapshot["patient"]["buzzer"])
    return bool(ROOMS["patient"]["buzzer"])


def _resync_safety(room):
    """Rebuild current safety intent without repeating alerts or saving a new snapshot."""
    _fail_restoration(room)
    if _emergency_snapshot is not None and room in ("patient", "living"):
        _cancel_commands(room)
        if room == "living":
            set_device(room, "auto", state=False, source="auto", silent=True)
            set_device(room, "light", state=False, source="auto", silent=True)
        set_device(room, "fan", state=False, source="auto", silent=True)
        if room == "patient":
            set_device(room, "buzzer", state=_patient_buzzer_target(), source="auto", silent=True)
    elif room == "patient" and (AI.get("fall") or _fall_buzzer_saved is not None):
        _cancel_commands(room)
        set_device(room, "buzzer", state=_patient_buzzer_target(),
                   source="auto", silent=True)


def _reconcile_safety(room):
    """Safety intent outlives bounded delivery attempts, including lost telemetry."""
    if _restoration_started is not None:
        return
    desired = {}
    if _emergency_snapshot is not None:
        if room == "living":
            desired = {"auto": False, "light": False, "fan": False}
        elif room == "patient":
            desired = {"fan": False, "buzzer": _patient_buzzer_target()}
    elif room == "patient" and (AI.get("fall") or _fall_buzzer_saved is not None):
        desired = {"buzzer": _patient_buzzer_target()}
    now = time.monotonic()
    with _delivery_lock:
        queued = {json.loads(p["text"])["cmd"] for p in _pending_commands[room].values()}
        for device, state in desired.items():
            key = (room, device)
            if device in queued or now < _safety_retry_at.get(key, 0):
                continue
            _safety_retry_at[key] = now + SAFETY_RECHECK_SEC
            set_device(room, device, state=state, source="auto", silent=True)


def _observe_fall_restoration(room, payload):
    global _fall_buzzer_saved, _fall_restore_target
    if (room != "patient" or _fall_restore_target is None or AI.get("fall")
            or _emergency_snapshot is not None):
        return
    with _delivery_lock:
        if _pending_commands[room]:
            return
    if type(payload.get("buzzer")) is bool and payload["buzzer"] == _fall_restore_target:
        _fall_buzzer_saved = None
        _fall_restore_target = None
        _emit("alert_state", {"level": alert_level, "message": "Node đã xác nhận kết thúc cảnh báo té ngã."})


def _enter_emergency():
    """Kitchen owns local outputs; gateway quiets other rooms and saves state."""
    global _emergency_snapshot, _restoration_started, _alarm_silenced
    _alarm_silenced = False
    _restoration_started = None
    _restoration_seen.clear()
    for room in ("patient", "living"):
        _cancel_commands(room)
    if _emergency_snapshot is None:
        with state_lock:
            _emergency_snapshot = {room: dict(ROOMS[room]) for room in ("patient", "living")}
            if _fall_buzzer_saved is not None:
                _emergency_snapshot["patient"]["buzzer"] = _fall_buzzer_saved
    log_audit("Cảnh báo khẩn cấp: khói/lửa/gas cao", user_id=None)
    send_telegram_alert_async("khan cap chay/gas")
    set_device("living", "auto", state=False, source="auto", silent=True)
    set_device("living", "light", state=False, source="auto", silent=True)
    for room in ("patient", "living"):
        set_device(room, "fan", state=False, source="auto", silent=True)
    set_device("patient", "buzzer", state=True, source="auto", silent=True)
    # đảm bảo camera bật để quan sát người bệnh
    set_camera_mode("on", user_id=None)


def silence_alert(user_id=None):
    """Mute audible alarms while keeping hazard detection and safety actions active."""
    global _alarm_silenced
    _alarm_silenced = True
    if _emergency_snapshot is not None:
        set_device("patient", "buzzer", state=False, source="auto", silent=True)
    if _kitchen_emergency or alert_level == "light":
        set_device("kitchen", "buzzer", state=False, source="auto", silent=True)
    log_audit("Tắt tiếng còi cảnh báo (giám sát nguy hiểm vẫn hoạt động)", user_id=user_id)
    _emit("alert_state", {"level": alert_level,
                          "message": "Đã tắt tiếng còi; hệ thống vẫn tiếp tục giám sát nguy hiểm."})


def confirm_safe(user_id=None):
    """Người dùng xác nhận an toàn -> khôi phục thiết bị."""
    global alert_level, _emergency_snapshot, _restoration_started
    global _fall_restore_target
    if _emergency_snapshot is None and _fall_buzzer_saved is not None:
        if AI.get("fall"):
            return
        _fall_restore_target = _fall_buzzer_saved
        _cancel_commands("patient", "buzzer")
        set_device("patient", "buzzer", state=_patient_buzzer_target(), source="auto", silent=True)
        _emit("alert_state", {"level": alert_level, "message": "Đang chờ node xác nhận kết thúc cảnh báo té ngã."})
        return
    danger, warn = _danger_warn()
    now = time.monotonic()
    safe_confirmed = (_kitchen_safe_since is not None and _kitchen_sample_at is not None
                      and now - _kitchen_safe_since >= KITCHEN_SAFE_HOLD_SEC
                      and now - _kitchen_sample_at <= KITCHEN_SAMPLE_TIMEOUT_SEC)
    if danger or warn or not safe_confirmed:
        _emit("alert_state", {"level": alert_level,
                              "message": "Cần dữ liệu bếp bình thường liên tục ít nhất 10 giây và còn cập nhật."})
        return
    kitchen = ROOMS["kitchen"]
    if (not NODE_ONLINE["kitchen"] or kitchen.get("phase") != "wait_confirm"
            or type(kitchen.get("event_id")) is not int):
        _emit("alert_state", {"level": alert_level,
                              "message": "Node bếp chưa sẵn sàng; cần trạng thái WAIT_CONFIRM mới nhất."})
        return
    if _restoration_started is not None:
        if now - _restoration_started < COMMAND_TTL:
            return
        _fail_restoration("patient")
    # The gateway never replays a stale confirmation on reconnect.
    _cancel_commands("kitchen")
    if not enqueue_command("kitchen", json.dumps(
            {"cmd": "confirm_safe", "event_id": kitchen["event_id"]})):
        _emit("command_error", {"room": "kitchen", "message": "Không gửi được xác nhận."})
        return
    if _emergency_snapshot is not None:
        _restoration_started = now
        if not AI.get("fall") and _fall_buzzer_saved is not None:
            _fall_restore_target = _fall_buzzer_saved
        _restoration_seen.clear()
        for room in ("patient", "living"):
            _cancel_commands(room)
        for room, saved in _emergency_snapshot.items():
            if room == "living" and saved["auto"]:
                continue
            set_device(room, "fan", state=saved["fan"], value=int(saved["fan_speed"]),
                       source="auto", silent=True)
        saved = _emergency_snapshot["living"]
        if not saved["auto"]:
            set_device("living", "light", state=saved["light"], source="auto", silent=True)
        set_device("living", "auto", state=saved["auto"], source="auto", silent=True)
        set_device("patient", "buzzer",
                   state=_patient_buzzer_target(),
                   source="auto", silent=True)
        _emit("alert_state", {"level": alert_level,
                              "message": "Đang chờ node xác nhận khôi phục."})
        return
    log_audit("Xác nhận an toàn, khôi phục thiết bị", user_id=user_id)
    alert_level = "normal"
    _emit("alert_state", {"level": "normal", "message": "Đã khôi phục về trạng thái bình thường."})
    evaluate_alerts()   # nếu vẫn còn nguy hiểm sẽ tự quay lại emergency


def _observe_restoration(room, payload):
    """Require a complete actuator report, never a sensor-only timestamp."""
    global _emergency_snapshot, _restoration_started
    if _restoration_started is None or _emergency_snapshot is None:
        return
    danger, warn = _danger_warn()
    now = time.monotonic()
    for target, observed in list(_restoration_seen.items()):
        if not NODE_ONLINE.get(target) or now - observed > KITCHEN_SAMPLE_TIMEOUT_SEC:
            _restoration_seen.pop(target, None)
    if (danger or warn or _kitchen_safe_since is None or
            now - _kitchen_safe_since < KITCHEN_SAFE_HOLD_SEC or _kitchen_sample_at is None or
            now - _kitchen_sample_at > KITCHEN_SAMPLE_TIMEOUT_SEC):
        _restoration_seen.clear()
        return
    if room not in _emergency_snapshot or not NODE_ONLINE.get(room):
        return
    with _delivery_lock:
        if _pending_commands[room]:
            return
    saved = _emergency_snapshot[room]
    expected = {"fan": saved["fan"],
                "fan_speed": int(saved["fan_speed"]) if saved["fan"] else 0}
    if room == "living":
        expected.update(light=saved["light"], auto=saved["auto"])
        if saved["auto"]:
            expected = {"auto": True}
    else:
        expected["buzzer"] = _patient_buzzer_target()
    matches = all(type(payload.get(key)) is type(value) and payload[key] == value
                  for key, value in expected.items())
    if matches:
        _restoration_seen[room] = now
    else:
        _restoration_seen.pop(room, None)
    # Do not report global restoration until the kitchen node itself
    # confirms that the local safety latch has left WAIT_CONFIRM.
    with _delivery_lock:
        kitchen_command_pending = bool(_pending_commands["kitchen"])
    kitchen_recovered = (NODE_ONLINE["kitchen"] and
                         ROOMS["kitchen"].get("phase") == "normal" and
                         not kitchen_command_pending)
    if set(_restoration_seen) == {"patient", "living"} and kitchen_recovered:
        _emergency_snapshot = None
        _restoration_started = None
        _restoration_seen.clear()
        log_audit("Khôi phục đã được các node xác nhận", user_id=None)
        _set_alert("normal", "Đã khôi phục về trạng thái bình thường.")


def evaluate_alerts():
    """Máy trạng thái: normal -> light -> emergency -> awaiting (chờ xác nhận)."""
    global alert_level
    danger, warn = _danger_warn()

    if danger:
        if alert_level != "emergency":
            _enter_emergency()
        _set_alert("emergency", "Phát hiện khói/lửa hoặc khí gas rất cao!")
    else:
        if alert_level == "emergency":
            _set_alert("awaiting", "Điều kiện đã an toàn — cần xác nhận để khôi phục.")
        elif alert_level == "awaiting":
            pass  # giữ nguyên tới khi người dùng xác nhận
        elif warn:
            if alert_level != "light":
                log_audit("Cảnh báo gas tăng cao", user_id=None)
                send_telegram_alert_async("gas tang nhe")
            _set_alert("light", "Khí gas tăng cao hơn mức bình thường.")
        else:
            _set_alert("normal")


# ================================================================== #
#  Camera + AI
# ================================================================== #
def is_camera_active():
    return camera_active


def get_latest_frame():
    with camera_lock:
        return latest_frame


def _start_worker_thread(target, args=()):
    if socketio is not None and hasattr(socketio, "start_background_task"):
        try:
            return socketio.start_background_task(target, *args)
        except Exception:
            pass
    t = threading.Thread(target=target, args=args, daemon=True)
    t.start()
    return t


def _start_camera(user_id=None):
    global camera_active, camera_owner_user_id, camera_thread
    global _camera_session_id, _pub_thread, _ai_thread
    with _camera_session_lock:
        if camera_active:
            return
        camera_active = True
        camera_owner_user_id = user_id
        _camera_session_id += 1
        current_session = _camera_session_id

        # Start decoupled publication and AI workers
        _pub_thread = _start_worker_thread(_camera_pub_worker, (current_session,))
        _ai_thread = _start_worker_thread(_camera_ai_worker, (current_session,))
        camera_thread = _pub_thread


def _stop_camera():
    global camera_active, camera_owner_user_id
    pub_t = None
    ai_t = None
    with _camera_session_lock:
        if not camera_active:
            return
        camera_active = False
        camera_owner_user_id = None
        pub_t = _pub_thread
        ai_t = _ai_thread

    # Unblock AI worker immediately if waiting for frames
    with _new_raw_frame_cond:
        _new_raw_frame_cond.notify_all()

    # Join threads with finite timeout to avoid deadlocks
    curr_t = threading.current_thread()
    if pub_t is not None and hasattr(pub_t, "join") and pub_t is not curr_t:
        pub_t.join(timeout=1.5)
    if ai_t is not None and hasattr(ai_t, "join") and ai_t is not curr_t:
        ai_t.join(timeout=1.5)

    with state_lock:
        AI.update({
            "gesture": "Camera Offline",
            "fps": "--",
            "video_fps": "--",
            "latency": "--",
            "work_ms": 0,
            "camera": False,
        })
    with _ai_results_lock:
        _latest_ai_results["pose_landmarks"] = None
        _latest_ai_results["multi_hand_landmarks"] = None
        _latest_ai_results["gesture"] = "—"
        _latest_ai_results["ts"] = 0.0

    _emit("camera_sync", {"active": False, "mode": camera_mode})
    _emit("ai_status", dict(AI))


def _maybe_auto_camera_on():
    if camera_mode == "auto":
        _start_camera(None)


def set_camera_mode(mode, user_id=None):
    """mode: auto | on | off."""
    global camera_mode
    mode = mode if mode in ("auto", "on", "off") else "auto"
    camera_mode = mode

    if mode == "on":
        _start_camera(user_id)
    elif mode == "off":
        _stop_camera()
    else:  # auto
        if now_ts() - last_motion_ts > CAMERA_MOTION_TIMEOUT:
            _stop_camera()

    _emit("camera_sync", {"active": camera_active, "mode": camera_mode})
    return {"active": camera_active, "mode": camera_mode}


def set_camera_state(desired, user_id=None):
    """Tương thích ngược: toggle bật/tắt (ép mode on/off)."""
    return set_camera_mode("on" if desired else "off", user_id=user_id)["active"]


def set_tracking(enabled, user_id=None):
    global tracking_enabled
    tracking_enabled = bool(enabled)
    if not tracking_enabled:
        uart_send_angle(SERVO_CENTER)
        with state_lock:
            AI["angle"] = SERVO_CENTER
    log_audit(f"{'Bật' if enabled else 'Tắt'} tracking servo", user_id=user_id)
    _emit("camera_sync", {"active": camera_active, "mode": camera_mode, "tracking": tracking_enabled})
    return tracking_enabled


def emit_full_state():
    """Gửi snapshot đầy đủ cho client (gọi trong context handler socket)."""
    emit("bootstrap", snapshot_all())


# ---- Cử chỉ (Yêu cầu 2: ánh xạ động, hỗ trợ 2 tay) ----
GESTURE_LABELS = {
    "fist": "Nắm tay",
    "one": "1 ngón (chỉ)",
    "two": "2 ngón (chữ V)",
    "three": "3 ngón",
    "four": "4 ngón",
    "open": "Bàn tay mở (5 ngón)",
    "thumbs_up": "Ngón cái (like)",
    "two_hands_open": "Hai bàn tay mở",
}
GESTURE_DEVICES = [("light", "Đèn"), ("fan", "Quạt"), ("buzzer", "Buzzer")]
GESTURE_ACTIONS = [("on", "Bật"), ("off", "Tắt"), ("toggle", "Đảo trạng thái")]

# Cache ánh xạ cử chỉ nạp từ DB: gesture_key -> (device, action)
_gesture_map = {}


def load_gesture_map():
    """Nạp ánh xạ cử chỉ từ database vào cache trong bộ nhớ."""
    global _gesture_map
    try:
        rows = fetch_gesture_mappings()
        _gesture_map = {r["gesture_name"]: (r["target_device"], r["action"]) for r in rows}
        print(f"[iot] loaded {len(_gesture_map)} gesture mappings")
    except Exception as exc:
        print("[iot] load gesture map error:", exc)


def reload_gesture_map():
    load_gesture_map()
    return _gesture_map


def available_gesture_options():
    """Danh mục cử chỉ/thiết bị/hành động cho giao diện tùy chỉnh."""
    return {
        "gestures": [{"key": k, "label": v} for k, v in GESTURE_LABELS.items()],
        "devices": [{"key": k, "label": v} for k, v in GESTURE_DEVICES],
        "actions": [{"key": k, "label": v} for k, v in GESTURE_ACTIONS],
    }


def _finger_states(hand_landmarks, frame_w, frame_h):
    """Trả về [thumb,index,middle,ring,pinky]; 1=duỗi, 0=co."""
    lm = [(int(p.x * frame_w), int(p.y * frame_h)) for p in hand_landmarks.landmark]
    tips = [4, 8, 12, 16, 20]
    st = [1 if abs(lm[4][0] - lm[17][0]) > abs(lm[3][0] - lm[17][0]) else 0]  # ngón cái theo x
    for i in range(1, 5):
        st.append(1 if lm[tips[i]][1] < lm[tips[i] - 2][1] else 0)             # 4 ngón theo y
    return st


def detect_gesture(hands_list, frame_w, frame_h):
    """Nhận 1-2 bàn tay -> gesture key (canonical) hoặc None."""
    if not hands_list:
        return None
    all_states = [_finger_states(h, frame_w, frame_h) for h in hands_list]
    counts = [sum(s) for s in all_states]

    if len(hands_list) >= 2 and all(c >= 4 for c in counts[:2]):
        return "two_hands_open"

    idx = counts.index(max(counts))            # dùng tay nhiều ngón nhất
    thumb, index, middle, ring, pinky = all_states[idx]
    total = counts[idx]

    if total == 0:
        return "fist"
    if total == 5:
        return "open"
    if total == 1 and thumb == 1:
        return "thumbs_up"
    if total == 1 and index == 1:
        return "one"
    if total == 2 and index == 1 and middle == 1:
        return "two"
    if total == 3:
        return "three"
    if total == 4:
        return "four"
    return None


def _apply_gesture(gesture_key):
    """Tra cứu ánh xạ trong DB (cache) rồi điều khiển thiết bị. Có cooldown.

    Với quạt, luôn gửi kèm PWM để firmware nhận đủ tốc độ:
      - on / toggle -> bật: value=70
      - off / toggle -> tắt: value=0
    """
    if AI_OBSERVE_ONLY:
        return
    mapping = _gesture_map.get(gesture_key)
    if not mapping:
        return

    device, action = mapping
    now = now_ts()
    if _last_gesture_action["key"] == gesture_key and (now - _last_gesture_action["ts"]) < GESTURE_COOLDOWN_SEC:
        return
    _last_gesture_action["key"] = gesture_key
    _last_gesture_action["ts"] = now

    if action == "toggle":
        with state_lock:
            if device == "fan":
                cur = bool(ROOMS["patient"].get("fan")) or int(ROOMS["patient"].get("fan_speed") or 0) > 0
            else:
                cur = bool(ROOMS["patient"].get(device))
        state = not cur
    elif action == "on":
        state = True
    elif action == "off":
        state = False
    else:
        return

    value = None
    if device == "fan":
        value = 70 if state else 0

    set_device(
        "patient",
        device,
        state=state,
        value=value,
        source="gesture",
        user_id=camera_owner_user_id,
    )


# ---- Té ngã ----
_fall_since = 0.0


def detect_fall(landmarks, w, h):
    """Heuristic: góc thân so phương đứng + tỉ lệ bbox. Trả về True/False (nghi ngờ)."""
    try:
        ls, rs = landmarks[11], landmarks[12]    # shoulders
        lh, rh = landmarks[23], landmarks[24]    # hips
        sx = (ls.x + rs.x) / 2 * w
        sy = (ls.y + rs.y) / 2 * h
        hx = (lh.x + rh.x) / 2 * w
        hy = (lh.y + rh.y) / 2 * h

        import math
        dx, dy = hx - sx, hy - sy
        # góc so với phương thẳng đứng (0 = đứng thẳng)
        angle = abs(math.degrees(math.atan2(abs(dx), abs(dy) + 1e-6)))

        xs = [p.x for p in landmarks]
        ys = [p.y for p in landmarks]
        bw = (max(xs) - min(xs)) * w
        bh = (max(ys) - min(ys)) * h
        aspect = bw / (bh + 1e-6)

        return angle > FALL_TORSO_DEG or aspect > FALL_ASPECT
    except Exception:
        return False


def _handle_fall(is_suspect):
    global _fall_since
    global _fall_buzzer_saved, _fall_restore_target
    now = now_ts()
    if AI_OBSERVE_ONLY:
        # Display-only suspicion must NEVER enter the actionable fall flag:
        # safety reconciliation and reconnect consume AI["fall"].
        if is_suspect:
            if _fall_since == 0.0:
                _fall_since = now
            suspected = now - _fall_since >= FALL_HOLD_SEC
        else:
            _fall_since = 0.0
            suspected = False
        with state_lock:
            changed = AI["fall_suspected"] != suspected
            AI["fall_suspected"] = suspected
        if changed:
            _emit("ai_status", dict(AI))
        return
    if is_suspect:
        if _fall_since == 0.0:
            _fall_since = now
        elif (now - _fall_since) >= FALL_HOLD_SEC and not AI["fall"]:
            if _fall_buzzer_saved is None:
                _fall_buzzer_saved = bool((_emergency_snapshot or ROOMS)["patient"]["buzzer"])
            _fall_restore_target = None
            _cancel_commands("patient", "buzzer")
            _restoration_seen.pop("patient", None)
            with state_lock:
                AI["fall"] = True
            log_audit("Phát hiện té ngã ở phòng người bệnh", user_id=None)
            send_telegram_alert_async("te nga phong benh")
            set_device("patient", "buzzer", state=True, source="auto", silent=True)
            _push_alert("fall", "Phát hiện té ngã ở phòng người bệnh!", "fall")
            _emit("ai_status", dict(AI))
    else:
        _fall_since = 0.0
        if AI["fall"]:
            with state_lock:
                AI["fall"] = False
            _emit("ai_status", dict(AI))


def _camera_pub_worker(session_id):
    global latest_frame, camera_active

    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        with _camera_session_lock:
            if session_id == _camera_session_id:
                camera_active = False
        with state_lock:
            AI.update({
                "gesture": "Camera Offline",
                "fps": "--",
                "video_fps": "--",
                "latency": "--",
                "work_ms": 0,
                "camera": False,
            })
        _emit("camera_sync", {"active": False, "mode": camera_mode})
        _push_alert("camera", "Không mở được camera.", "camera")
        cap.release()
        with _new_raw_frame_cond:
            _new_raw_frame_cond.notify_all()
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    _emit("camera_sync", {"active": True, "mode": camera_mode})

    pub_fps_times = deque(maxlen=20)
    draw = None
    if mp is not None and hasattr(mp, "solutions") and hasattr(mp.solutions, "drawing_utils"):
        draw = mp.solutions.drawing_utils

    try:
        while camera_active and session_id == _camera_session_id:
            ok, img = cap.read()
            if not ok or img is None:
                time.sleep(0.01)
                continue

            try:
                flipped = cv2.flip(img, 1)
                if isinstance(flipped, np.ndarray):
                    img = flipped
            except Exception:
                pass

            if hasattr(img, "shape") and isinstance(img.shape, (tuple, list)) and len(img.shape) >= 2:
                h, w = int(img.shape[0]), int(img.shape[1])
            else:
                h, w = CAMERA_HEIGHT, CAMERA_WIDTH

            # Hand off raw frame to AI worker without blocking publication
            with _new_raw_frame_cond:
                _latest_raw_slot["frame"] = img.copy() if hasattr(img, "copy") else img
                _latest_raw_slot["gen"] += 1
                _latest_raw_slot["ts"] = time.perf_counter()
                _latest_raw_slot["w"] = w
                _latest_raw_slot["h"] = h
                _new_raw_frame_cond.notify()

            # Read latest AI results under lock
            now = time.perf_counter()
            with _ai_results_lock:
                pose_lms = _latest_ai_results.get("pose_landmarks")
                hands_lms = _latest_ai_results.get("multi_hand_landmarks")
                gesture_res = _latest_ai_results.get("gesture", "—")
                res_ts = _latest_ai_results.get("ts", 0.0)

            # Draw overlay if fresh
            max_age = globals().get("OVERLAY_MAX_AGE_SEC", 0.8)
            if (now - res_ts) <= max_age:
                if draw is not None:
                    if pose_lms is not None and mp is not None and hasattr(mp.solutions, "pose"):
                        draw.draw_landmarks(img, pose_lms, mp.solutions.pose.POSE_CONNECTIONS)
                    if hands_lms is not None and mp is not None and hasattr(mp.solutions, "hands"):
                        for hl in hands_lms:
                            draw.draw_landmarks(img, hl, mp.solutions.hands.HAND_CONNECTIONS)
                if gesture_res and gesture_res != "—":
                    cv2.putText(img, gesture_res, (12, 50),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 255, 180), 2)

            with state_lock:
                angle_now = AI["angle"]
            cv2.putText(img, f"Goc: {int(angle_now)}", (12, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 200, 255), 2)

            # Measure publication FPS
            t_pub = time.perf_counter()
            pub_fps_times.append(t_pub)
            v_fps = "--"
            if len(pub_fps_times) >= 2:
                dur = pub_fps_times[-1] - pub_fps_times[0]
                if dur > 0:
                    v_fps = f"{(len(pub_fps_times) - 1) / dur:.1f}"
            with state_lock:
                AI["video_fps"] = v_fps

            ret, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ret:
                with camera_lock:
                    latest_frame = buffer.tobytes()

            # Auto shutdown on motion timeout
            if camera_mode == "auto" and (now_ts() - last_motion_ts) > CAMERA_MOTION_TIMEOUT:
                with _camera_session_lock:
                    if session_id == _camera_session_id:
                        camera_active = False
                break

            time.sleep(STREAM_SLEEP)
    except Exception as exc:
        print("[camera pub] error:", exc)
        _push_alert("camera", f"Lỗi camera: {exc}", "camera")
    finally:
        cap.release()
        with _camera_session_lock:
            if session_id == _camera_session_id:
                camera_active = False
        with _new_raw_frame_cond:
            _new_raw_frame_cond.notify_all()
        with state_lock:
            AI.update({
                "gesture": "Camera Offline",
                "fps": "--",
                "video_fps": "--",
                "latency": "--",
                "work_ms": 0,
                "camera": False,
            })
        with _ai_results_lock:
            _latest_ai_results["pose_landmarks"] = None
            _latest_ai_results["multi_hand_landmarks"] = None
            _latest_ai_results["gesture"] = "—"
            _latest_ai_results["ts"] = 0.0
        _emit("camera_sync", {"active": False, "mode": camera_mode})
        _emit("ai_status", dict(AI))


def _camera_ai_worker(session_id):
    pose = None
    hands = None
    if mp is not None and hasattr(mp, "solutions"):
        if ENABLE_TRACKING or ENABLE_FALL:
            pose = mp.solutions.pose.Pose(
                model_complexity=0,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
        if ENABLE_GESTURE:
            hands = mp.solutions.hands.Hands(
                max_num_hands=2,
                model_complexity=0,
                min_detection_confidence=0.65,
                min_tracking_confidence=0.55,
            )

    last_inferred_gen = 0
    ai_fps_times = deque(maxlen=20)
    last_emit = 0.0

    try:
        while camera_active and session_id == _camera_session_id:
            with _new_raw_frame_cond:
                while camera_active and session_id == _camera_session_id and _latest_raw_slot["gen"] <= last_inferred_gen:
                    _new_raw_frame_cond.wait(timeout=0.1)
                if not camera_active or session_id != _camera_session_id:
                    break
                raw_frame = _latest_raw_slot["frame"]
                last_inferred_gen = _latest_raw_slot["gen"]
                w = _latest_raw_slot.get("w", CAMERA_WIDTH)
                h = _latest_raw_slot.get("h", CAMERA_HEIGHT)

            if raw_frame is None:
                continue

            t0 = time.perf_counter()
            try:
                rgb = cv2.cvtColor(raw_frame, cv2.COLOR_BGR2RGB)
                if not isinstance(rgb, np.ndarray):
                    rgb = raw_frame
            except Exception:
                rgb = raw_frame
            gesture = "—"
            pose_lms = None
            hands_lms = None

            # ----- Pose: tracking + té ngã -----
            if pose is not None:
                pres = pose.process(rgb)
                if pres and pres.pose_landmarks:
                    pose_lms = pres.pose_landmarks
                    lms = pres.pose_landmarks.landmark
                    cx = lms[0].x * w
                    if tracking_enabled:
                        angle = update_tracking(cx, w)
                        uart_send_angle(angle)
                    if ENABLE_FALL:
                        _handle_fall(detect_fall(lms, w, h))

            # ----- Hands: cử chỉ -----
            if hands is not None and last_inferred_gen % PROCESS_EVERY_N_FRAMES == 0:
                hres = hands.process(rgb)
                if hres and hres.multi_hand_landmarks:
                    hands_lms = hres.multi_hand_landmarks
                    gkey = detect_gesture(hands_lms, w, h)
                    if gkey:
                        gesture = GESTURE_LABELS.get(gkey, gkey)
                        _apply_gesture(gkey)

            t_work = time.perf_counter()
            work_ms = int((t_work - t0) * 1000)
            ai_fps_times.append(t_work)
            fps = "--"
            if len(ai_fps_times) >= 2:
                dur = ai_fps_times[-1] - ai_fps_times[0]
                if dur > 0:
                    fps = f"{(len(ai_fps_times) - 1) / dur:.1f}"

            with _ai_results_lock:
                _latest_ai_results["pose_landmarks"] = pose_lms
                _latest_ai_results["multi_hand_landmarks"] = hands_lms
                _latest_ai_results["gesture"] = gesture
                _latest_ai_results["ts"] = t_work

            with state_lock:
                AI.update({
                    "gesture": gesture,
                    "fps": fps,
                    "latency": work_ms,
                    "work_ms": work_ms,
                    "camera": True,
                })

            if socketio is not None and (time.time() - last_emit) >= STATUS_EMIT_INTERVAL:
                _emit("ai_status", dict(AI))
                last_emit = time.time()
    except Exception as exc:
        print("[camera ai] error:", exc)
    finally:
        if pose is not None:
            try:
                pose.close()
            except Exception:
                pass
        if hands is not None:
            try:
                hands.close()
            except Exception:
                pass


def process_camera_stream():
    """Backward-compatible entry point that launches the decoupled camera workers and waits."""
    _start_camera()
    while camera_active:
        time.sleep(0.05)


# ================================================================== #
#  Khởi động dịch vụ nền
# ================================================================== #
def start_background_services():
    global services_started
    if services_started:
        return
    services_started = True

    load_gesture_map()
    init_uart()
    threading.Thread(target=_ble_thread, daemon=True).start()
    if camera_mode == "on":
        _start_camera()
    print(f"[iot] background services started (BLE x{len(NODES)}; UART configured={bool(UART_ENABLE)})")
