# Firmware ESP32-C3

[Về dự án](../README.md) · [Sơ đồ chân ba node](../docs/HARDWARE.md)

| Sketch | Tên quảng bá BLE | Vai trò |
| --- | --- | --- |
| `patient_node/patient_node.ino` | `AIoT_Patient_Node` | SHT, PIR, relay đèn, quạt, buzzer, servo qua UART |
| `living_node/living_node.ino` | `AIoT_Living_Node` | SHT, BH1750, HLK-LD2420, đèn, quạt tự động |
| `kitchen_node/kitchen_node.ino` | `AIoT_Kitchen_Node` | Gas, khói, lửa, cửa sổ, quạt hút, đèn, buzzer |

Hai header dùng chung: `command_contract.h` xử lý lệnh/ACK, `node_logic.h` chứa
logic tự động bếp và phòng khách. Giữ nguyên cấu trúc thư mục khi mở/biên dịch sketch
vì các sketch include header bằng đường dẫn `../`.

## Biên dịch và nạp

Trong Arduino IDE, dùng ESP32 board package và chọn board phù hợp ESP32-C3 của bạn
(cấu hình dự án trước đây dùng **ESP32C3 Dev Module**, USB CDC On Boot bật).
Các thư viện mà mã nguồn sử dụng:

- BLE, Wire và FreeRTOS trong ESP32 Arduino core.
- ArduinoJson, ESP32Servo, Adafruit SHT31 Library, BH1750.

Repo chưa khóa phiên bản ESP32 core/thư viện. Biên dịch từng sketch để xác nhận tương
thích trước khi nạp; test C++ trên máy chỉ kiểm tra logic trong header.
Mở Serial Monitor **115200**, đọc MAC được in khi boot và cập nhật cấu hình gateway.

## Giao thức BLE

| Thành phần | UUID |
| --- | --- |
| Service | `4fafc201-1fb5-459e-8fcc-c5c9c331914b` |
| Notify: node → gateway | `beb5483e-36e1-4688-b7f5-ea07361b26a8` |
| Write: gateway → node | `1c95d5e3-d03b-4c71-b54d-172fa5545a74` |

Telemetry là JSON kết thúc bằng newline, được chia thành các đoạn notify tối đa
20 byte. Gateway phải ghép lại trước khi parse. Mỗi node gửi khoảng một lần/giây
khi kết nối; mất kết nối thì quảng bá trở lại.

Lệnh ví dụ: `{"id":1,"cmd":"buzzer","state":1,"buzzer":true}`.
Node trả ACK với cùng `id` và trạng thái `applied`, `rejected` hoặc `busy`.
Quạt nhận PWM 0–255 trên đường BLE; backend đổi phần trăm 0–100 của giao diện sang PWM.

## Logic hiện tại

### Bếp

`KitchenState` đọc cảm biến mỗi khoảng 100 ms, kể cả lúc mất BLE:

- Gas ADC ≥ 1500: còi cảnh báo nhịp 300 ms mỗi 2 giây.
- Gas ADC ≥ 2500, có khói hoặc có lửa: mở cửa, bật quạt hút và còi, **tắt đèn**.
- Trong trạng thái khẩn cấp, node từ chối lệnh điều khiển thủ công.
- Khi hết cả nguy hiểm và cảnh báo liên tục 10 giây, node chuyển sang trạng thái
  chờ xác nhận và vẫn giữ cửa mở, quạt hút/còi bật, đèn tắt.
- Chỉ sau lệnh `confirm_safe` từ gateway, node mới khôi phục các đầu ra đã lưu.

Ngưỡng này nằm trong `node_logic.h`; đổi biến môi trường ngưỡng gas trên gateway
không tự đổi ngưỡng đã biên dịch trong node. Backend còn có quy trình cảnh báo và
xác nhận khôi phục các phòng khác; không đồng nhất việc node bếp hết cảnh báo với
việc toàn bộ hệ thống đã hoàn tất xác nhận.

### Phòng khách

Chế độ tự động chạy cục bộ ngay cả khi mất BLE. Khi radar xác nhận có người gần đây: bật
đèn nếu lux < 100; quạt 100% nếu nhiệt độ ≥ 30 hoặc độ ẩm ≥ 75, khoảng 50% nếu
nhiệt độ ≥ 27 hoặc độ ẩm ≥ 65, còn lại tắt. Không phát hiện hiện diện trong 120 giây
thì tắt đèn/quạt. Lệnh đèn hoặc quạt thủ công tắt `auto`; lệnh `auto` bật lại chế độ này.

### Phòng bệnh

Relay đèn GPIO4, quạt và buzzer nhận lệnh BLE. Servo nhận góc qua UART1 trên GPIO20/21, không qua
lệnh servo BLE. Camera và xử lý AI chạy trên gateway.

Các hành vi trên mô tả mã nguồn hiện tại, không khẳng định tất cả board đang được
nạp đúng phiên bản này. Patient/living hiện thay nhiệt độ hoặc độ ẩm NaN thành 0
khi gửi telemetry; không xem số 0 là bằng chứng cảm biến hoạt động bình thường.
