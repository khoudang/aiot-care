# Thử nghiệm tăng tốc và làm mượt camera trên Pi

## Thay đổi

- Tách nhịp điều khiển servo khỏi nhịp nhận diện YOLO: vòng điều khiển chạy mỗi 90 ms.
- Tăng giới hạn tốc độ bám người từ 6 lên 12 độ/giây, có giới hạn gia tốc và hãm khi gần góc đích.
- Mỗi kết quả nhận diện mới chỉ tạo một góc đích, tối đa 6 độ hiệu chỉnh. Không cộng lặp sai số từ ảnh cũ.
- Góc đích hết hạn sau 1 giây tính từ thời điểm chụp ảnh; kết quả âm tính thực sự hủy lệnh bám đang chờ.
- Dừng gửi lệnh khi camera tắt, phiên camera thay đổi, tracking bị tắt hoặc ở chế độ chỉ quan sát. Không tự đưa servo về giữa lúc khởi động.
- Giữ nguyên nhịp YOLO cấu hình trên Pi là 0,5 giây, logic cử chỉ và té ngã.
- Giữ chính sách không thấy người 5 giây thì về giữa 90 độ; tốc độ về giữa vẫn tối đa 6 độ/giây.
- Kèm phần hiển thị nhãn cử chỉ tiếng Việt bằng Pillow đã có trong bản triển khai nguồn, để mã trên Git đầy đủ và khớp bản Pi. Bổ sung phụ thuộc Pillow.

## Kiểm chứng

Bản thử trên Pi vượt qua 53 bài kiểm tra và 12 kiểm tra con cho chuyển động, vòng điều khiển, tracking, về giữa, quyền riêng tư, vòng đời camera và nhãn tiếng Việt. Kiểm tra dùng phần cứng/UART giả, không điều khiển servo thật để chạy test.

Sau khi triển khai: dịch vụ hoạt động, API giữ camera bật và chế độ điều khiển AI hiện có, tracking YOLO không báo lỗi, luồng MJPEG trả về ảnh JPEG, UART mở `/dev/serial0` ở 115200 baud, SQLite kiểm tra toàn vẹn trả về `ok`.

## Giới hạn

- Đây là tốc độ giới hạn của lệnh phần mềm, không phải tốc độ cơ khí đã đo.
- UART vẫn dùng góc nguyên dạng `Axxx\n`, nên không phải mỗi nhịp 90 ms đều tạo một vị trí nguyên khác nhau.
- Độ mượt thực tế cần người dùng quan sát khi đi ngang trước camera; nguồn cấp, cơ khí và firmware ESP32 vẫn có thể gây khựng.
- Không đưa `.env`, mật khẩu, khóa phiên hay cơ sở dữ liệu lên Git.
