# Bàn giao nhánh BLE / Raspberry Pi 4

Nhánh: `feature/ble-pi4-readiness`. Không merge `main`, không flash firmware hoặc kích hoạt tải thật trong đợt này.

## Đã thay đổi

- Phối hợp discovery BLE dùng chung cache, kể cả kết quả chưa thấy thiết bị; tránh các node thiếu MAC lần lượt khởi động quét trùng. Giữ BLEDevice đang kết nối bằng trạng thái do ứng dụng sở hữu; manual scan có giới hạn tần suất.
- Phân biệt disconnected / connecting / subscribing / ready. `ready` là đăng ký notify thành công, không chứng minh telemetry còn mới.
- Đánh thức bộ gửi bằng event, bổ sung phản hồi ACK và telemetry đầu ra sớm trong firmware. ACK `busy` retry có backoff giới hạn; giữ ID và thứ tự lệnh. ACK `applied` là chấp thuận logic, không chứng minh cơ cấu vật lý hoàn tất.
- Trace tối đa 200 lệnh, dọn trace bị hủy, snapshot dưới lock. Chỉ ACK đúng ID được tính cho lệnh; không gán telemetry bất kỳ thành bằng chứng thực thi. RTT tính từ bắt đầu ghi GATT, tránh số âm khi ACK đến trước lúc hàm ghi trả về. ACK busy không được tính là hoàn tất; giữ trace qua lỗi ghi tạm thời để theo dõi retry.
- Endpoint trace chỉ dành cho admin; cập nhật hiển thị trạng thái và tài liệu liên quan.
- Thêm `scripts/pi_preflight.py`, hướng dẫn triển khai Pi 4, cấu hình systemd có giới hạn restart; tắt Flask reloader trong chế độ chạy service.
- Giữ số đo MP-2 là ADC thô và trạng thái chưa hiệu chuẩn; không tự quy đổi ADC tuyến tính thành ppm.

## Bằng chứng kiểm tra

- Lượt cuối trên host Windows: **62 tests, 0 failures, 0 errors, 0 skipped**; log gốc: [verification/ble-host-tests.txt](verification/ble-host-tests.txt).
- Lệnh: `uv run --no-project --python 3.12 --with flask --with flask-socketio python -m unittest discover -s tests -v` (lượt thực thi dùng runner Python tương đương để lưu log và số đếm JSON).
- Transport BLE và UART trong test là giả lập; các dòng kết nối trong log không phải kết nối radio thật. Flask test dùng cơ sở dữ liệu tạm, không server thật.
- Có biên dịch/chạy kiểm tra logic C++ trên host trong suite; không đồng nghĩa đã build toàn bộ firmware Arduino `.ino`.
- Bốn regression test biên của trace đã thất bại đúng nguyên nhân trước sửa, sau sửa nằm trong 62 test xanh: ACK đến sớm; busy không phải hoàn tất; giữ trace khi retry lỗi ghi; timestamp monotonic bằng 0.
- Review độc lập cho phần sửa trace cuối: passed, không phát hiện lỗi logic/bảo mật. Scan dòng mới không phát hiện literal secret, shell=True/os.system, eval/exec hoặc pickle. Đây không phải chứng nhận bảo mật toàn hệ thống.

## Chưa nghiệm thu / không cam kết

1. Chưa đo độ trễ radio, discovery và reconnect trên Raspberry Pi 4 + ba ESP32 thật. Không cam kết các ngưỡng mili-giây từ fake transport.
2. Chưa build toàn bộ firmware bằng Arduino/ESP-IDF target SDK, chưa flash thiết bị.
3. Watchdog stale telemetry **chưa triển khai**; không dùng trạng thái ready làm chứng cứ dữ liệu mới.
4. MP-2 chưa có hiệu chuẩn, kiểm chứng ngưỡng bằng khí chuẩn hoặc nghiệm thu cơ cấu tải thật. Không suy ra ppm hay mức an toàn thực tế từ test host.

Bước nghiệm thu kế tiếp: build firmware đúng board, chạy preflight trên Pi, thử riêng từng node rồi ba node đồng thời, đo ACK/discovery/reconnect và thử quy trình an toàn trong môi trường kiểm soát. Tham khảo [hướng dẫn Pi](PI4_DEPLOYMENT_GUIDE.md), [hợp đồng BLE](BLE_RELIABILITY_RELEASE.md) và [hiệu chuẩn MP-2](MP2_CALIBRATION_GUIDE.md).
