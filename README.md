# AIoT Care Station — Hệ thống giám sát chăm sóc người bệnh

Hệ thống nhà thông minh 3 phòng dùng **BLE** làm phương thức truyền dữ liệu chính (không dùng MQTT),
Raspberry Pi 4 làm gateway chạy Flask + Socket.IO, camera AI bám người + phát hiện té ngã,
và **UART** để gửi góc servo tracking tới ESP(1) ở phòng người bệnh.

## 1. Cấu trúc thư mục

```
project/
├── app.py              # điểm khởi động Flask + Socket.IO
├── web.py              # route + socket handlers
├── iot.py              # BLE (3 node) + UART servo + camera AI + cảnh báo
├── config.py           # cấu hình (MAC, UART, ngưỡng...)
├── database.py         # SQLite: users, login_logs, audit_logs, system_configs
├── requirements.txt
├── smart_home.db       # (tự tạo khi chạy lần đầu)
└── templates/
    ├── index.html      # dashboard chính
    ├── login.html
    └── register.html
```

> **Quan trọng:** ba file `index.html`, `login.html`, `register.html` phải nằm trong thư mục `templates/`.

## 2. Cài đặt & chạy

```bash
pip install -r requirements.txt
python app.py
# mở http://<ip-raspberry>:5000
```

Tài khoản mặc định: `admin / admin123` (quản trị) · `khoi / khoi1234` (thành viên).
Mã đăng ký nội bộ mặc định: `FAMILY2026` (đổi trong tab **Cấu hình hệ thống**).

## 3. Cấu hình (config.py hoặc biến môi trường)

| Biến | Ý nghĩa | Mặc định |
|------|---------|----------|
| `BLE_MAC_PATIENT` / `BLE_MAC_LIVING` / `BLE_MAC_KITCHEN` | MAC BLE của 3 node ESP32 | (sửa theo thiết bị) |
| `BLE_NOTIFY_UUID` / `BLE_COMMAND_UUID` | UUID characteristic notify / write | (mặc định trong config) |
| `UART_PORT` | cổng serial tới ESP(1) servo | `/dev/ttyUSB0` (hoặc `/dev/serial0`) |
| `UART_BAUD` | baudrate UART | `115200` |
| `SERVO_KP`, `SERVO_DEADZONE_PX`, `SERVO_SMOOTHING`, `SERVO_INVERT` | tinh chỉnh tracking | xem config |
| `CAMERA_MOTION_TIMEOUT` | giây không thấy PIR thì tắt camera (chế độ auto) | `20` |
| `GAS_WARN_THRESHOLD` / `GAS_HIGH_THRESHOLD` | ngưỡng cảnh báo nhẹ / khẩn cấp | `1500` / `2500` |

## 4. Giao thức firmware — BLE (mỗi node ESP32)

Mỗi node **gửi telemetry** (BLE notify, characteristic `BLE_NOTIFY_UUID`) dạng JSON. Chỉ cần gửi các trường có thật:

**Node phòng người bệnh (patient):**
```json
{"temp":27.5,"hum":64,"gas":420,"motion":1,"light":0,"fan":0,"fan_speed":0,"buzzer":0}
```
**Node phòng khách (living):**
```json
{"temp":28.0,"hum":60,"motion":1,"lux":140,"light":0,"light_level":0,"fan":0,"fan_speed":0,"auto":1}
```
**Node phòng bếp (kitchen):**
```json
{"gas":300,"smoke":0,"flame":0,"window":0,"exhaust":0}
```
> `motion` của node patient chính là **PIR** — Pi dùng nó để tự bật camera (chế độ auto).
> Có thể thêm trường `"room":"patient"` trong JSON nếu muốn Pi tự định tuyến thay vì theo MAC.

Mỗi node **nhận lệnh** (BLE write, characteristic `BLE_COMMAND_UUID`) dạng JSON:
```json
{"cmd":"light","state":1}            // bật/tắt đèn
{"cmd":"fan","state":1,"value":60}   // bật quạt + tốc độ %
{"cmd":"buzzer","state":1}
{"cmd":"window","state":1}           // mở cửa sổ (bếp)
{"cmd":"exhaust","state":1}          // quạt hút (bếp)
{"cmd":"auto","state":0}             // tắt chế độ tự động (khách)
```

## 5. Giao thức firmware — UART (ESP(1) servo pan phòng bệnh)

Pi tính góc bám người từ camera và gửi liên tục (≤ ~12 Hz) qua UART:
```
A090\n      // góc servo = 90 độ (0..180); ESP(1) parse số sau 'A'
```
ESP(1) chỉ cần đọc dòng, tách số và `servo.write(angle)`. Khi tắt tracking, Pi gửi góc giữa (`A090`).

## 6. Camera bật theo PIR

- **Tự động (mặc định):** PIR phòng bệnh phát hiện chuyển động → Pi bật camera; hết chuyển động quá `CAMERA_MOTION_TIMEOUT` giây → tự tắt.
- **Bật / Tắt thủ công:** dùng công tắc 3 chế độ (Tự động / Bật / Tắt) trên dashboard, trang **Phòng người bệnh**.
- Camera chạy MediaPipe **Pose** (bám người + phát hiện té ngã) và **Hands** (cử chỉ điều khiển đèn/quạt, giãn cách frame để nhẹ CPU).

## 7. Luồng cảnh báo (state machine)

`Bình thường → Cảnh báo nhẹ → Khẩn cấp → Chờ xác nhận`. Khi khẩn cấp (khói/lửa/gas cao):
bật quạt hút + mở cửa sổ + buzzer, **giữ đèn và camera**, gửi Telegram + ghi log.
Khi hết nguy hiểm chuyển sang *Chờ xác nhận* — cần bấm nút xác nhận trên dashboard mới khôi phục thiết bị.
Phát hiện té ngã là luồng cảnh báo y tế riêng (buzzer + Telegram + log).
