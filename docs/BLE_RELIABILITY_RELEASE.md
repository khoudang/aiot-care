# Tài liệu Bàn giao Kỹ thuật: BLE Reliability Release & Cross-Layer Contract

## 1. Tổng quan & Trạng thái Release
* **Mã công việc:** `[AIOT-CARE-BLE-PI4-01]`
* **Nhánh thực hiện:** `feature/ble-pi4-readiness`
* **Base commit:** `a69772db3f5e52359e348e2e816e9c9923594686`
* **Hardware xác nhận:** Cảm biến MP-2 (Winsen), Raspberry Pi 4 Model B 4GB RAM, 3 board ESP32-C3 (bếp, phòng khách, phòng bệnh).
* **Môi trường kiểm thử thực tế:** Host simulation sandbox với fake transport deterministic, không chạm hardware thật, không kích hoạt relay/servo thật.

---

## 2. Hợp đồng Đa tầng (Cross-Layer Protocol Contract)

| Tầng | Định danh & Thuộc tính | Ngữ nghĩa / Trạng thái | Đảm bảo an toàn |
| :--- | :--- | :--- | :--- |
| **GATT Transport** | `write_gatt_char(command_uuid, json, response=True)` | Tầng BLE ATT chấp nhận packet ghi. Chưa chứng minh firmware đã thực thi. | Bounded retry (4 attempts, timeout 2s, TTL 30s). Giữ nguyên `response=True`. |
| **Application ACK** | `{"ack": <uint32_t id>, "status": "applied"\|"rejected"\|"busy"}` | Firmware ESP32 đã giải mã JSON, kiểm tra logic an toàn cục bộ, và chấp thuận lệnh logic vào biến điều khiển trong bộ nhớ (trong `drainCommands`, gói ACK phát đi trước khi gọi `applyOutputs`). | Phản hồi ngay lập tức qua notify frame riêng. Trạng thái `busy` áp dụng backoff có giới hạn (0.2s–1.0s) tránh bão retry; `rejected` hủy quy trình khôi phục. |
| **Immediate State** | `{"room": "...", "light": bool, "fan": bool, ...}` | Firmware phát frame telemetry đầu ra ngay sau khi `applyOutputs()` xuất tín hiệu GPIO. | Giảm thiểu độ trễ cập nhật so với chu kỳ 1s thông thường. Lưu ý: các mốc thời gian <10ms/<50ms là kết quả đo host simulation trong cùng tiến trình, không phải cam kết cố định trên sóng vô tuyến BLE phần cứng thực tế (phụ thuộc connection interval và RF). |
| **Physical Feedback** | *Chưa có cảm biến hành trình* | Không báo "vật lý hoàn thành" nếu không có sensor phản hồi (ví dụ: servo đã quay xung PWM nhưng cánh cửa sổ chưa có công tắc hành trình vật lý). | Hệ thống chỉ ghi nhận trung thực "đã xuất tín hiệu điều khiển" (actuator output applied). |

---

## 3. Trạng thái Node (Node Readiness States)

Hệ thống định nghĩa các trạng thái trong backend và giao diện:
1. `disconnected`: Chưa kết nối BLE.
2. `connecting`: Đang tìm kiếm và khởi tạo bắt tay BLE.
3. `subscribing`: Đã kết nối GATT, đang đăng ký nhận thông báo `start_notify`.
4. `ready`: Đăng ký `start_notify` thành công và sẵn sàng truyền nhận lệnh 2 chiều. Trạng thái này xác nhận kênh notify hoạt động, không đại diện cho việc dữ liệu telemetry liên tục tươi mới.
5. `stale`: **[CHƯA TRIỂN KHAI / NOT IMPLEMENTED — PENDING]**. Watchdog kiểm tra độ tươi telemetry theo thời gian thực (>10s) chưa được kích hoạt để tránh nguy cơ reset trạng thái an toàn ngoài ý muốn hoặc hủy lệnh an toàn khi chưa có nghiệm thu vô tuyến phần cứng. Được ghi nhận là hạng mục chờ kiểm chứng trên thiết bị thật.

> **Bảo toàn tính tương thích:** Biến và từ điển `NODE_ONLINE[room]` tiếp tục giữ giá trị `bool` (`True` khi `ready`, `False` khi ở các trạng thái khác), đảm bảo không làm gián đoạn bất kỳ luồng xử lý hoặc test case cũ nào.

---

## 4. Ma trận Nghiệm thu (Tested vs. Untested Matrix)

| Hạng mục kiểm thử | Trạng thái | Bằng chứng thực nghiệm | Ghi chú kỹ thuật |
| :--- | :---: | :--- | :--- |
| **Đo độ trễ Monotonic Trace (Priority A)** | **ĐÃ TEST** | `tests/test_ble_latency_trace.py` (8/8 tests OK) | Đo cùng tiến trình bằng monotonic clock: queue delta, GATT delta, ACK RTT delta. Bounded deque + active dict (200 items max). Không giả định correlated applied khi chỉ nhận telemetry đơn thuần. Snapshot copy an toàn dưới lock. |
| **Khám phá & Sẵn sàng (Priority B)** | **ĐÃ TEST** | `tests/test_ble_readiness.py` (6/6 tests OK), `tests/test_ble_settings.py` (3/3 tests OK) | Phối hợp single-flight discovery; 3 node thiếu MAC cùng lúc chỉ quét 1 lần trong TTL; client không phụ thuộc thuộc tính nội bộ `_device`; manual scan có rate limit; giữ cache node đang kết nối. |
| **Phản hồi tức thì & Bounded Busy Retry (Priority C)** | **ĐÃ TEST** | `tests/test_immediate_feedback.py` (3/3 tests OK), `tests/test_command_delivery.py` (9/9 tests OK), `tests/test_kitchen_control.py` (20/20 tests OK) | Đánh thức sender bằng `asyncio.Event` trên host; ACK busy áp dụng backoff 0.2s–1.0s không gây bão thử lại; bảo toàn thứ tự và ID lệnh gốc; bảo toàn logic khẩn cấp/an toàn. |
| **C++ Host Logic Firmware** | **ĐÃ TEST** | `tests/test_firmware_logic.py` (1/1 test OK) | Biên dịch logic máy trạng thái Kitchen & Living bằng `g++ -std=c++11`, kiểm tra WAIT_CONFIRM, confirm_safe và sound(). ACK phát trước applyOutputs; không hạ ngưỡng an toàn gas. |
| **Script Chẩn đoán Pi 4 Preflight (Priority D)** | **ĐÃ TEST** | `tests/test_pi_preflight.py` (1/1 test OK), `scripts/pi_preflight.py --json` | Chạy read-only độc lập, kiểm tra OS, arch, Python, BlueZ, RAM, nhiệt độ, masked configuration. Cấu hình systemd có bounded restart `StartLimitIntervalSec=60s`. |
| **MP-2 Sensor Honesty (Priority E)** | **ĐÃ TEST** | `tests/test_kitchen_control.py` | ADC thô 0-4095; `gas_unit: raw_adc`, `calibration_status: uncalibrated`, `ppm_c3h8: null`. Sấy già hóa ≥48h theo đúng Winsen manual v1.4. Không bịa hệ số ppm. |
| **Hardware Thật Pi 4 & 3 ESP32** | *CHƯA TEST (External)* | Không thao tác | Chờ môi trường phần cứng thật của người dùng để nạp firmware và nghiệm thu tín hiệu sóng thực tế. |
| **Biên dịch Firmware Full SDK Arduino** | *CHƯA TEST (Host logic only)* | Logic C++ host đã kiểm chứng | Máy host Windows không cài đặt Arduino-CLI / ESP-IDF; mã nguồn .ino được cập nhật chuẩn cú pháp, bảo toàn logic. |
