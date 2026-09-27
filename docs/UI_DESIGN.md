# Giao diện AIoT Care

Thiết kế tối giản, nền sáng trung tính và xanh ngọc cho trạng thái. Tổng quan chỉ
gồm trạng thái hệ thống và ba hàng thông tin phòng. Bỏ banner trang trí, thời tiết,
nhãn kết nối trùng lặp và widget vòng đeo. Trợ lý được mở từ menu bên trái. Các giá trị ban đầu chưa nhận dữ liệu hiển thị `--` hoặc
“Chưa có dữ liệu”. Kết nối máy chủ và kết nối node được hiển thị riêng.

## Tham khảo

- [Tabler](https://github.com/tabler/tabler): bố cục dashboard, khoảng trắng, thẻ dữ liệu.
- [CoreUI](https://github.com/coreui/coreui-free-bootstrap-admin-template): điều hướng bên trái, nhóm quản trị và trạng thái.

Các repo được dùng để tham khảo thiết kế. Không sao chép mã hoặc cài thêm framework.
Web tiếp tục dùng Flask/Jinja và Socket.IO hiện có. Font Awesome và Socket.IO vẫn
tải từ CDN như trước; cần truy cập mạng để tải hai tài nguyên này lần đầu.

## Cấu trúc

```text
templates/             Trang dashboard, đăng nhập, đăng ký (Jinja)
static/css/            Component, bố cục dashboard, giao diện xác thực
static/js/dashboard.js Điều hướng, cảm biến, điều khiển, chat, cảnh báo
static/js/admin.js     Giao diện quản trị, chỉ nạp với vai trò admin
static/js/auth.js      Hiện/ẩn mật khẩu
```

Tên API, sự kiện Socket.IO và payload điều khiển được giữ nguyên. Không thay đổi
pinout hay firmware. Hệ thống chỉ còn patient/living/kitchen; đã bỏ cấu hình BLE,
telemetry và cảnh báo của vòng đeo theo phạm vi phần cứng thực tế. Bộ kiểm tra
giao diện dùng máy chủ mô phỏng riêng; thao tác điều khiển không gửi đến thiết bị thật.

## Dọn repo

`KLTN_v0.2_cha/` là bản ứng dụng cũ độc lập gồm 20 tệp. Đã kiểm tra entrypoint,
service, script cập nhật và tham chiếu từ mã chính: ứng dụng hiện tại không sử dụng
thư mục này. 15 tệp trùng nội dung với bản ở gốc; 5 tệp còn lại là phiên bản cũ.
Toàn bộ bản cũ được sao lưu ra `_artifacts/` ở thư mục Projects trước khi bỏ khỏi repo.
Không xóa tài liệu y khoa, sơ đồ chân, database đang chạy, firmware hoặc test.

Đã bỏ tải Chart.js và đoạn khởi tạo biểu đồ gas không còn canvas trong giao diện.
Các sparkline cảm biến vẫn vẽ bằng Canvas gốc, không phụ thuộc Chart.js.

## Kiểm tra

Kiểm tra trên trình duyệt: cả admin/member, chuyển các phòng, cập nhật dữ liệu,
đèn và còi bếp qua Socket.IO giả lập, cảnh báo khẩn cấp/chờ xác nhận, mất kết nối,
menu điện thoại, khung chat, đăng nhập/đăng ký và hiện/ẩn mật khẩu.
Ảnh minh họa QA dùng dữ liệu mô phỏng, không phải số đo thực tế.

Chạy các kiểm thử backend với `python -m unittest discover -s tests -v`.
