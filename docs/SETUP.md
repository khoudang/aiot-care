# Cài đặt và vận hành

[Về README](../README.md) · [Phần cứng](HARDWARE.md)

## Môi trường Python

Chạy lệnh từ thư mục gốc repo. Có thể dùng môi trường hiện có nếu ứng dụng đang chạy tốt.
Nếu cài máy mới:

```bash
python -m venv .venv
```

Kích hoạt bằng `.venv\Scripts\Activate.ps1` trên PowerShell hoặc
`source .venv/bin/activate` trên Linux, sau đó:

```bash
python -m pip install -r requirements.txt
```

Repo chưa khóa phiên bản dependency/Python. Khả năng cài OpenCV và MediaPipe phụ
thuộc hệ điều hành, kiến trúc và phiên bản Python; giữ môi trường đang hoạt động
trước khi thử nâng cấp trên Pi.

## Cấu hình

`config.py` đọc biến môi trường và `.env` qua python-dotenv. Tạo `.env` cục bộ,
không đưa key, mật khẩu hoặc token thật lên Git.

| Biến | Ý nghĩa |
| --- | --- |
| `SECRET_KEY` | Khóa phiên riêng của máy triển khai; giữ ổn định giữa các lần chạy |
| `DATABASE` | Đường dẫn SQLite, mặc định `smart_home.db` |
| `BLE_MAC_PATIENT`, `BLE_MAC_LIVING`, `BLE_MAC_KITCHEN` | MAC đọc từ từng node thật |
| `UART_ENABLE` | `1` bật UART servo, `0` tắt |
| `UART_PORT`, `UART_BAUD` | Cổng serial thực tế và baud; mặc định `/dev/ttyUSB0`, `115200` |
| `CAMERA_MODE_DEFAULT` | `auto`, `on` hoặc `off` |
| `VIDEO_SOURCE` | Chỉ số camera OpenCV, mặc định `0` |
| `ALLOW_REGISTER` | `1` cho đăng ký, `0` tắt đăng ký |
| `ADMIN_REGISTER_CODE` | Mã đăng ký khởi tạo khi cấu hình DB chưa tồn tại |
| `GEMINI_API_KEY` | Key cho trợ lý AI, xem [CHATBOT.md](CHATBOT.md) |

Các UUID và lựa chọn nâng cao nằm trong [config.py](../config.py).
Ứng dụng seed tài khoản mẫu từ `INITIAL_USERS` khi tài khoản tương ứng chưa tồn tại.
Đăng nhập tài khoản quản trị đã cấu hình; thay mật khẩu mẫu và mã đăng ký trước khi
chia sẻ link Internet. Cấu hình đăng ký/Telegram đã lưu trong DB được quản lý qua
trang quản trị, không mặc nhiên bị ghi đè khi thay `.env`.

## Thử bếp trên Windows

```powershell
python run_kitchen_test.py
```

Mở `http://127.0.0.1:5000/dashboard`. Script dùng BLE thật, chỉ chọn node `kitchen`,
dùng `kitchen-test.db`, tắt UART, đặt camera `off`, tắt tự ingest RAG.
Script tạo khóa phiên mới mỗi lần chạy nên cần đăng nhập lại sau khi khởi động lại.
Địa chỉ loopback chỉ truy cập được ngay trên laptop; dùng ngrok cho máy bên ngoài.

## Ngrok trên laptop

Cài theo [hướng dẫn Windows chính thức](https://ngrok.com/download/windows).
Lần đầu, đăng nhập tài khoản ngrok rồi chạy lệnh thêm authtoken trên máy của bạn:

```powershell
ngrok config add-authtoken YOUR_AUTHTOKEN
```

Khi web cổng 5000 đã chạy, mở terminal thứ hai:

```powershell
ngrok http 5000 --inspect=false
```

Mở URL HTTPS ở dòng Forwarding, thêm `/dashboard` nếu cần. Bấm Visit Site nếu
ngrok hiển thị trang trung gian, rồi đăng nhập ứng dụng. Tắt Wi-Fi điện thoại và
dùng 4G/5G để thử khác mạng. Giữ web và ngrok chạy; Ctrl+C tại terminal ngrok để dừng.
Không đưa authtoken hay cấu hình ngrok cá nhân vào repo. Hạn mức miễn phí có thể đổi,
xem [tài liệu ngrok](https://ngrok.com/docs/pricing-limits/free-plan-limits).

## Raspberry Pi

Sau khi cài dependency, kiểm tra Bluetooth, MAC từng node, camera và quyền truy cập
cổng serial của tài khoản chạy ứng dụng. Chạy:

```bash
python app.py
```

Mở `http://<IP-của-Pi>:5000/dashboard`. Entry point này khởi tạo cả BLE, camera,
chatbot và database; không phải máy chủ giao diện độc lập. Không import `app.py`
chỉ để kiểm tra tài liệu hoặc quét route.

### Tự chạy với systemd

File [aiot-care.service](../aiot-care.service) hiện dùng user `khoi`, đường dẫn
`/home/khoi/aiot-care` và môi trường `venv311`. Chỉnh `User`, `WorkingDirectory`,
`ExecStart` và `Environment=PATH` đúng máy trước khi cài; nếu tạo `.venv` theo hướng
dẫn trên thì sửa đường dẫn môi trường tương ứng.

```bash
sudo cp aiot-care.service /etc/systemd/system/aiot-care.service
sudo systemctl daemon-reload
sudo systemctl enable --now aiot-care
sudo systemctl status aiot-care
journalctl -u aiot-care -n 100 --no-pager
```

Ngrok là tiến trình riêng; service này chỉ khởi động ứng dụng AIoT Care.
`update.sh` thực hiện git pull, ingest tài liệu và restart service: đọc trước khi
chạy, không dùng trong lúc có thay đổi cục bộ chưa được lưu.

## Khi chưa thấy dữ liệu

| Hiện tượng | Kiểm tra |
| --- | --- |
| Web mở nhưng node offline | Nguồn node, Bluetooth gateway, MAC và UUID đúng firmware |
| Đèn/còi chưa đổi trạng thái | Trạng thái kết nối, thông báo lệnh, chế độ khẩn cấp, GPIO và active-HIGH/LOW |
| Link ngrok không vào được | Web local cổng 5000, tiến trình ngrok, Internet và laptop có sleep không |
| Khởi động báo cổng 5000 đã dùng | Một bản web khác đang chạy; không khởi động thêm bản thứ hai |
| UART không quay servo | Port thực, baud 115200, TX nối RX GPIO20 và GND chung |
