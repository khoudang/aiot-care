# Hướng dẫn nạp Firmware cho ESP32-C3 Super Mini (3 Node)

Thư mục này chứa mã nguồn C++ (Arduino) cho 3 mạch ESP32-C3 đóng vai trò là các node cảm biến BLE:
- `patient_node`: Theo dõi sức khỏe, phát hiện ngã (qua PIR giả lập), khí gas, điều khiển quạt/đèn.
- `living_node`: Đo sáng, nhiệt độ, độ ẩm, tự động hóa đèn.
- `kitchen_node`: Cảnh báo cháy, rò rỉ gas, điều khiển quạt hút và đóng mở cửa sổ (Servo).

## 1. Cài đặt môi trường (Arduino IDE)
1. Tải và cài đặt [Arduino IDE](https://www.arduino.cc/en/software).
2. Vào **File -> Preferences**, thêm đường dẫn sau vào *Additional Boards Manager URLs*:
   `https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json`
3. Vào **Tools -> Board -> Boards Manager**, tìm `esp32` và cài đặt.
4. Chọn board: **Tools -> Board -> ESP32 Arduino -> ESP32C3 Dev Module** (hoặc board tương đương cho C3).
5. Bật USB CDC: **Tools -> USB CDC On Boot -> Enabled** (Rất quan trọng với C3 Super Mini để có thể in Serial).

## 2. Cài đặt thư viện
Vào **Sketch -> Include Library -> Manage Libraries**, tìm và cài đặt các thư viện sau:
- `ArduinoJson` (tác giả Benoit Blanchon)
- `ESP32Servo` (nếu dùng Servo ở Kitchen node)

## 3. Cách lấy địa chỉ MAC để cấu hình cho Pi
ESP32 có địa chỉ MAC BLE cố định do nhà sản xuất quy định. Để hệ thống Raspberry Pi kết nối đúng với các node này, bạn cần:
1. Nạp code cho từng Node.
2. Mở ứng dụng **nRF Connect** trên điện thoại (Android/iOS).
3. Quét Bluetooth, tìm các thiết bị có tên: `AIoT_Patient_Node`, `AIoT_Living_Node`, `AIoT_Kitchen_Node`.
4. Ghi lại địa chỉ MAC của từng node (ví dụ: `A0:F2:62:A5:6D:16`).
5. Vào thư mục code trên Raspberry Pi, mở file `.env` (hoặc `config.py`) và sửa lại các biến MAC cho khớp:
   ```env
   BLE_MAC_PATIENT=A0:F2:62:xx:xx:xx
   BLE_MAC_LIVING=A0:F2:62:yy:yy:yy
   BLE_MAC_KITCHEN=A0:F2:62:zz:zz:zz
   ```
6. Khởi động lại hệ thống trên Pi (`sudo systemctl restart aiot-care`).

## 4. Chân kết nối phần cứng (Pinout mặc định)
Bạn có thể thay đổi trong các file `.ino` nếu đấu nối thực tế khác.

**Patient Node:**
- Cảm biến: DHT (Pin 2), MQ2 (Pin 3), PIR (Pin 4)
- Thiết bị: Đèn (Pin 5), Quạt (Pin 6), Còi chip (Pin 7)

**Living Node:**
- Cảm biến: DHT (Pin 2), PIR (Pin 3), Quang trở LDR (Pin 4)
- Thiết bị: Đèn (Pin 5), Quạt (Pin 6)

**Kitchen Node:**
- Cảm biến: Khí gas MQ2 (Pin 2), Khói (Pin 3), Lửa IR (Pin 4)
- Thiết bị: Servo Cửa Sổ (Pin 5), Quạt hút (Pin 6)
