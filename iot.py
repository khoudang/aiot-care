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
import threading
import time
from node_protocol import build_command
from collections import deque

import cv2
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
        "window": False, "exhaust": False, "light": False, "buzzer": False,
        "updated_at": 0,
    },
}

NODE_ONLINE = {"patient": False, "living": False, "kitchen": False}

AI = {
    "gesture": "—", "fps": "--", "latency": "--",
    "angle": SERVO_CENTER, "fall": False, "camera": False,
}

# Camera / tracking
camera_active = False
camera_mode = CAMERA_MODE_DEFAULT          # auto | on | off
tracking_enabled = ENABLE_TRACKING
last_motion_ts = 0.0
camera_thread = None
latest_frame = None
camera_owner_user_id = None

# Cảnh báo
alert_level = "normal"                     # normal | light | emergency | awaiting
_emergency_snapshot = None
_restoration_started = None
_restoration_seen = {}
_kitchen_safe_since = None
_kitchen_sample_at = None
_kitchen_emergency = False
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
ble_loop = None
BLE_MAC_CONFIG_KEYS = {room: f"ble_mac_{room}" for room in ROOMS}
_ble_reconfigure = {room: threading.Event() for room in ROOMS}

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


def snapshot_all():
    with state_lock:
        rooms = {r: dict(v) for r, v in ROOMS.items()}
        ai = dict(AI)
        nodes = dict(NODE_ONLINE)
        cam = {"active": camera_active, "mode": camera_mode, "tracking": tracking_enabled}
        alert = {"level": alert_level}
    return {"rooms": rooms, "nodes": nodes, "ai": ai, "camera": cam,
            "alert": alert, "histories": snapshot_histories()}


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
}
_BOOL_KEYS = ["motion", "light", "fan", "buzzer", "smoke", "flame", "window", "exhaust", "auto"]


def apply_node_payload(room, payload):
    """Nhận dict telemetry từ 1 node, cập nhật state phòng tương ứng."""
    global last_motion_ts
    global _kitchen_safe_since, _kitchen_sample_at, _kitchen_emergency

    if room not in ROOMS:
        return

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
def set_node_online(room, online):
    if room not in ROOMS:
        return
    _restoration_seen.pop(room, None)
    changed = NODE_ONLINE.get(room) != online
    NODE_ONLINE[room] = online
    if changed:
        _emit("node_status", dict(NODE_ONLINE))
        if not online:
            log_audit(f"Node {room} mất kết nối (BLE offline)", user_id=None)
            _push_alert("node_" + room,
                        f"Node {room_name(room)} mất kết nối.", "node")


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
                            if payload["status"] == "rejected":
                                _fail_restoration(room)
                                _emit("command_error", {"room": room, "message": "Node rejected command"})
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
             "online": bool(NODE_ONLINE[node["room"]])} for node in NODES]


async def _scan_ble_devices():
    devices = await BleakScanner.discover(timeout=5.0)
    return sorted([{"name": device.name or "Thiết bị BLE", "mac": device.address.upper()}
                   for device in devices], key=lambda device: (device["name"], device["mac"]))


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
    _ble_reconfigure[room].set()
    _cancel_commands(room)
    for key in list(_last_cmd):
        if key[0] == room:
            _last_cmd.pop(key, None)


async def _node_loop(node):
    room = node["room"]
    notify_uuid = node["notify_uuid"]
    command_uuid = node["command_uuid"]

    if BleakClient is None:
        print("[BLE] bleak chưa được cài — bỏ qua node", room)
        return

    while True:
        try:
            _ble_reconfigure[room].clear()
            mac = _configured_mac(node)
            if not mac or not mac.strip():
                print("[BLE] MAC not configured; waiting for node", room)
                continue
            print(f"[BLE {room}] connecting to {mac} ...")
            async with BleakClient(mac) as client:
                if _ble_reconfigure[room].is_set() or _configured_mac(node).upper() != mac.upper():
                    continue
                ble_clients[room] = client
                set_node_online(room, True)
                print(f"[BLE {room}] connected")

                await client.start_notify(notify_uuid, _make_notify_handler(room))
                _resync_safety(room)

                # vòng lặp gửi lệnh (drain queue) + giữ kết nối
                while client.is_connected and not _ble_reconfigure[room].is_set():
                    await _send_pending(room, client, command_uuid)
                    await asyncio.sleep(0.05)

        except Exception as exc:
            print(f"[BLE {room}] disconnected / reconnect:", exc)
        finally:
            ble_clients[room] = None
            set_node_online(room, False)
            await asyncio.sleep(BLE_RECONNECT_DELAY)


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
        _pending_commands[room][_command_sequence] = {
            "text": text, "created": time.monotonic(), "sent": None, "attempts": 0}
        return True


def _cancel_commands(room, device=None):
    """A new safety phase invalidates queued and retrying older commands."""
    with _delivery_lock:
        for ident, pending in list(_pending_commands[room].items()):
            if device is None or json.loads(pending["text"])["cmd"] == device:
                del _pending_commands[room][ident]
        retained = []
        while True:
            try:
                text = command_queues[room].get_nowait()
                if device is not None and json.loads(text)["cmd"] != device:
                    retained.append(text)
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
        due = pending["sent"] is None or now - pending["sent"] >= COMMAND_ACK_TIMEOUT
        if now - pending["created"] >= COMMAND_TTL or (due and pending["attempts"] >= COMMAND_ATTEMPTS):
            del _pending_commands[room][ident]
            _fail_restoration(room)
            _emit("command_error", {"room": room, "message": "Command acknowledgement timeout"})
            return
        if not due:
            return
        pending["sent"] = now
        pending["attempts"] += 1
    try:
        await client.write_gatt_char(command_uuid, pending["text"].encode("utf-8"), response=True)
    except Exception:
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
            set_device(room, "buzzer", state=True, source="auto", silent=True)
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
            desired = {"fan": False, "buzzer": True}
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
    global _emergency_snapshot, _restoration_started
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
    if _emergency_snapshot is not None:
        if _restoration_started is not None:
            if now - _restoration_started < COMMAND_TTL:
                return
            _fail_restoration("patient")
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
    if set(_restoration_seen) == {"patient", "living"}:
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


def _start_camera(user_id=None):
    global camera_active, camera_thread, camera_owner_user_id
    if socketio is None or camera_active:
        return
    camera_active = True
    camera_owner_user_id = user_id
    camera_thread = socketio.start_background_task(process_camera_stream)


def _stop_camera():
    global camera_active, camera_owner_user_id
    camera_active = False
    camera_owner_user_id = None


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


def process_camera_stream():
    global latest_frame, camera_active

    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        camera_active = False
        with state_lock:
            AI.update({"gesture": "Camera Offline", "fps": "--", "latency": "--", "camera": False})
        _emit("camera_sync", {"active": False, "mode": camera_mode})
        _push_alert("camera", "Không mở được camera.", "camera")
        cap.release()
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAMERA_HEIGHT)
    try:
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:
        pass

    pose = None
    hands = None
    draw = None
    if mp is not None:
        draw = mp.solutions.drawing_utils
        if ENABLE_TRACKING or ENABLE_FALL:
            pose = mp.solutions.pose.Pose(model_complexity=0,
                                          min_detection_confidence=0.5,
                                          min_tracking_confidence=0.5)
        if ENABLE_GESTURE:
            hands = mp.solutions.hands.Hands(max_num_hands=2, model_complexity=0,
                                             min_detection_confidence=0.65,
                                             min_tracking_confidence=0.55)

    _emit("camera_sync", {"active": True, "mode": camera_mode})

    frame_count = 0
    fps_times = deque(maxlen=20)
    last_emit = 0.0

    try:
        while camera_active:
            t0 = time.perf_counter()
            ok, img = cap.read()
            if not ok:
                time.sleep(0.01)
                continue

            frame_count += 1
            img = cv2.flip(img, 1)
            h, w = img.shape[:2]
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            gesture = "—"

            # ----- Pose: tracking + té ngã -----
            if pose is not None:
                pres = pose.process(rgb)
                if pres.pose_landmarks:
                    lms = pres.pose_landmarks.landmark
                    cx = lms[0].x * w        # mũi làm tâm bám
                    if tracking_enabled:
                        angle = update_tracking(cx, w)
                        uart_send_angle(angle)
                    if ENABLE_FALL:
                        _handle_fall(detect_fall(lms, w, h))
                    if draw is not None:
                        draw.draw_landmarks(img, pres.pose_landmarks,
                                            mp.solutions.pose.POSE_CONNECTIONS)

            # ----- Hands: cử chỉ (giãn cách frame, hỗ trợ 2 tay) -----
            if hands is not None and frame_count % PROCESS_EVERY_N_FRAMES == 0:
                hres = hands.process(rgb)
                if hres.multi_hand_landmarks:
                    hands_list = hres.multi_hand_landmarks
                    if draw is not None:
                        for hl in hands_list:
                            draw.draw_landmarks(img, hl, mp.solutions.hands.HAND_CONNECTIONS)
                    gkey = detect_gesture(hands_list, w, h)
                    if gkey:
                        gesture = GESTURE_LABELS.get(gkey, gkey)
                        _apply_gesture(gkey)

            # ----- FPS / latency -----
            fps_times.append(time.perf_counter())
            fps = "--"
            if len(fps_times) >= 2:
                dur = fps_times[-1] - fps_times[0]
                if dur > 0:
                    fps = f"{(len(fps_times) - 1) / dur:.1f}"
            latency = int((time.perf_counter() - t0) * 1000)

            with state_lock:
                AI.update({"gesture": gesture, "fps": fps, "latency": latency, "camera": True})
                angle_now = AI["angle"]

            # overlay gọn (chuyên nghiệp)
            cv2.putText(img, f"Goc: {int(angle_now)}", (12, 24),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 200, 255), 2)
            if gesture != "—":
                cv2.putText(img, gesture, (12, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (80, 255, 180), 2)

            if socketio is not None and (time.time() - last_emit) >= STATUS_EMIT_INTERVAL:
                _emit("ai_status", dict(AI))
                last_emit = time.time()

            ret, buffer = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
            if ret:
                with camera_lock:
                    latest_frame = buffer.tobytes()

            # tự tắt khi hết chuyển động (chế độ auto)
            if camera_mode == "auto" and (now_ts() - last_motion_ts) > CAMERA_MOTION_TIMEOUT:
                camera_active = False

            time.sleep(STREAM_SLEEP)

    except Exception as exc:
        print("[camera] error:", exc)
        _push_alert("camera", f"Lỗi camera: {exc}", "camera")
    finally:
        cap.release()
        if pose is not None:
            pose.close()
        if hands is not None:
            hands.close()
        with state_lock:
            AI.update({"gesture": "Camera Offline", "fps": "--", "latency": "--", "camera": False})
        _emit("camera_sync", {"active": False, "mode": camera_mode})
        _emit("ai_status", dict(AI))


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
    print("[iot] background services started (BLE x4 + UART)")
