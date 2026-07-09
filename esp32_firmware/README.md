# Tài liệu Kỹ thuật Firmware ESP32-C3 Super Mini (AIoT Care Station)

Thư mục này chứa mã nguồn C++ (Arduino) cho 3 mạch ESP32-C3 đóng vai trò là các node cảm biến BLE giao tiếp với Raspberry Pi.

---

## 1. Kiến trúc Giao tiếp (BLE & JSON)
Mỗi ESP32 hoạt động như một **BLE Server**.
*   **Service UUID:** `4fafc201-1fb5-459e-8fcc-c5c9c331914b`
*   **Notify UUID (Gửi đi):** `beb5483e-36e1-4688-b7f5-ea07361b26a8`
*   **Write UUID (Nhận lệnh):** `1c95d5e3-d03b-4c71-b54d-172fa5545a74`

Tất cả dữ liệu truyền nhận đều ở định dạng **JSON**. ESP32 sẽ gửi chuỗi JSON lên Pi mỗi 1 giây (1000ms), và Pi sẽ gửi chuỗi JSON xuống ESP32 khi người dùng bấm nút trên Web.

---

## 2. Chi tiết Từng Node

### 🔴 NODE 1: Patient Node (Phòng Người Bệnh)
**Mục đích:** Theo dõi nhiệt độ, độ ẩm, rò rỉ khí gas, phát hiện ngã/chuyển động, bật đèn/quạt/còi báo động.

#### Sơ đồ cắm chân (Pinout)
| Linh kiện | Chân (Pin) | Loại (I/O) | Ghi chú |
| :--- | :--- | :--- | :--- |
| Cảm biến DHT11/22 | `2` | INPUT | Đọc Nhiệt độ (`temp`) và Độ ẩm (`hum`) |
| Cảm biến khí Gas (MQ2) | `3` | ANALOG | Đọc nồng độ Gas (`gas`), trả về giá trị Analog (0-4095) |
| Cảm biến chuyển động (PIR) | `4` | INPUT | Đọc trạng thái chuyển động (`motion`), Mức `HIGH` là có chuyển động |
| Relay Đèn | `5` | OUTPUT | Bật/tắt đèn phòng (`light`) |
| Relay Quạt | `6` | OUTPUT | Bật/tắt quạt (`fan`) |
| Còi Báo Động (Buzzer) | `7` | OUTPUT | Kêu to khi phát hiện ngã hoặc cảnh báo khẩn cấp (`buzzer`) |

#### Logic Giao tiếp (Gửi/Nhận)
*   **Gửi lên Pi (Notify):** 
    ```json
    {"room": "patient", "temp": 25.5, "hum": 60.5, "gas": 420, "motion": true}
    ```
*   **Nhận từ Pi (Write):** 
    ```json
    {"light": true, "fan": false, "buzzer": true}
    ```
*   **Logic xử lý:** Khi Pi gửi lệnh bật đèn (`"light": true`), ESP32 sẽ parse JSON bằng thư viện `ArduinoJson`, kiểm tra biến và set cờ `digitalWrite(PIN_LIGHT, HIGH)`.

---

### 🟢 NODE 2: Living Node (Phòng Khách)
**Mục đích:** Theo dõi nhiệt độ, độ ẩm, cường độ ánh sáng, tự động bật đèn khi có người và trời tối.

#### Sơ đồ cắm chân (Pinout)
| Linh kiện | Chân (Pin) | Loại (I/O) | Ghi chú |
| :--- | :--- | :--- | :--- |
| Cảm biến DHT11/22 | `2` | INPUT | Đọc Nhiệt độ (`temp`) và Độ ẩm (`hum`) |
| Cảm biến chuyển động (PIR) | `3` | INPUT | Đọc trạng thái chuyển động (`motion`), `HIGH` là có người |
| Cảm biến ánh sáng (LDR) | `4` | ANALOG | Đọc độ sáng (`lux`), trả về Analog (0-4095) |
| Relay Đèn | `5` | OUTPUT | Bật/tắt đèn phòng (`light`) |
| Relay Quạt | `6` | OUTPUT | Bật/tắt quạt (`fan`) |

#### Logic Giao tiếp (Gửi/Nhận)
*   **Gửi lên Pi (Notify):** 
    ```json
    {"room": "living", "temp": 26.2, "hum": 55.0, "lux": 850, "motion": false}
    ```
*   **Nhận từ Pi (Write):** 
    ```json
    {"light": true, "fan": true, "auto": true}
    ```
*   **Logic xử lý:** Biến `auto_mode` (lưu trạng thái tự động) sẽ được cập nhật từ lệnh của Pi. Nếu `auto=true`, hệ thống web Pi sẽ tự động phân tích có người và gửi lệnh bật đèn xuống, hoặc bạn có thể lập trình thêm vào hàm `loop()` của ESP32.

---

### 🟡 NODE 3: Kitchen Node (Phòng Bếp)
**Mục đích:** Cảnh báo hỏa hoạn, rò rỉ gas, tự động bật quạt hút và mở cửa sổ thoát khí.

#### Sơ đồ cắm chân (Pinout)
| Linh kiện | Chân (Pin) | Loại (I/O) | Ghi chú |
| :--- | :--- | :--- | :--- |
| Cảm biến khí Gas (MQ2) | `2` | ANALOG | Cảnh báo gas rò rỉ (`gas`) |
| Cảm biến Khói (MQ135) | `3` | INPUT | Báo có khói (`smoke`), `HIGH` là có khói |
| Cảm biến Lửa (IR Flame) | `4` | INPUT | Báo có lửa (`flame`), **Lưu ý:** Thường cảm biến lửa trả về `LOW` khi phát hiện lửa. Mã nguồn đã đảo ngược logic này thành `flame = (digitalRead(PIN_FLAME) == LOW)`. |
| Động cơ Servo (Cửa sổ) | `5` | PWM | Đóng/mở cửa sổ thoát khí (`window`). 0 độ là đóng, 90 độ là mở. |
| Relay Quạt Hút | `6` | OUTPUT | Bật/tắt quạt hút khói/gas (`exhaust`) |

#### Logic Giao tiếp (Gửi/Nhận)
*   **Gửi lên Pi (Notify):** 
    ```json
    {"room": "kitchen", "gas": 300, "smoke": false, "flame": false}
    ```
*   **Nhận từ Pi (Write):** 
    ```json
    {"window": true, "exhaust": true}
    ```
*   **Logic xử lý:** Khi Pi phát hiện cháy, hệ thống IoT (web) sẽ tự động gửi lệnh `{"window": true, "exhaust": true}` xuống. ESP32 nhận được sẽ dùng thư viện `ESP32Servo` quay servo cửa sổ góc 90 độ và bật Relay quạt hút.

---

## 3. Hướng dẫn Nạp Code và Thư viện
1. Cài đặt **Arduino IDE** và thêm Boards Manager cho ESP32.
2. Chọn Board: **ESP32C3 Dev Module** (Bật `USB CDC On Boot: Enabled`).
3. Cài các thư viện sau từ Library Manager:
   - **ArduinoJson** (bởi Benoit Blanchon) - Dùng để parse/tạo chuỗi JSON.
   - **ESP32Servo** (bởi Kevin Harrington) - Dùng điều khiển servo vì thư viện Servo cũ không hỗ trợ tốt ESP32.
4. Mở từng file `.ino`, nạp code.
5. Sau khi nạp xong, dùng app **nRF Connect** (trên điện thoại) để dò tìm địa chỉ MAC của từng Node.
6. Điền MAC vào file `.env` trên Raspberry Pi. Khởi động lại Pi là xong!
