# Tài liệu Kỹ thuật Firmware ESP32-C3 Super Mini (AIoT Care Station)

Thư mục này chứa mã nguồn C++ (Arduino) cho 3 mạch ESP32-C3 dựa trên **chuẩn sơ đồ phần cứng mới nhất (sodochan.xlsx)**.

---

## 1. Kiến trúc Giao tiếp (BLE & JSON)
Mỗi ESP32 hoạt động như một **BLE Server**.
*   **Service UUID:** `4fafc201-1fb5-459e-8fcc-c5c9c331914b`
*   **Notify UUID (Gửi đi):** `beb5483e-36e1-4688-b7f5-ea07361b26a8`
*   **Write UUID (Nhận lệnh):** `1c95d5e3-d03b-4c71-b54d-172fa5545a74`

Tất cả dữ liệu truyền nhận đều ở định dạng **JSON**. 

---

## 2. Chi tiết Từng Node (Chuẩn theo sodochan.xlsx)

### 🔴 NODE 1: Patient Node (Phòng Người Bệnh)
**Mục đích:** Đọc SHT30, PIR, điều khiển quạt, còi và nhận UART từ Pi để quay servo theo dõi khuôn mặt.

#### Sơ đồ cắm chân (Pinout)
| Thiết bị | Chân thiết bị | Tín hiệu | ESP32-C3 | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **SHT30** | SDA / SCL | I2C | **GPIO8 / GPIO9** | Đo nhiệt độ, độ ẩm |
| **Buzzer** | VCC | Digital/PWM | **GPIO0** | Còi báo động |
| **Driver quạt** | IN1 / IN2 | Digital/PWM | **GPIO1 / GPIO2** | Quạt làm mát |
| **UART Pi** | RX / TX | UART | **GPIO20 / GPIO21** | Kết nối với Serial của Pi |
| **Servo tracking**| Signal | PWM | **GPIO6** | Xoay camera theo người |
| **PIR HC-SR501** | OUT | Digital Input | **GPIO5** | Cảm biến chuyển động |

#### Logic Giao tiếp
*   **Gửi lên Pi:** `{"room":"patient","temp":25.5,"hum":60.5,"motion":true}`
*   **Nhận từ Pi:** `{"fan": true, "buzzer": true}`
*   **Xử lý UART Servo:** Pi gửi qua dây Serial chuỗi góc ví dụ `A90\n`, Node giải mã và điều khiển servo xoay camera.

---

### 🟢 NODE 2: Living Node (Phòng Khách)
**Mục đích:** Theo dõi nhiệt độ, độ ẩm, độ sáng. Điều khiển quạt, đèn.

#### Sơ đồ cắm chân (Pinout)
| Thiết bị | Chân thiết bị | Tín hiệu | ESP32-C3 | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **PIR HC-SR501** | OUT | Digital Input | **GPIO10** | Cảm biến chuyển động |
| **BH1750** | SDA / SCL | I2C | **GPIO8 / GPIO9** | Cảm biến ánh sáng |
| **SHT30** | SDA / SCL | I2C | **GPIO8 / GPIO9** | Cảm biến nhiệt độ, độ ẩm (Chung bus I2C) |
| **Relay đèn** | IN | Digital Output| **GPIO7** | Bật tắt đèn |
| **Driver quạt** | IN1 / IN2 | Digital/PWM | **GPIO1 / GPIO2** | Quạt làm mát |

#### Logic Giao tiếp
*   **Gửi lên Pi:** `{"room":"living","temp":26.2,"hum":55.0,"lux":850,"motion":false}`
*   **Nhận từ Pi:** `{"light": true, "fan": true, "auto": true}`

---

### 🟡 NODE 3: Kitchen Node (Phòng Bếp)
**Mục đích:** Báo cháy, báo rò rỉ khí gas, bật quạt hút và mở cửa sổ an toàn.

#### Sơ đồ cắm chân (Pinout)
| Thiết bị | Chân thiết bị | Tín hiệu | ESP32-C3 | Ghi chú |
| :--- | :--- | :--- | :--- | :--- |
| **MQ-2** | AO / DO | Analog/Digital| **GPIO0 / GPIO1** | Đo khí gas và khói |
| **Flame Sensor** | DO | Digital Input | **GPIO2** | Báo có lửa (Mức LOW) |
| **Servo SG90** | Signal | PWM | **GPIO3** | Cửa sổ thoáng khí |
| **Relay đèn** | IN | Digital Output| **GPIO4** | Bật đèn bếp |
| **Driver quạt hút**| IN1 / IN2 | Digital/PWM | **GPIO7 / GPIO8** | Quạt thông gió |

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
