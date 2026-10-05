# API và Socket.IO

[Về README](../README.md). Đối chiếu trực tiếp [web.py](../web.py) và [iot.py](../iot.py).
Các API dữ liệu/điều khiển yêu cầu phiên đăng nhập; Socket.IO từ chối kết nối nếu
session chưa có `user_id`. Trình duyệt dùng cùng origin với web.

## HTTP

| Phương thức | Đường dẫn | Chức năng |
| --- | --- | --- |
| GET | `/api/state` | Snapshot: `rooms`, `nodes`, `ai`, `camera`, `alert`, `histories` |
| GET | `/api/history` | Các chuỗi lịch sử theo phòng |
| GET | `/video_feed` | MJPEG khi camera hoạt động |
| GET, POST | `/api/gesture_mappings` | Đọc/cập nhật ánh xạ cử chỉ |
| DELETE | `/api/gesture_mappings/<gesture_name>` | Xóa ánh xạ |
| GET | `/api/kitchen_alerts` | Lịch sử cảnh báo bếp |

API quản trị dưới `/api/admin/` yêu cầu role `admin`: users, logs và configs.
`GET /api/admin/ble-nodes` trả MAC và trạng thái ba node; `POST /api/admin/ble-nodes/<room>`
nhận `{ "mac": "AA:BB:CC:DD:EE:FF" }` để lưu và kết nối lại node tương ứng.
`GET /api/admin/ble-scan` quét các thiết bị BLE đang quảng bá gần gateway.
Điều khiển thiết bị sử dụng sự kiện Socket.IO bên dưới.

`rooms` và `nodes` gồm `patient`, `living`, `kitchen`. `camera.mode` nhận `auto`,
`on`, `off`; `alert.level` là `normal`, `light`, `emergency` hoặc `awaiting`.
Camera stream không tự quyết định chế độ camera; chế độ được quản lý ở backend.

## Socket.IO: trình duyệt gửi

| Sự kiện | Payload ví dụ | Tác dụng |
| --- | --- | --- |
| `request_initial_state` | Không cần payload | Nhận snapshot `bootstrap` |
| `set_device` | `{"room":"kitchen","device":"light","state":true}` | Điều khiển thiết bị |
| `set_device` | `{"room":"living","device":"fan","value":50}` | Tốc độ quạt 0–100% |
| `set_camera_mode` | `{"mode":"auto"}` | Chế độ camera |
| `set_tracking` | `{"enabled":true}` | Theo dõi bằng servo |
| `confirm_safe` | `{}` | Yêu cầu xác nhận an toàn; backend kiểm tra điều kiện |

Thiết bị hợp lệ: patient → `fan`, `buzzer`; living → `light`, `fan`, `auto`;
kitchen → `light`, `buzzer`, `window`, `exhaust`. Xem [node_protocol.py](../node_protocol.py).
`control_device` là sự kiện cũ nhận trường `command`, không dùng payload room/device
của `set_device`.

## Socket.IO: trình duyệt nhận

| Sự kiện | Nội dung |
| --- | --- |
| `bootstrap` | Snapshot đầy đủ giống `/api/state` |
| `room_update` | `{"room":"kitchen","data":{...}}` |
| `node_status` | Bản đồ tên phòng → trạng thái kết nối |
| `sensor_chart_update` | Lịch sử cảm biến |
| `camera_sync` | Trạng thái camera, chế độ và có thể có tracking |
| `ai_status` | Trạng thái xử lý AI camera |
| `alert_state` | `level`, `message` |
| `system_alert` | `type`, `message` |
| `command_error` | Lỗi gửi/ACK lệnh; có `room`, `message`, có thể có `device` |

Ví dụ và bảng này mô tả giao thức, không thực thi lệnh thiết bị. ACK firmware xác
nhận xử lý lệnh, không phải phản hồi đo cơ khí của cửa sổ/đèn/quạt.
