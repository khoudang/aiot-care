# Phase 2: trạng thái số đo và kiểm tra AI có đối chứng

Tiếp nối commit `b12e9e4` trên Pi thật. **Không sửa hoặc nạp firmware, không thay cực tính/logic cảm biến lửa** trong đợt này.

## Đã kiểm tra và bổ sung

### Phân biệt liên kết BLE với dữ liệu cảm biến mới

- API `/api/state` có thêm `telemetry` cho mỗi phòng: trạng thái `offline`, `awaiting`, `fresh`, `partial`, `stale`; tuổi mẫu và trạng thái riêng từng trường cảm biến.
- Dùng clock monotonic. Mẫu ở timestamp 0 vẫn hợp lệ. Kiểm tra kiểu dữ liệu và loại bỏ NaN/Infinity khỏi việc làm mới dấu thời gian; ADC khí phải thuộc 0–4095.
- ACK, trạng thái relay/còi/cửa và frame phase/event_id không được coi là mẫu cảm biến mới. Nếu PIR còn cập nhật nhưng nhiệt độ/độ ẩm thiếu hoặc cũ, hiển thị `partial` thay vì coi tất cả số đo đều mới.
- Ngưỡng cấu hình: `TELEMETRY_STALE_SEC`, tương thích biến cũ `NODE_STALE_SEC`, mặc định 10 giây; trên Pi hiện tại đọc được **12 giây** từ cấu hình đã có. UI dùng lại chu kỳ đọc API 3 giây hiện có, không thêm vòng polling bằng model hoặc thread quét BLE.
- Đây là **giám sát/hiển thị độ mới**, không phải chính sách tự can thiệp khi stale. Không sửa NODE_ONLINE, phase bếp, latch an toàn hoặc hàng đợi lệnh chỉ vì dữ liệu cũ.
- Giao diện có nhãn riêng ở từng phòng. Không suy ra node mất nguồn từ BLE offline; không hạ badge cảnh báo nguy hiểm đã biết khi hiển thị stale; nhãn số liên kết không được hiểu là số trường cảm biến còn mới.

### Kiểm tra phần mềm

- **71 Python tests trên Pi: OK**, thời gian 31.538 giây; không failure/error/skip trong lượt này. Bao gồm test độ mới, các test bảo vệ bếp và interlock AI chỉ quan sát từ bản trước.
- Node syntax check và harness chạy hàm renderer cùng handler socket thật: giữ cảnh báo nguy hiểm, báo stale/partial, không để cache fresh/offline ghi đè sự kiện disconnect/reconnect mới, không xóa cảnh báo khí khi phục hồi fresh. Ba regression socket đã fail trước sửa và pass sau sửa; log: [verification/pi4-phase2-ui-tests.txt](verification/pi4-phase2-ui-tests.txt).
- Log test: [verification/pi4-phase2-unit-tests.txt](verification/pi4-phase2-unit-tests.txt).

## BLE bếp: khoanh vùng thêm, chưa tuyên bố sửa xong

Đã tạm dừng app (camera/AI cũng dừng), ngắt có chọn lọc các liên kết AIoT đang giữ, rồi quét độc lập bằng Bleak trên Pi trong 20 giây:

- Node người bệnh: 253 callback quảng bá, RSSI từ −46 đến −35 dBm.
- Node phòng khách: 176 callback, RSSI từ −95 đến −82 dBm.
- Node bếp: không có quảng bá mới trong cửa sổ đo đó.

App được khởi động lại ở khối finally. Phép thử này không đủ để kết luận ESP tắt, và không chứng minh mọi nguyên nhân nằm ở RF. Tuy nhiên, lần không thấy bếp này vẫn xảy ra khi camera/AI và các kết nối app khác đã dừng, nên không thể mặc định quy cho tải AI hoặc giới hạn ba kết nối đồng thời. Laptop đã kết nối/nhận dữ liệu bếp ở các lượt riêng trước đó. Bước phân biệt tiếp theo cần so sánh vị trí/đường truyền ngay tại Pi; chưa tự thay giao thức hoặc mua phần cứng.

## AI: smoke test bằng ảnh kiểm thử chính thức, không phải accuracy thực tế

Chạy MediaPipe Hands hiện có và hàm detect_gesture của dự án trên các asset của MediaPipe, cả ảnh gốc và ảnh lật ngang:

- Bốn cử chỉ chính `fist`, `one`, `two`, `open`: **8/8 trường hợp đối chứng** nhận đúng trong tập nhỏ này.
- Ảnh mèo là đối chứng âm: **2/2** không trả cử chỉ.
- Cử chỉ mở rộng `thumbs_up`: **0/2** đúng; một ảnh không nhận được, ảnh lật bị nhận thành `three`. Chưa sửa heuristic hay hạ confidence chỉ để ép fixture xanh.
- Tổng: **10/12 trường hợp**, không diễn giải thành độ chính xác sử dụng thực tế. Chưa đánh giá video, nhiều người, ánh sáng khác nhau, che khuất hoặc phát hiện té ngã bằng tập có nhãn.
- Không gửi lệnh thiết bị trong phép thử. AI trên gateway giữ chế độ chỉ quan sát; không tự bật tính năng điều khiển AI dựa trên kết quả smoke test.

Nguồn kiểm thử: `https://storage.googleapis.com/mediapipe-assets/` với các file `fist.jpg`, `pointing_up.jpg`, `victory.jpg`, `thumb_up.jpg`, `cat.jpg`, `right_hands.jpg`. Ảnh open dùng nửa phải của right_hands.jpg, chứa một bàn tay mở thẳng đứng đã quan sát; giữ tỉ lệ và thu về tối đa 320 pixel. Asset chỉ cache riêng trong evidence trên Pi, không phân phối lại trong Git. Danh mục asset được đối chiếu với BUILD của MediaPipe: https://github.com/google-ai-edge/mediapipe/blob/a1ff14c8/mediapipe/tasks/testdata/vision/BUILD.

## Còn chờ

1. Kết nối bếp ổn định và nghiệm thu ba node đồng thời ở vị trí lắp thật.
2. Cảm biến lửa: tạm hoãn theo yêu cầu; trạng thái bình thường không phải chứng nhận an toàn.
3. UART/servo tracking: chưa xác minh dây/cơ khí, UART vẫn tắt trong cấu hình triển khai.
4. Video có nhãn để đánh giá cử chỉ/té ngã và hiệu chỉnh nếu cần; thumbs_up mở rộng chưa đạt.
5. Nghiệm thu tải thật và tình huống an toàn chỉ sau khi đầu vào đã được xác minh, không tạo rò gas/cháy thật.
