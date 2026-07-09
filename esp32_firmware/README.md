# Tài liệu Kỹ thuật Firmware ESP32-C3 Super Mini (AIoT Care Station)

Thư mục này chứa mã nguồn C++ (Arduino) cho 3 mạch ESP32-C3 dựa trên **chuẩn sơ đồ phần cứng mới nhất (sodochan.xlsx)**.

> [!CAUTION]
> **CẢNH BÁO NGUỒN ĐIỆN:** Mạch ESP32-C3 Super Mini hoạt động ở mức logic 3.3V. Bạn phải cắm chuẩn xác chân nguồn (VCC) cho các cảm biến theo bảng bên dưới. **Nếu cắm nhầm cảm biến 3.3V vào chân 5V, cảm biến sẽ cháy ngay lập tức!** Chân 5V trên mạch thường ký hiệu là `5V` hoặc `VBUS`, chân 3.3V ký hiệu là `3.3V`.

---

## 1. Kiến trúc Giao tiếp (BLE & JSON)
Mỗi ESP32 hoạt động như một **BLE Server**.
*   **Service UUID:** `4fafc201-1fb5-459e-8fcc-c5c9c331914b`
*   **Notify UUID (Gửi đi):** `beb5483e-36e1-4688-b7f5-ea07361b26a8`
*   **Write UUID (Nhận lệnh):** `1c95d5e3-d03b-4c71-b54d-172fa5545a74`

---

## 2. Chi tiết Từng Node (Chuẩn theo sodochan.xlsx)

### 🔴 NODE 1: Patient Node (Phòng Người Bệnh)
**Mục đích:** Đọc SHT30, PIR, điều khiển quạt, còi và nhận UART từ Pi để quay servo theo dõi khuôn mặt.

#### Sơ đồ cắm chân (Pinout)
| Thiết bị | Chân Nguồn (VCC) | Chân Đất (GND) | Chân Tín hiệu | ESP32-C3 | Ghi chú |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **SHT30** | **3.3V** | GND | SDA / SCL | **GPIO8 / GPIO9** | Đo nhiệt độ, độ ẩm |
| **PIR HC-SR501** | **5V** | GND | OUT | **GPIO5** | Cảm biến chuyển động |
| **Servo tracking**| **5V** | GND | Signal | **GPIO6** | Xoay camera theo người |
| **Buzzer** | N/A | GND | VCC (Signal) | **GPIO0** | Còi báo động (Cấp nguồn từ I/O) |
| **Driver quạt** | Khẩn cấp 5V/12V | GND | IN1 / IN2 | **GPIO1 / GPIO2** | Quạt làm mát |
| **UART Pi** | N/A | N/A | RX / TX | **GPIO20 / GPIO21** | Nhận UART từ Raspberry Pi |

#### Logic Giao tiếp
*   **Gửi lên Pi:** `{"room":"patient","temp":25.5,"hum":60.5,"motion":true}`
*   **Nhận từ Pi:** `{"fan": true, "buzzer": true}`
*   **Xử lý UART Servo:** Pi gửi qua dây Serial chuỗi góc ví dụ `A90\n`, Node giải mã và điều khiển servo xoay camera.

---

### 🟢 NODE 2: Living Node (Phòng Khách)
**Mục đích:** Theo dõi nhiệt độ, độ ẩm, độ sáng. Điều khiển quạt, đèn.

#### Sơ đồ cắm chân (Pinout)
| Thiết bị | Chân Nguồn (VCC) | Chân Đất (GND) | Chân Tín hiệu | ESP32-C3 | Ghi chú |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **PIR HC-SR501** | **5V** | GND | OUT | **GPIO10** | Cảm biến chuyển động |
| **BH1750** | **3.3V** | GND | SDA / SCL | **GPIO8 / GPIO9** | Cảm biến ánh sáng |
| **SHT30** | **3.3V** | GND | SDA / SCL | **GPIO8 / GPIO9** | Cảm biến nhiệt độ, độ ẩm |
| **Relay đèn** | **5V** | GND | IN | **GPIO7** | Bật tắt đèn |
| **Driver quạt** | Khẩn cấp 5V/12V | GND | IN1 / IN2 | **GPIO1 / GPIO2** | Quạt làm mát |

#### Logic Giao tiếp
*   **Gửi lên Pi:** `{"room":"living","temp":26.2,"hum":55.0,"lux":850,"motion":false}`
*   **Nhận từ Pi:** `{"light": true, "fan": true, "auto": true}`

---

### 🟡 NODE 3: Kitchen Node (Phòng Bếp)
**Mục đích:** Báo cháy, báo rò rỉ khí gas, bật quạt hút và mở cửa sổ an toàn.

#### Sơ đồ cắm chân (Pinout)
| Thiết bị | Chân Nguồn (VCC) | Chân Đất (GND) | Chân Tín hiệu | ESP32-C3 | Ghi chú |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **MQ-2** | **5V** | GND | AO / DO | **GPIO0 / GPIO1** | Đo khí gas và khói |
| **Flame Sensor** | **3.3V** | GND | DO | **GPIO2** | Báo có lửa (Mức LOW) |
| **Servo SG90** | **5V** | GND | Signal | **GPIO3** | Cửa sổ thoáng khí |
| **Relay đèn** | **5V** | GND | IN | **GPIO4** | Bật đèn bếp |
| **Driver quạt hút**| Khẩn cấp 5V/12V| GND | IN1 / IN2 | **GPIO7 / GPIO8** | Quạt thông gió |

#### Logic Giao tiếp
*   **Gửi lên Pi:** `{"room":"kitchen","gas":300,"smoke":false,"flame":false}`
*   **Nhận từ Pi:** `{"window": true, "exhaust": true, "light": true}`

---

## 3. Hướng dẫn Nạp Code và Thư viện
1. Chọn Board: **ESP32C3 Dev Module** trong Arduino IDE (Nhớ bật `USB CDC On Boot: Enabled`).
2. Cài các thư viện sau từ Library Manager:
   - **ArduinoJson** (by Benoit Blanchon)
   - **ESP32Servo** (by Kevin Harrington)
   - **Adafruit SHT31 Library** (by Adafruit)
   - **BH1750** (by Christopher Laws)
3. Nạp code vào từng mạch, sau đó dùng điện thoại (app **nRF Connect**) quét dò địa chỉ MAC Bluetooth và điền vào file `.env` trên Pi.
