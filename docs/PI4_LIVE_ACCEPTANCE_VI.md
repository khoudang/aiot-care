# Nghiệm thu trực tiếp Raspberry Pi 4 — bản triển khai BLE/AI

## Trạng thái bàn giao

**Đã triển khai và chạy trên Pi thật; chưa nghiệm thu hoàn chỉnh ba node đồng thời.**

- Máy thử: Raspberry Pi 4 Model B Rev 1.5, RAM 4 GB, Debian 13 aarch64.
- Dùng lại Python 3.11.9 / MediaPipe 0.10.14 đang tương thích. Không nâng cấp gói hệ thống hay thay interpreter của ứng dụng khác.
- Release riêng: `/home/khoi/aiot-care-releases/ble-pi4-20261030`.
- Dữ liệu riêng: `/home/khoi/aiot-care-data/smart_home.db`; giữ bốn tài khoản hiện có, không reset mật khẩu người dùng.
- Bản sao lưu service, drop-in, cấu hình riêng và SQLite nằm tại `/home/khoi/aiot-care-evidence/20261030-181946`. Không đưa credential hoặc nội dung `.env` lên Git.

## Các sửa đổi có bằng chứng thực tế

1. Đối chiếu tên quảng bá để sửa MAC từng phòng, không lấy thứ tự/địa chỉ mặc định trong code làm bằng chứng danh tính thiết bị. Cấu hình đã được đọc lại qua API quản trị.
2. Phát hiện drop-in `desktop.conf` ghi đè unit chính, khiến đổi unit nhưng vẫn chạy app cũ. Thêm override riêng và kiểm tra cả WorkingDirectory lẫn ExecStart hiệu lực.
3. Phát hiện BlueZ còn giữ kết nối node người bệnh/phòng khách trong khi ứng dụng báo disconnected; node đã connected không phát quảng bá mới nên vòng discovery không tìm thấy. Ngắt có chọn lọc hai liên kết này đã làm hai node xuất hiện lại và gateway nhận telemetry. Không suy ra node mất nguồn từ trạng thái offline của gateway.
4. Bổ sung các lệnh `ExecStartPre` trong drop-in của riêng Pi này: `-/usr/bin/bluetoothctl --timeout 5 disconnect <MAC đã xác minh>` cho ba địa chỉ cấu hình trước khi app mới chạy. Không tắt/reset adapter, không xóa pairing, không đụng thiết bị Bluetooth khác. Đây là chính sách một gateway sở hữu các node AIoT; không áp dụng nguyên xi khi nhiều ứng dụng cùng cần các liên kết đó.
5. Sửa `CAMERA_MODE_DEFAULT=on`: khởi động camera một lần khi dịch vụ bắt đầu; giữ nguyên hành vi auto/off. Trước sửa, cấu hình on không tự bắt đầu camera.
6. Thêm `AI_OBSERVE_ONLY=1`: vẫn suy luận Pose/Hands/tracking và hiển thị kết quả, nhưng không phát lệnh AI xuống BLE/UART hoặc gửi Telegram do AI. Nghi ngờ té ngã dùng `fall_suspected`, tách khỏi `fall` đang được các nhánh an toàn/reconnect sử dụng; tránh bật còi gián tiếp. Lệnh thủ công và bảo vệ bếp độc lập không bị vô hiệu hóa.
7. Thêm nhãn chế độ quan sát trên Dashboard. Không gọi kết quả âm tính của heuristic là chứng nhận "an toàn".
8. Sửa teardown test bất đồng bộ bị treo trên Python 3.11: dừng vòng gửi bằng cờ/event và chờ có timeout thay vì chỉ cancel task lúc wait_for đang hoàn tất.

## Kiểm thử trên Pi

**68 tests, 0 failure/error, không skipped**, thời gian 21.984 giây. Log: [verification/pi4-unit-tests.txt](verification/pi4-unit-tests.txt). Suite dùng fake transport cho các ca phần mềm và có kiểm tra logic C++ trên host; tách biệt với các phép đo BLE/camera thật dưới đây.

### Phản hồi BLE thật

Đây là số mẫu nhỏ, không phải bảo đảm SLA hoặc độ tin cậy dài hạn:

- Người bệnh: ba lệnh giữ nguyên trạng thái đèn, ACK applied sau 73.10 / 90.22 / 157.06 ms tính từ enqueue trên gateway; trung vị 90.22 ms.
- Phòng khách: ba lệnh giữ nguyên chính sách Auto hoặc trạng thái hiện tại, ACK applied sau 69.86 / 133.93 / 100.37 ms; trung vị 100.37 ms. Không đổi Auto sang Manual chỉ để thử đèn.
- Bếp: một ACK applied sau 214.04 ms; hai lệnh tiếp theo không có bằng chứng hoàn tất ở thời điểm ghi (một canceled, một còn enqueued). Kết nối bếp chưa ổn định, không ghi kết quả 3/3 hoặc đạt.
- Lượt cuối sau phục hồi BlueZ, camera/AI và hai kết nối người bệnh/phòng khách cùng hoạt động; một lệnh người bệnh có ACK applied sau 102.76 ms trong lúc AI chạy. Node bếp chưa ready ở lần kiểm tra này.
- ACK chỉ chứng minh chấp thuận logic, không chứng minh tải/cơ cấu vật lý hoạt động. Không kích thử gas, không thử nguy hiểm thật, không gửi lệnh mute/khôi phục an toàn trong lượt đo này.

### Camera và AI thật

- Camera USB: 320×240, đọc 60 frame, không lỗi đọc; Pose có landmark ở 58 frame. Hands đã chạy nhưng không có bàn tay được phát hiện trong mẫu đó.
- Benchmark riêng gồm cả khởi tạo model: 6.25 FPS; median xử lý frame 117.79 ms. Đây không phải độ chính xác nhận diện.
- Trong gateway chạy thật đồng thời BLE: khoảng 6.7 FPS ở cuối phép đo; RSS 283.5 MiB, CPU khoảng 99% theo thang một lõi; nhiệt độ 62.809°C ở mẫu tài nguyên. Thời điểm kiểm tra throttling: `0x0`.
- MJPEG có JPEG hợp lệ khi xác thực; truy cập video không xác thực bị chuyển về đăng nhập (302).
- Không lưu ảnh/video từ camera. Chưa có bộ video gán nhãn nên chưa tính accuracy, precision, recall hoặc F1 cho cử chỉ/té ngã.

## Dọn dẹp an toàn

Đã xóa và kiểm tra lại **518 file**, tổng dung lượng logic **150,391,532 byte (143.42 MiB)**, chỉ gồm object `.o` CPython có thể build lại và bản nén nguồn trùng byte nếu có. Giữ nguyên source, Python đã cài, virtualenv, thư viện dùng chung, mô hình AI, video, cấu hình, database và các bản rollback. Không tuyên bố thao tác dọn đĩa làm giảm RAM.

## Cấu hình hiện tại và giới hạn

- Camera bật; `AI_OBSERVE_ONLY=1` có nhãn trên giao diện. `UART_ENABLE=0` vì chưa xác minh đấu UART/servo thật; góc tracking trên giao diện không phải bằng chứng servo đã quay.
- Chưa xác minh cảm biến lửa SY-M213: phép thử riêng ghi DO luôn LOW và AO 4095; bản đảo mức do người dùng nạp chưa phải sửa/hiệu chuẩn cảm biến. Không dùng trạng thái bếp bình thường để chứng nhận không có lửa.
- Chưa hoàn tất nghiệm thu ba node online đồng thời, mất BLE/Pi, tải/cơ cấu thật hoặc độ chính xác AI. Không suy ra ESP đã tắt chỉ vì gateway offline.
- Watchdog stale telemetry của code nền vẫn chưa triển khai; ready chứng minh subscribe notify, không tự chứng minh số đo còn mới.
- Không mở tunnel/port Internet mới, không thay mật khẩu SSH, không gọi thêm API LLM trả phí. Cần đổi mật khẩu SSH yếu và chuyển sang key trước khi sử dụng ngoài môi trường thử.

## Khôi phục

Dừng service, giữ một bản sao drop-in mới rồi bỏ riêng `zz-aiot-release.conf` khỏi thư mục drop-in, phục hồi unit từ `aiot-care.service.before`, daemon-reload và khởi động lại. Các checkout và database gốc vẫn còn nguyên. Không dùng git reset --hard hoặc xóa các thư mục gốc để rollback.
