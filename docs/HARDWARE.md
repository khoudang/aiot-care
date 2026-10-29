# Sơ đồ chân phần cứng

[Về README](../README.md) · [Firmware](../esp32_firmware/README.md) · [CSV](hardware/pinout.csv)

Bảng này được đối chiếu với hằng `PIN_*` của ba sketch hiện tại. **GPIO là số GPIO
trên ESP32-C3, không phải thứ tự chân vật lý trên board.** Kiểm tra nhãn in trên board.
Không sử dụng sơ đồ cũ trong thư mục `hardware/reference/` để đấu node bếp hiện tại.

## Phòng bếp — `kitchen` (đã xác nhận 29/10/2026)

Tên BLE: `AIoT_Kitchen_Node`. MAC thực tế cần kiểm tra qua Serial Monitor.

| Thiết bị | Tín hiệu | ESP32-C3 | Ghi chú |
| --- | --- | --- | --- |
| MP-2 (nguồn 5 V) | AO | GPIO0 | Qua R1=1 kΩ từ AO đến GPIO0, R2=1,5 kΩ từ GPIO0 xuống GND: V_GPIO0 ≈ 0,6×V_AO; ADC thô, không phải ppm |
| MP-2 | DO | GPIO1 | Có dây theo sơ đồ thực tế, **firmware không đọc**; phải ngắt dây hoặc hạ mức nếu DO có thể lên 5 V |
| Cảm biến lửa (nguồn 3,3 V) | AO | GPIO3 | Dây đã xác nhận; hiện chưa dùng để kích hoạt báo động |
| Cảm biến lửa (nguồn 3,3 V) | DO | GPIO6 | LOW = phát hiện lửa (phải kiểm thử mức logic thực tế) |
| Servo cửa sổ | Signal | GPIO4 | 0° đóng, 90° mở |
| Buzzer | Signal | GPIO5 | HIGH bật, LOW tắt |
| Driver quạt hút | IN1/PWM | GPIO7 | PWM 0–255 |
| Driver quạt hút | IN2 | GPIO8 | LOW |
| Relay đèn | IN | GPIO20 | HIGH bật theo firmware |

**Logic khí:** chỉ MP-2 AO tham gia xét mức (ADC 1500/2500 hiện là ngưỡng thử nghiệm *sau chia áp*, cần hiệu chuẩn lại). Cảm biến lửa kích hoạt theo DO. Các GPIO chỉ ghi kết nối thực tế; firmware chưa được nạp/kiểm chứng trên board. **Không dùng mô hình quạt thông thường làm giải pháp an toàn trong môi trường rò gas thật.**

## Phòng người bệnh — `patient` (đã xác nhận)

| Thiết bị | GPIO |
| --- | --- |
| SHT30/SHT31 SDA / SCL | GPIO3 / GPIO4 |
| PIR OUT | GPIO5 |
| Buzzer | GPIO0 |
| Servo camera | GPIO6 |
| Quạt IN1/PWM / IN2 | GPIO9 / GPIO10 |
| Relay đèn | GPIO8 |
| UART RX / TX | GPIO20 / GPIO21 |

UART từ gateway dùng 115200 baud, chuỗi góc ví dụ `A90\n`.

## Phòng khách — `living` (đã xác nhận)

| Thiết bị | GPIO | Ghi chú |
| --- | --- | --- |
| SHT30/SHT31 + BH1750 SDA/SCL | GPIO8 / GPIO9 | I²C chung |
| HLK-LD2420 OT2 | GPIO1 | Tín hiệu hiện diện chính, dùng trong firmware |
| HLK-LD2420 OT1 | GPIO0 | Có dây, không dùng trong tự động hóa |
| Dây radar khác, được báo là UART RX | GPIO2 | **Chưa xác minh tên/tác dụng, không dùng** |
| Relay đèn | GPIO7 | HIGH bật theo firmware |
| Quạt IN1/PWM / IN2 | GPIO5 / GPIO6 | PWM ở IN1 |

## Nguồn và mức tín hiệu

- GPIO ESP32-C3 dùng mức logic 3,3 V. Kiểm tra mức AO/DO thực tế của module, đặc biệt
  module MP-2 cấp 5 V; dùng mạch hạ mức phù hợp nếu tín hiệu vượt mức cho phép của GPIO.
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
