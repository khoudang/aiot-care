# Sơ đồ chân phần cứng

[Về README](../README.md) · [Firmware](../esp32_firmware/README.md) · [CSV](hardware/pinout.csv)

Bảng này được đối chiếu với hằng `PIN_*` của ba sketch hiện tại. **GPIO là số GPIO
trên ESP32-C3, không phải thứ tự chân vật lý trên board.** Kiểm tra nhãn in trên board.
Không sử dụng sơ đồ cũ trong thư mục `hardware/reference/` để đấu node bếp hiện tại.

## Phòng bếp — `kitchen`

Tên BLE: `AIoT_Kitchen_Node`. MAC dự kiến: **`E8:3D:C1:9D:A5:16`**;
đối chiếu MAC thực tế trong Serial Monitor và đặt `BLE_MAC_KITCHEN` trên gateway.

| Thiết bị | Tín hiệu | ESP32-C3 | Quy ước trong firmware |
| --- | --- | --- | --- |
| MQ-2 (người dùng ghi MP-2) | AO | GPIO0 | Đọc ADC thô, chưa quy đổi ppm |
| MQ-2 | DO | GPIO1 | HIGH = báo khói theo code hiện tại |
| Cảm biến lửa | DO | GPIO2 | LOW = phát hiện lửa |
| Servo SG90 cửa sổ | Signal | GPIO4 | 0° đóng, 90° mở theo lệnh servo |
| Buzzer chủ động | Signal | GPIO5 | HIGH bật, LOW tắt; loại đã thử có tiếng |
| Driver quạt hút | IN1 | GPIO7 | HIGH khi chạy |
| Driver quạt hút | IN2 | GPIO8 | LOW |
| Relay đèn | IN | GPIO20 | HIGH bật, LOW tắt theo code |

```text
MQ-2 AO ───────────── GPIO0       SG90 Signal ───── GPIO4
MQ-2 DO ───────────── GPIO1       Buzzer Signal ─── GPIO5
Flame DO ──────────── GPIO2       Quạt IN1 ──────── GPIO7
Relay đèn IN ──────── GPIO20      Quạt IN2 ──────── GPIO8
```

## Phòng người bệnh — `patient`

Tên BLE: `AIoT_Patient_Node`. Cấu hình địa chỉ thực tế bằng `BLE_MAC_PATIENT`.

| Thiết bị | Tín hiệu | ESP32-C3 | Ghi chú |
| --- | --- | --- | --- |
| SHT30/SHT31 | SDA | GPIO8 | I²C, địa chỉ code dùng `0x44` |
| SHT30/SHT31 | SCL | GPIO9 | Chung bus I²C |
| PIR | OUT | GPIO5 | HIGH = có chuyển động |
| Buzzer | Signal | GPIO0 | HIGH bật, LOW tắt |
| Driver quạt | IN1 / IN2 | GPIO1 / GPIO2 | PWM trên IN1; IN2 LOW |
| Servo camera | Signal | GPIO6 | Khởi động ở 90° |
| UART từ gateway | RX | GPIO20 | Nối TX của Pi/USB–UART vào đây |
| UART về gateway | TX | GPIO21 | Nối RX của Pi/USB–UART nếu cần |

UART dùng **115200 baud, 8N1**, chuỗi ví dụ `A90\n` (kết thúc bằng ký tự xuống dòng).
Nối chung GND. `UART_PORT` phải là cổng thực tế; USB dùng nạp sketch không mặc nhiên
là UART1 trên GPIO20/21. Chưa gán chân relay đèn cho phòng bệnh.

## Phòng khách — `living`

Tên BLE: `AIoT_Living_Node`. Cấu hình địa chỉ thực tế bằng `BLE_MAC_LIVING`.

| Thiết bị | Tín hiệu | ESP32-C3 | Ghi chú |
| --- | --- | --- | --- |
| SHT30/SHT31 và BH1750 | SDA | GPIO8 | Chung bus; địa chỉ `0x44` và `0x23` |
| SHT30/SHT31 và BH1750 | SCL | GPIO9 | Chung bus I²C |
| PIR | OUT | GPIO10 | HIGH = có chuyển động |
| Relay đèn | IN | GPIO7 | HIGH bật, LOW tắt theo code |
| Driver quạt | IN1 / IN2 | GPIO1 / GPIO2 | PWM trên IN1; IN2 LOW |

## Nguồn và mức tín hiệu

- GPIO ESP32-C3 dùng mức logic 3,3 V. Kiểm tra mức AO/DO thực tế của module, đặc biệt
  module MQ-2 cấp 5 V; dùng mạch hạ mức phù hợp nếu tín hiệu vượt mức cho phép của GPIO.
- Servo, quạt và tải đèn cần nguồn/driver phù hợp; các chân trên bảng là chân tín hiệu,
  không phải chân cấp công suất. Không cấp nguồn động cơ trực tiếp từ GPIO.
- Chọn điện áp VCC theo module thực tế, nối chung GND cho nguồn và tín hiệu liên quan.
  Kiểm tra relay active-HIGH/LOW và mức DO cảm biến trước khi kết nối tải.
- Trạng thái `window`, `light`, `fan` trên web là trạng thái điều khiển/telemetry;
  hệ thống chưa có cảm biến riêng xác nhận cửa đã mở hay đèn đã sáng.

## Tài liệu tham khảo cũ

[Excel gốc](hardware/reference/sodochan-original.xlsx) và
[CSV gốc](hardware/reference/sodochan-original.csv) được giữ nguyên nội dung để đối chiếu.
Hai bản này ghi servo bếp GPIO3, relay GPIO4 và chưa có buzzer GPIO5: **không còn khớp
firmware bếp hiện tại**. Bảng ở trang này và `pinout.csv` mới là bản đang dùng.
