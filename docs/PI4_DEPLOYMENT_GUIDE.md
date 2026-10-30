# Hướng dẫn Triển khai & Nghiệm thu Gateway Raspberry Pi 4 (4GB RAM)

## 1. Thông số Hệ thống Khuyến nghị

* **Phần cứng:** Raspberry Pi 4 Model B, RAM 4 GB.
* **Hệ điều hành khuyến nghị:** Raspberry Pi OS (Debian 12 Bookworm hoặc Debian 11 Bullseye) **64-bit (`aarch64`)**.
  > *Lưu ý quan trọng:* Bản 32-bit (`armv7l`) thiếu wheel nhị phân chính thức cho nhiều thư viện AI (như MediaPipe), đồng thời hiệu năng Bluetooth D-Bus và xử lý số học 64-bit kém hơn đáng kể.
* **Nguồn điện & Tản nhiệt:** Nguồn chính hãng 5.1V / 3A Type-C; vỏ nhôm tản nhiệt hoặc quạt chủ động. CPU không được vượt quá 80°C để tránh hiện tượng throttling (giảm xung).

---

## 2. Kiểm tra Preflight chẩn đoán (Read-Only)

Trước khi cấu hình hoặc khởi chạy dịch vụ, chạy script chẩn đoán an toàn:
```bash
python3 scripts/pi_preflight.py
# Hoặc xuất định dạng JSON máy đọc:
python3 scripts/pi_preflight.py --json
```
Script sẽ kiểm tra:
* Kiến trúc OS/kernel (xác nhận 64-bit).
* Phiên bản Python và virtualenv.
* Bộ điều khiển Bluetooth & socket `/var/run/dbus/system_bus_socket`.
* Nhiệt độ CPU, RAM khả dụng, trạng thái throttling.
* Bảng kiểm tra các gói phụ thuộc `requirements.txt`.
* Cấu hình an toàn đã che mặt nạ (masked secrets).

---

## 3. Cài đặt Phụ thuộc & Quản lý Wheel ARM

Tạo môi trường ảo cách ly:
```bash
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip setuptools wheel
```

### Xử lý các gói phụ thuộc trên kiến trúc ARM:
1. **OpenCV:**
   * Nên dùng bản không giao diện: `pip install opencv-python-headless` để tránh kéo theo các phụ thuộc GUI/X11 nặng nề.
2. **MediaPipe:**
   * MediaPipe cung cấp wheel cho Linux `aarch64`. Trong trường hợp chạy trên hệ thống không có binary wheel tương thích, hệ thống gateway được thiết kế cho phép chạy backend + BLE độc lập:
     ```bash
     export CAMERA_MODE_DEFAULT=off
     export ENABLE_TRACKING=0
     ```
   * Khi tắt camera/AI, toàn bộ luồng BLE 3 node và web dashboard vẫn hoạt động bình thường với mức chiếm dụng RAM dưới 150 MB và CPU dưới 5%.
3. **Bleak (Bluetooth Low Energy):**
   * Đảm bảo người dùng chạy dịch vụ thuộc nhóm `bluetooth`:
     ```bash
     sudo usermod -aG bluetooth $USER
     ```
   * Dịch vụ `bluetooth.service` và `dbus.service` phải đang chạy.

---

## 4. Quản lý Dịch vụ Systemd

Cài đặt service template từ repository:
```bash
sudo cp aiot-care.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable aiot-care.service
sudo systemctl start aiot-care.service
```

Kiểm tra trạng thái & log:
```bash
sudo systemctl status aiot-care.service
journalctl -u aiot-care.service -f
```

Đặc điểm an toàn của service:
* Chỉ chạy một tiến trình duy nhất (`app.py` thiết lập `use_reloader=False` rõ ràng cùng `FLASK_DEBUG=0` trong unit file, tránh hiện tượng reloader spawn tiến trình con gây xung đột cổng Socket.IO và tạo hai luồng BLE quét trùng lặp).
* Khởi động theo thứ tự: `After=network.target bluetooth.target dbus.service` chỉ định thứ tự kích hoạt tiến trình theo systemd, KHÔNG đồng nghĩa adapter Bluetooth HCI phần cứng đã sẵn sàng tại thời điểm app khởi chạy. Gateway được thiết kế với cơ chế catch-up và reconnect có bounded backoff để tự phục hồi khi adapter bật sau.
* Giới hạn tần suất khởi động lại: cấu hình `StartLimitIntervalSec=60s` và `StartLimitBurst=5` kết hợp `Restart=on-failure`, `RestartSec=5s` nhằm ngăn chặn triệt để vòng lặp restart storm (tối đa 5 lần trong 60 giây).
