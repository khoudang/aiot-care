# MP-2 DO – checklist trước khi kích hoạt (ESP32-C3 kitchen)

**Trạng thái:** firmware có hỗ trợ đọc DO nhưng tắt mặc định. Chưa có bằng chứng thử trên board thật.

## 1. Kiểm tra phần cứng

- [ ] Xác nhận module đang dùng là **MP-2** cấp nguồn 5 V, không phải MQ-2.
- [ ] Ngắt kết nối DO 5 V trực tiếp khỏi ESP32-C3 GPIO1 ngay cả khi macro đang tắt.
- [ ] Lắp bộ chuyển mức / phân áp đúng điện áp, dùng chung GND; **đo điện áp thực tế ở GPIO1, bảo đảm không vượt 3,3 V**.
- [ ] Dùng đồng hồ đo kiểm mức HIGH và LOW ở GPIO1 khi module comparator chuyển trạng thái.
- [ ] Xác nhận DO có thực sự active LOW; nếu không, sửa chính xác cực tính trong code trước khi bật.
- [ ] Kiểm tra điều kiện bình thường và cảnh báo so ngưỡng; núm chỉnh comparator trên module quyết định ngưỡng DO, **không** dùng ngưỡng DO thay ngưỡng ADC 1500/2500.
- [ ] Không dùng khí dễ cháy, khói cháy, hoặc nguồn lửa gần relay, mô-tơ, board để kiểm thử.

## 2. Kích hoạt có kiểm soát

Sau khi tất cả bước điện áp/cực tính được xác nhận, biên dịch firmware với macro:

```cpp
#define MP2_DO_SAFE_WIRING_VERIFIED 1
```

Đặt định nghĩa này trước phần khai báo mặc định trong `kitchen_node.ino` hoặc truyền cờ build tương đương. **Không dùng trong khi GPIO1 vẫn nhận mức 5 V.**

## 3. Kiểm thử phần mềm và an toàn

- [ ] Ở chế độ mặc định, BLE có `mp2_do_enabled:false`, `mp2_do_alarm:false` và giao diện hiện **Chưa kích hoạt**.
- [ ] Khi bật với DO LOW: `mp2_do_enabled:true`, `mp2_do_alarm:true`, alias `smoke:true`; ESP32 chuyển `EMERGENCY`.
- [ ] Gas ADC vẫn là 0–4095; DO không đổi đơn vị thành ppm.
- [ ] DO HIGH và ADC dưới 1500, flame=false liên tục >=10 giây: chuyển `WAIT_CONFIRM` và không tự khôi phục.
- [ ] DO LOW khi `WAIT_CONFIRM`: cấm `confirm_safe`; khi DO HIGH, `event_id` hợp lệ mới có thể xác nhận.
- [ ] Mất BLE, mẫu telemetry cũ, hoặc sai `event_id`: không tự giải khóa.
- [ ] Kiểm tra còi, quạt, cửa sổ, relay dưới điều kiện **mô phỏng tín hiệu điện an toàn**, không phun khí cháy.
- [ ] Chạy `python -m unittest discover -s tests -p test_firmware_logic.py` và bộ test kitchen trước khi nạp lên thiết bị.

## 4. Giới hạn công bố

MP-2 DO là tín hiệu comparator theo khí / hơi nhạy cảm với module, **không là đầu báo khói quang học chuyên dụng**.
Ngưỡng ADC vẫn là ngưỡng thử nghiệm chưa được hiệu chuẩn cho mục đích bảo vệ tính mạng.
Hệ thống nghiên cứu này không thay thế thiết bị báo cháy / báo gas đạt chuẩn.
