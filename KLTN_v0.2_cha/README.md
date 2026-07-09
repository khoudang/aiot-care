# AIoT Care Station — BLE P2P + BLE Mesh Backend

Backend này đã được thiết kế lại theo mô hình kết hợp **BLE P2P** và **BLE Mesh**:

- **BLE P2P:** Raspberry Pi chỉ kết nối trực tiếp với **ESP chính** ở phòng người bệnh.
- **BLE Mesh:** ESP chính giao tiếp nội bộ với các node trong mesh: `patient`, `living`, `kitchen`, `wearable`.
- **Web / Socket.IO:** Pi giải mã dữ liệu từ ESP chính, cập nhật state từng phòng đúng thứ tự và đẩy realtime lên dashboard.
- **UART:** Pi vẫn gửi góc servo tracking camera bằng UART riêng, không đi qua BLE Mesh.

Mục tiêu của thiết kế mới là giảm số kết nối BLE trực tiếp trên Raspberry Pi, gom dữ liệu mesh thành một gói chuẩn, và để ESP chính chịu trách nhiệm định tuyến lệnh xuống đúng node.

---

## 1. Kiến trúc tổng thể

```text
Web Dashboard
  │
  │ Socket.IO / REST
  ▼
Raspberry Pi 4 Backend
  ├─ Camera AI: gesture / tracking / fall detection
  ├─ UART → ESP servo pan
  └─ BLE P2P ⇄ ESP chính / Node phòng bệnh
                    │
                    │ BLE Mesh
                    ▼
        ┌────────────┬────────────┬────────────┬────────────┐
        │ patient    │ living     │ kitchen    │ wearable   │
        │ PIR/temp   │ temp/lux   │ gas/flame  │ HR/SpO2    │
        │ light/fan  │ light/fan  │ exhaust    │ health     │
        └────────────┴────────────┴────────────┴────────────┘
```

---

## 2. Vai trò từng tầng

### Raspberry Pi

Pi không còn kết nối BLE trực tiếp với từng node. Pi chỉ làm các việc:

1. Nhận lệnh điều khiển từ web.
2. Đóng gói lệnh thành JSON `mesh_command`.
3. Gửi `mesh_command` xuống ESP chính qua BLE P2P.
4. Nhận JSON `mesh_state` lớn từ ESP chính.
5. Giải mã dữ liệu theo thứ tự `patient → living → kitchen → wearable`.
6. Cập nhật state backend, lịch sử biểu đồ, cảnh báo và Socket.IO.

### ESP chính / node phòng bệnh

ESP chính là gateway giữa Pi và BLE Mesh:

1. Nhận dữ liệu cảm biến/trạng thái từ các node mesh.
2. Gom dữ liệu thành một gói JSON `mesh_state`.
3. Gửi `mesh_state` lên Pi qua BLE notify.
4. Nhận `mesh_command` từ Pi qua BLE write.
5. Giải mã `room`, `device`, `state`, `value`.
6. Forward lệnh xuống đúng node mesh.

### Các node BLE Mesh

- `patient`: PIR, nhiệt độ, độ ẩm, đèn, quạt, buzzer.
- `living`: nhiệt độ, độ ẩm, lux, đèn, quạt, auto mode.
- `kitchen`: gas, khói, lửa, cửa sổ, quạt hút.
- `wearable`: nhịp tim, SpO2, trạng thái sức khỏe.

---

## 3. Luồng truyền dữ liệu lên web

```text
Node mesh gửi sensor/device state
  ↓
ESP chính nhận và gom dữ liệu
  ↓
ESP chính tạo mesh_state JSON lớn
  ↓
BLE P2P notify lên Pi
  ↓
Pi decode packet
  ↓
Pi update ROOMS theo thứ tự:
patient → living → kitchen → wearable
  ↓
Pi emit Socket.IO:
room_update / node_status / ai_status / mesh_packet / alert_state
  ↓
Web dashboard hiển thị đúng phòng, đúng cảm biến
```

---

## 4. Luồng điều khiển từ web xuống thiết bị

```text
User bấm điều khiển trên web
  ↓
Socket.IO event: set_device
  ↓
Pi gọi set_device(room, device, state, value)
  ↓
Pi đóng gói mesh_command JSON
  ↓
BLE P2P write xuống ESP chính
  ↓
ESP chính decode target.room + target.device
  ↓
ESP chính forward qua BLE Mesh đến đúng node
  ↓
Node thực thi bật/tắt/chỉnh thiết bị
  ↓
Node gửi state mới về ESP chính
  ↓
ESP chính gom vào mesh_state gửi lại Pi để đồng bộ web
```

---

## 5. Format gói ESP chính gửi lên Pi: `mesh_state`

Firmware ESP chính nên gửi **newline-delimited JSON**, tức mỗi gói JSON kết thúc bằng `\n`. Backend đã hỗ trợ ghép lại JSON nếu BLE notify bị chia nhỏ thành nhiều chunk.

### Format khuyến nghị

```json
{
  "type": "mesh_state",
  "seq": 101,
  "ts": 1720000000,
  "nodes": {
    "patient": {
      "online": true,
      "sensors": {
        "temp": 27.5,
        "hum": 64,
        "motion": 1
      },
      "devices": {
        "light": 0,
        "fan": 1,
        "fan_speed": 70,
        "buzzer": 0
      }
    },
    "living": {
      "online": true,
      "sensors": {
        "temp": 28.0,
        "hum": 60,
        "lux": 140,
        "motion": 0
      },
      "devices": {
        "light": 1,
        "light_level": 80,
        "fan": 0,
        "fan_speed": 0,
        "auto": 1
      }
    },
    "kitchen": {
      "online": true,
      "sensors": {
        "gas": 300,
        "smoke": 0,
        "flame": 0
      },
      "devices": {
        "window": 0,
        "exhaust": 0
      }
    },
    "wearable": {
      "online": true,
      "sensors": {
        "heart_rate": 78,
        "spo2": 98
      }
    }
  }
}
```

### Format phẳng cũng được hỗ trợ

Backend cũng chấp nhận format sau:

```json
{
  "type": "mesh_state",
  "seq": 102,
  "nodes": {
    "patient": {"online": true, "temp": 27.5, "hum": 64, "motion": 1, "light": 0},
    "living": {"online": true, "temp": 28.0, "hum": 60, "lux": 140, "light": 1},
    "kitchen": {"online": true, "gas": 300, "smoke": 0, "flame": 0},
    "wearable": {"online": true, "heart_rate": 78, "spo2": 98}
  }
}
```

---

## 6. Format gói Pi gửi xuống ESP chính: `mesh_command`

Khi web điều khiển thiết bị, backend gửi xuống ESP chính gói như sau:

```json
{
  "type": "mesh_command",
  "seq": 12,
  "ts": 1720000001.25,
  "source": "manual",
  "target": {
    "room": "kitchen",
    "device": "exhaust"
  },
  "cmd": "exhaust",
  "room": "kitchen",
  "state": 1
}
```

Ví dụ bật quạt phòng bệnh tốc độ 70%:

```json
{
  "type": "mesh_command",
  "seq": 13,
  "source": "gesture",
  "target": {
    "room": "patient",
    "device": "fan"
  },
  "cmd": "fan",
  "room": "patient",
  "state": 1,
  "value": 70
}
```

ESP chính chỉ cần ưu tiên các field:

- `target.room` hoặc `room`
- `target.device` hoặc `cmd`
- `state`
- `value`
- `seq`

---

## 7. Cấu hình `.env`

Tạo file `.env` từ `.env.example` và sửa MAC/UUID theo thiết bị thật.

```env
SECRET_KEY=smart_home_secret_key_2026_change_me
DATABASE=smart_home.db
ALLOW_REGISTER=1
ADMIN_REGISTER_CODE=FAMILY2026

# BLE P2P + BLE Mesh
BLE_ENABLE=1
BLE_TOPOLOGY=p2p_mesh
BLE_GATEWAY_ROOM=patient
BLE_GATEWAY_MAC=a0:f2:62:a5:6d:16
BLE_NOTIFY_UUID=beb5483e-36e1-4688-b7f5-ea07361b26a8
BLE_COMMAND_UUID=1c95d5e3-d03b-4c71-b54d-172fa5545a74
BLE_WRITE_CHUNK_SIZE=180
BLE_WRITE_WITH_RESPONSE=0
BLE_RX_BUFFER_LIMIT=12000
BLE_RECONNECT_DELAY=3

# UART servo
UART_ENABLE=1
UART_PORT=/dev/ttyUSB0
UART_BAUD=115200

# Camera AI
CAMERA_MODE_DEFAULT=auto
VIDEO_SOURCE=0
CAMERA_WIDTH=320
CAMERA_HEIGHT=240
JPEG_QUALITY=60
PROCESS_EVERY_N_FRAMES=5
STATUS_EMIT_INTERVAL=0.3
STREAM_SLEEP=0.02

# Medical RAG
GEMINI_API_KEY=your_key_here
GEMINI_CHAT_MODEL=gemini-2.5-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
MEDICAL_RAG_AUTO_INGEST=0
```

Nếu muốn chạy test web trên laptop không có BLE:

```env
BLE_ENABLE=0
UART_ENABLE=0
CAMERA_MODE_DEFAULT=off
```

Nếu muốn quay lại firmware cũ Pi kết nối từng node:

```env
BLE_TOPOLOGY=legacy_multi_node
```

---

## 8. Cấu trúc source

```text
project/
├── app.py
├── config.py
├── database.py
├── iot.py
├── web.py
├── medical_rag.py
├── ingest_medical_docs.py
├── requirements.txt
├── README.md
└── .env.example
```

---

## 9. Chạy backend

```bash
pip install -r requirements.txt
cp .env.example .env
python app.py
```

Mở dashboard:

```text
http://<ip-raspberry-pi>:5000
```

---

## 10. Các Socket.IO event chính

Backend vẫn giữ event cũ để frontend không phải đổi nhiều:

- `request_initial_state`
- `set_device`
- `set_camera_mode`
- `set_tracking`
- `confirm_safe`
- `control_device`

Backend emit lên web:

- `bootstrap`
- `room_update`
- `node_status`
- `sensor_chart_update`
- `mesh_packet`
- `system_alert`
- `alert_state`
- `camera_sync`
- `ai_status`

---

## 11. Ghi chú quan trọng cho firmware ESP chính

1. Nên gửi mỗi `mesh_state` kết thúc bằng `\n`.
2. Nên có `seq` tăng dần để Pi bỏ qua packet trùng.
3. Nên gửi full snapshot 4 node mỗi chu kỳ, hoặc ít nhất gửi node nào có thay đổi.
4. Nên có `online` cho từng node để dashboard biết node nào mất mesh.
5. Khi nhận `mesh_command`, ESP chính nên ACK hoặc gửi lại state mới trong `mesh_state` tiếp theo.
6. Nếu JSON lớn hơn MTU BLE, ESP chính có thể chia notify thành nhiều chunk; backend Pi đã có buffer ghép lại.

---

## 12. Điểm đã chỉnh trong backend

- Thêm cấu hình `BLE_TOPOLOGY=p2p_mesh`.
- Thêm BLE gateway config: `BLE_GATEWAY_MAC`, `BLE_GATEWAY_NOTIFY_UUID`, `BLE_GATEWAY_COMMAND_UUID`.
- Pi chỉ mở 1 BLE connection đến ESP chính.
- Thêm parser `mesh_state` để giải mã JSON lớn.
- Thêm builder `mesh_command` để đóng gói lệnh từ web.
- Giữ API/socket web hiện tại để frontend ít phải chỉnh.
- Giữ fallback `legacy_multi_node` để test firmware cũ.
