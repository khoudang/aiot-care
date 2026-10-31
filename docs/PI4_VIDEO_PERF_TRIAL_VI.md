# Pi 4: nghiệm thu thử pipeline video/AI

## Phiên bản thực chạy

- Source ứng dụng: `e573f03b8472b793c8246c7642e2dc327acdea90`, nhánh `feature/pi4-video-ai-perf`.
- Release Pi: `/home/khoi/aiot-care-releases/video-e573f03`.
- Đã đọc lại effective systemd WorkingDirectory/ExecStart, `/proc/<pid>/cwd`, Git HEAD và source sạch. PID 21742, NRestarts=0 tại các lượt kiểm tra.
- Dùng lại Python 3.11.9 trong `/home/khoi/aiot-care/venv311`; giữ SQLite dùng chung và 4 tài khoản. Giữ nguyên release cũ và backup riêng, không ghi credentials lên Git.

## Kết quả đo trước/sau

Cùng cấu hình 640×480, JPEG quality 85, Hands stride 3; không đổi model/runtime. Cả hai lượt đo dài khoảng 10 giây và cùng có 3 node kết nối tại hai đầu phép đo. Không thể bảo đảm cảnh camera/tư thế người hoàn toàn giống nhau; không dùng kết quả này để suy ra độ chính xác AI.

- Trước: 7.69 JPEG khác nhau/giây; 325 gói JPEG, trong đó 248 gói lặp ảnh liền trước.
- Sau: 15.15 JPEG khác nhau/giây; 152 gói JPEG, không có gói lặp ảnh liền trước trong lượt đo. Tốc độ ảnh mới phía server tăng 1.97 lần.
- Sau: khoảng cách ảnh mới median 67.74 ms, p95 71.90 ms. Đây là thời gian nhận JPEG ở Pi localhost, **không phải độ trễ camera→màn hình trình duyệt**.
- Snapshot AI ngay trước/sau cùng khoảng 7.5 FPS. Thời gian xử lý snapshot 115 ms trước và 93 ms sau, không phải benchmark phân phối suy luận. Các snapshot kiểm tra sau đó dao động 6.8–8.2 FPS và 92–233 ms: chưa chứng minh AI nhanh hơn đáng kể.
- Tách video và suy luận, dùng latest-frame, bỏ gửi lặp JPEG; `fps` vẫn là inference FPS và `video_fps` là nhịp xuất ảnh. Không lấy video FPS làm AI FPS.

## Kiểm tra đã thực thi

- Host: 93 unittest pass; 3 regression phiên camera, 1 regression action-after-stop và 2 regression lỗi phiên cũ đều pass.
- Pi thật: **93 tests / 40.619 giây / OK**. Đây vẫn là test logic có mock hardware, không phải 93 phép thử phần cứng.
- JS syntax và renderer harness thực: `SOCKET_REGRESSIONS=3 FAILURES=0`.
- API chưa đăng nhập bị chặn, API có phiên đăng nhập hoạt động. AI runtime/camera/stream thực đã chạy.
- Trong lượt đo sau triển khai, cả 3 node có sensor telemetry `fresh` ở đầu và cuối.
- Pi khoảng 75.0–77.4°C ở các lượt kiểm tra; `get_throttled=0x0`. Có cảnh báo nhiệt 78.4°C khi test đồng thời với app cũ; nên chú ý tản nhiệt.

## Giới hạn còn lại

- Living BLE có lúc mất kết nối/telemetry, log `failed to discover services, device disconnected`, dù BlueZ có lúc còn Connected=yes. Sau đó app tự nối lại. Lượt theo dõi bổ sung có 26 mẫu, kết thúc bằng 8 mẫu liên tiếp cả 3 node fresh. **Không gọi đây là đã chữa dứt điểm hoặc ổn định dài hạn.**
- Không thực hiện lệnh disconnect thủ công trong lượt theo dõi đó vì living đã tự online khi bắt đầu; không quy việc hồi phục cho thao tác của người kiểm tra.
- AI vẫn `AI_OBSERVE_ONLY=1`: chỉ quan sát, không tự điều khiển tải/gửi cảnh báo AI. Không thay firmware hoặc nghiệm thu cảm biến lửa SY-M213. Chưa có nghiệm thu accuracy té ngã/cử chỉ, thao tác tải vật lý hay độ mượt browser/LAN.
- Lượt này triển khai bằng Git bundle có SHA-256 xác nhận đọc lại, rồi đọc lại đúng Git commit trên Pi; sau đó nhánh GitHub đã được push và API xác nhận đúng source commit.

## Bằng chứng và quay lại bản trước

Bằng chứng riêng trên Pi: `/home/khoi/aiot-care-evidence/video-e573f03-20261031-105658/` chứa backup DB/config/service, stage manifest, log test, activation readback và JSON đo. Không đưa DB/config bí mật hoặc hình camera lên Git; các phép đo không lưu ảnh.

Override riêng của thử nghiệm: `/etc/systemd/system/aiot-care.service.d/zzz-video-perf.conf`. Bản cũ và override `zz-aiot-release.conf` vẫn giữ nguyên. Khi cần quay lại, gỡ **chỉ override thử nghiệm này**, daemon-reload và restart service rồi đọc lại ExecStart/WorkingDirectory/health. Có chuẩn bị rollback tự động nếu kích hoạt thất bại; chưa diễn tập một lượt rollback đầy đủ sau khi thử nghiệm đã thành công.
