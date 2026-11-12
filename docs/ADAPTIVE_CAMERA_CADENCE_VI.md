# Camera Auto: giữ camera mở, điều chỉnh nhịp xử lý

## Thay đổi hành vi

- `auto`: khởi động camera ngay khi dịch vụ nền chạy hoặc khi chọn Auto. Không đóng camera chỉ vì PIR không phát hiện chuyển động.
- `on`: giữ chế độ xử lý active; `off`: đóng camera như trước. PIR không được mở lại camera khi người dùng đã chọn Off.
- Sau khoảng không hoạt động, Auto chuyển sang idle **chỉ khi** telemetry motion của node patient còn mới và node đang online. Mất/stale PIR thì giữ active, không suy diễn rằng phòng trống.
- PIR có chuyển động, biến đổi hình ảnh, kết quả Hands dương tính hoặc nghi ngờ ngã làm mới thời điểm hoạt động. Khóa active trong chuỗi nghi ngờ ngã, cảnh báo/ngữ cảnh khôi phục còn hiệu lực. Cảnh báo không được vượt quyền Off.
- Dò thay đổi ảnh chỉ là phép so sánh ảnh xám thu nhỏ (chênh lệch ≥20 mức tại ≥2% điểm lấy mẫu), không phải mô hình nhận diện người. Nhiễu/ánh sáng hoặc pan có thể đánh thức active; chuyển động nhỏ có thể không đủ ngưỡng.

## Tham số `.env`

```dotenv
CAMERA_IDLE_AFTER_SEC=30
CAMERA_ACTIVE_VIDEO_FPS=15
CAMERA_IDLE_VIDEO_FPS=3
CAMERA_IDLE_AI_FPS=2
```

Đây là giới hạn lập lịch, **không phải FPS đo được hoặc cấu hình đã nghiệm thu trên Pi**. Active không bổ sung giới hạn AI: giữ cách xử lý theo khả năng phần cứng. Idle giới hạn toàn bộ lượt suy luận (Pose/Hands/YOLO), Hands vẫn theo stride và YOLO vẫn có cadence riêng. Nhịp thực tế có thể thấp hơn giới hạn, kể cả do khung mới được chuyển giao ở nhịp video.

`CAMERA_MOTION_TIMEOUT` là tham số cũ, không còn đóng camera trong Auto. Không cần thay pin, firmware, ngưỡng té ngã hoặc giao thức UART để dùng thay đổi này.

## Thu nhận, video và AI là ba việc khác nhau

Capture tiếp tục đọc/drain ảnh camera, kể cả trong idle, để hạn chế xử lý hàng đợi ảnh cũ ở thiết bị không tuân thủ cấu hình buffer/FPS. Nhịp chuyển giao khung/encode JPEG giảm xuống giới hạn video, và worker AI có giới hạn riêng **trước** các lời gọi mô hình. Không chỉ giảm số khung hiển thị ở trình duyệt. Không khẳng định giảm FPS cảm biến vật lý hoặc giảm điện năng camera.

`ai.camera_profile`, `camera_profile_reason`, `target_video_fps`, `target_ai_fps` trong trạng thái chẩn đoán phản ánh profile/lý do và giới hạn mục tiêu; `target_ai_fps=0` ở active nghĩa là không bổ sung cap, không phải tắt AI. Khi camera dừng, các giá trị mục tiêu được xóa về 0. Số đo `fps` và `video_fps` vẫn là số đo riêng, không lấy mục tiêu để giả làm kết quả.

## Tracking: tự về Home khi không thấy người

- Khi YOLO liên tục không phát hiện người trong ít nhất **5 giây**, pan bắt đầu trở về Home (`SERVO_CENTER`, mặc định 90°). Thời gian tính từ khung âm tính đầu tiên của phiên camera, không phải từ lúc boot.
- Về Home từng bước tối đa 3°/lần và ngân sách 6°/giây, không nhảy ngay về tâm; tới Home thì ngừng gửi. Phát hiện người trở lại sẽ hủy timeout và tiếp tục tracking.
- Một người khác còn trong ảnh cũng hủy timeout dù mục tiêu cũ bị mất. Lượt YOLO bị skip không tự tạo lệnh về Home.
- Chỉ tác động khi tracking bật, khung còn mới và phiên camera còn hợp lệ. Không về Home khi observe-only, lỗi/mất model hoặc camera tắt; timeout không mang sang phiên mới.
- Đã có regression mô phỏng worker/clock/UART trong `tests/test_tracking_home.py`; chưa nghiệm thu chuyển động servo vật lý. Mốc 5 giây là điều kiện bắt đầu, lệnh thực tế còn phụ thuộc nhịp khung và suy luận.

## Kiểm thử và ranh giới triển khai

Chạy test bằng hardware stubs, không import/chạy entrypoint `app.py`, không dùng camera/BLE/UART thật:

```bash
uv run --no-project --python 3.12 --with pytest --with numpy --with flask --with flask-socketio --with python-dotenv --with pyserial --with bleak python -m pytest tests -q
node --test tests/test_telemetry_ui.cjs tests/test_kitchen_buzzer_ui.cjs tests/test_gesture_ui.cjs tests/test_fall_confirmation_ui.cjs tests/test_admin_management_ui.cjs
```

Các regression mới kiểm tra: Auto không chờ PIR mới mở; Auto không dừng sau timeout cũ; idle thực sự giảm encode/lời gọi Pose; đọc capture vẫn tiếp tục; chuyển động ảnh đánh thức publisher thật; boot on/auto đúng một lần; Off được giữ; cảnh báo/PIR không khả dụng giữ active; tham số sai bị từ chối; cleanup không để lại mục tiêu FPS cũ. Bộ test hiện có kiểm tra phiên camera cũ, stop/restart, gesture và safety độc lập.

**Chưa triển khai Pi và chưa kiểm thử thiết bị vật lý.** Trước khi đổi release: lưu trạng thái runtime hiện tại và giữ `CAMERA_MODE_DEFAULT=off` nếu người dùng đang tắt camera; không vô tình bật camera/điều khiển cử chỉ qua restart. Giữ nguyên `AI_OBSERVE_ONLY`, không bật tải chỉ để thử FPS. Cần đo A/B CPU, nhiệt độ, FPS thực, độ trễ wake/cử chỉ, khả năng bắt sự kiện có nhãn và vận hành dài hạn. Không dùng số đo pipeline cũ ở `e573f03b8472b793c8246c7642e2dc327acdea90` để khẳng định hiệu năng YOLO hoặc cơ chế adaptive mới.
