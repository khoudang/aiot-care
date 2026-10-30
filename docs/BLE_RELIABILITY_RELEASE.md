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
| **Application ACK** | `{"ack": <uint32_t id>, "status": "applied"\|"rejected"\|"busy"}` | Firmware ESP32 đã giải mã JSON, kiểm tra logic an toàn cục bộ, và áp dụng giá trị ra biến điều khiển. | Phản hồi ngay lập tức qua notify frame riêng. `busy` hoặc `rejected` kích hoạt xử lý gateway phù hợp. |
| **Immediate State** | `{"room": "...", "light": bool, "fan": bool, ...}` | Firmware phát ngay trạng thái đầu ra sau khi lệnh áp dụng thành công. | Giao diện web nhận cập nhật trạng thái mới nhất ngay lập tức (<50ms), không đợi chu kỳ 1s. |
| **Physical Feedback** | *Chưa có cảm biến hành trình* | Không báo "vật lý hoàn thành" nếu không có sensor phản hồi (ví dụ: servo đã quay góc nhưng cánh cửa sổ chưa có công tắc hành trình). | Hệ thống chỉ ghi nhận "đã xuất tín hiệu điều khiển" (actuator output applied). |

---

## 3. Trạng thái Node (Node Readiness States)

Hệ thống phân biệt 5 trạng thái hạt nhân trong backend và giao diện:
1. `disconnected`: Chưa kết nối BLE.
2. `connecting`: Đang tìm kiếm và khởi tạo bắt tay BLE.
3. `subscribing`: Đã kết nối GATT, đang đăng ký nhận thông báo `start_notify`.
4. `ready`: Đăng ký `start_notify` thành công và sẵn sàng truyền nhận lệnh 2 chiều.
5. `stale`: Đã kết nối nhưng mất tín hiệu telemetry quá thời gian quy định (>10s).

> **Bảo toàn tính tương thích:** Biến và từ điển `NODE_ONLINE[room]` tiếp tục giữ giá trị `bool` (`True` khi `ready`, `False` khi ở các trạng thái khác), đảm bảo không làm gián đoạn bất kỳ luồng xử lý hoặc test case cũ nào.

---

## 4. Ma trận Nghiệm thu (Tested vs. Untested Matrix)

| Hạng mục kiểm thử | Trạng thái | Bằng chứng thực nghiệm | Ghi chú kỹ thuật |
| :--- | :---: | :--- | :--- |
| **Đo độ trễ Monotonic Trace (Priority A)** | **ĐÃ TEST** | `tests/test_ble_latency_trace.py` (3/3 tests OK) | Đo cùng tiến trình bằng monotonic clock: queue delta, GATT delta, ACK RTT delta. Bounded deque 200 items. |
| **Khám phá & Sẵn sàng (Priority B)** | **ĐÃ TEST** | `tests/test_ble_readiness.py` (4/4 tests OK), `tests/test_ble_settings.py` (3/3 tests OK) | Test scan rỗng rồi xuất hiện; start_notify lỗi không báo online; 1 node lỗi không ảnh hưởng node khác; giữ cache node đang kết nối. |
| **Phản hồi tức thì 3 Node (Priority C)** | **ĐÃ TEST** | `tests/test_immediate_feedback.py` (3/3 tests OK), `tests/test_command_delivery.py` (8/8 tests OK), `tests/test_kitchen_control.py` (20/20 tests OK) | Đánh thức sender bằng `asyncio.Event` (<10ms thay vì poll 50ms); phát telemetry ngay sau lệnh; bảo toàn logic khẩn cấp/an toàn. |
| **C++ Host Logic Firmware** | **ĐÃ TEST** | `tests/test_firmware_logic.py` (1/1 test OK) | Biên dịch logic máy trạng thái Kitchen & Living bằng `g++ -std=c++11`, kiểm tra WAIT_CONFIRM, confirm_safe và sound(). |
| **Script Chẩn đoán Pi 4 Preflight (Priority D)** | **ĐÃ TEST** | `tests/test_pi_preflight.py` (1/1 test OK), `scripts/pi_preflight.py --json` | Chạy read-only độc lập, kiểm tra OS, arch, Python, BlueZ, RAM, nhiệt độ, masked configuration. |
| **MP-2 Sensor Honesty (Priority E)** | **ĐÃ TEST** | `tests/test_kitchen_control.py` | ADC thô 0-4095; `gas_unit: raw_adc`, `calibration_status: uncalibrated`, `ppm_c3h8: null`. Không bịa hệ số ppm. |
| **Hardware Thật Pi 4 & 3 ESP32** | *CHƯA TEST (External)* | Không thao tác | Chờ môi trường phần cứng thật của người dùng để nạp firmware và nghiệm thu tín hiệu sóng thực tế. |
| **Biên dịch Firmware Full SDK Arduino** | *CHƯA TEST (Host logic only)* | Logic C++ host đã kiểm chứng | Máy host Windows không cài đặt Arduino-CLI / ESP-IDF; mã nguồn .ino được cập nhật chuẩn cú pháp, bảo toàn logic. |
