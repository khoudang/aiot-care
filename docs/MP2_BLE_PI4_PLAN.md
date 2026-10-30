# Kế hoạch cải tiến AIoT Care: MP-2, BLE và Raspberry Pi 4

## Phạm vi và trạng thái

- Nhánh kế hoạch: `plan/mp2-ble-pi4-readiness`.
- Cơ sở: `hardware-confirmed-2026-10-29`, commit `2205867d9ae3743f9cbc33161ae727f6a08c6260`.
- Phần cứng người dùng xác nhận: cảm biến **MP-2**, gateway **Raspberry Pi 4, RAM 4 GB**. Kiến trúc OS/Python và phiên bản BlueZ trên Pi chưa được xác nhận.
- `main` chưa được cập nhật theo phần cứng mới; không dùng nội dung MQ-2 cũ làm cơ sở chuyển đổi MP-2.
- Commit tài liệu này KHÔNG thay đổi firmware, ngưỡng cảnh báo, dữ liệu runtime, tài khoản hay thiết bị. Chưa có bằng chứng chạy thật trên Pi và chưa công bố ppm đã hiệu chuẩn.

## Thứ tự đề xuất

### 1. Đo độ trễ trước khi thay timeout hoặc giao thức

Thêm trace theo `command_id`: backend nhận, vào hàng đợi, bắt đầu GATT write, GATT write hoàn tất, nhận application ACK, nhận trạng thái node và phát cập nhật web. Dùng đồng hồ monotonic cho khoảng thời gian trong cùng tiến trình; không trừ timestamp giữa ESP32/Pi/browser khi chưa đồng bộ đồng hồ. Muốn đo end-to-end browser thì dùng một clock ở browser hoặc một giao thức đối chiếu phù hợp.

Phân biệt ba kết quả:
1. ATT/GATT write được chấp nhận ở tầng BLE.
2. Firmware xử lý lệnh và xuất giá trị điều khiển.
3. Cơ cấu thực sự hoàn thành chuyển động/tác động vật lý (hiện chưa có cảm biến xác nhận cho mọi thiết bị).

Ghi median, p95, tỷ lệ lỗi và độ dài hàng đợi, riêng từng node. Đo trước/sau cùng workload. Không bật/tắt relay/servo liên tục tự động trên hệ thống đang sử dụng; test ban đầu dùng fake transport hoặc fixture phần cứng có kiểm soát, không nối tải nguy hiểm.

Điểm cần đo trên bản cơ sở:
- Gateway kiểm tra gửi lệnh mỗi 50 ms (`iot.py`).
- Một lệnh đang chờ ACK trên mỗi phòng; ACK timeout 2 s, tối đa 4 attempts, TTL 30 s. Timeout KHÔNG phải độ trễ cố định của mọi lệnh.
- Bếp gửi telemetry định kỳ 1 s. Web có thể chậm xác nhận mặc dù đầu ra đã thay đổi.
- `notifyJson` chia khung 20 byte, chờ 5 ms mỗi đoạn. Đo áp lực giữa telemetry/ACK trước khi thay MTU/chunking.

**Điều kiện đạt:** có trace tái hiện được trường hợp chậm và phân biệt thời gian chờ queue, BLE, firmware, telemetry và UI; test không tiếp xúc hardware thật mặc định.

### 2. Ổn định nhận dạng, discovery và reconnect

- Phân biệt `configured`, `discovering`, `connecting`, `subscribing`, `ready`, `stale`, `disconnected`.
- Chỉ báo `ready` sau khi subscribe notify và xác nhận đúng node/protocol; bản cơ sở gọi `set_node_online(True)` trước `start_notify`.
- Giữ cache thiết bị đã cấu hình khi scan không thấy node đang kết nối; không diễn giải vắng quảng bá là offline.
- Quét chung có phối hợp, có thời hạn và backoff; không để mỗi node tự gây scan storm. Bản cơ sở đã có discovery lock/cache; cải tiến dựa trên đó, không xóa các bảo vệ này.
- Service UUID giúp lọc nhưng chưa đủ phân biệt phòng nếu các node dùng chung UUID. Bổ sung stable node ID/role hoặc đặc tính nhận dạng được kiểm tra sau kết nối, rồi mới bind với phòng. Không đoán phòng từ MAC gần nhau hoặc tên quảng bá trống.
- Có thông báo tách biệt: không thấy quảng bá, connect timeout, sai service, subscribe lỗi, mất notify và sai cấu hình.
- Đặt giới hạn `max_age` rõ ràng cho cache, debounce nút scan; không tăng tốc bằng quét liên tục. Adapter quyết định khả năng scan đồng thời với nhiều kết nối.

**Test bắt buộc:** scan trống rồi node xuất hiện; tên trống; sai UUID/role; hai node tên giống nhau; node đang connected không quảng bá; subscribe lỗi; một node mất không làm hai node còn lại mất ready; reconnect đọc đúng cấu hình mới; cache không giữ sẵn sàng giả.

### 3. Cải thiện phản hồi điều khiển, giữ logic an toàn

- Sau khi đầu ra được áp dụng, gửi ngay trạng thái thay đổi; không đợi telemetry định kỳ. Lệnh servo có thể đã được xuất góc nhưng chưa hoàn tất hành trình.
- UI hiển thị `pending`, `confirmed`, `rejected`, `timed_out`; không biến trạng thái mong muốn thành trạng thái thực tế chỉ vì enqueue thành công.
- Định nghĩa ACK `applied` thống nhất giữa node: cập nhật logic/xuất GPIO/PWM là gì; ACK không phải chứng nhận tải vật lý đã hoạt động.
- Cân nhắc đánh thức sender bằng event khi có lệnh mới thay cho poll, nhưng chỉ sau khi có baseline. Không busy loop.
- Giữ correlation ID, retry có giới hạn và thứ tự an toàn. Lệnh thay đổi trạng thái nên idempotent; không tự áp dụng retry cho thao tác có tác dụng phụ không lặp lại được.
- Lệnh cảnh báo/khôi phục cần ưu tiên và kiểm tra event/phase, không để lệnh manual hoặc slider cũ vô hiệu hóa cảnh báo mới.
- Slider có coalescing, nhưng không được coi lệnh đã gửi là chưa hề thực thi khi hủy pending. Xác nhận lại từ node.
- Không mặc định đổi mọi GATT write sang `response=False`, giảm ACK timeout mạnh hoặc bỏ ACK để có cảm giác nhanh.

**Điều kiện đạt:** test transport giả chứng minh immediate state update và timeout/retry hợp lý; test đồng thời manual/auto/alarm/reconnect không làm sai trạng thái an toàn. Mục tiêu độ trễ thực tế sẽ chốt sau baseline, không hứa một con số khi chưa đo.

### 4. Nghiệm thu trên Raspberry Pi 4 / 4 GB

Ghi nhận Pi OS 32/64 bit, Python, BlueZ, adapter Bluetooth, nguồn/tản nhiệt và camera trước khi khóa dependency. Pi 4 / 4 GB là thông tin cấu hình, không phải bằng chứng hệ thống chạy tốt.

Kiểm tra tăng tải theo thứ tự:
1. Backend + một node, camera/AI tắt.
2. Ba node đồng thời, camera/AI tắt.
3. Camera stream.
4. Từng tác vụ cử chỉ/theo dõi/nghi ngờ té ngã, sau đó tổ hợp cần demo.

Mỗi bước ghi CPU, RSS RAM, nhiệt độ/throttling, queue length, camera FPS xử lý thực, độ tuổi frame, tỷ lệ reconnect và độ trễ command. Khảo sát nhiễu Wi-Fi 2.4 GHz/BT, vị trí antenna và thiết bị USB trước khi thay transport. Không tự tắt Wi-Fi hoặc thay adapter khi chưa được phép.

Nếu AI làm tăng trễ, dùng bounded latest-frame queue và cân nhắc tách camera/AI khỏi BLE; không thêm process chỉ vì nghe có vẻ nhanh hơn. Kết quả đo quyết định kiến trúc.

Rà systemd: user/workdir/venv thật, Bluetooth/D-Bus readiness và quyền, log xoay vòng, restart có giới hạn/backoff, khởi động lại không tạo gateway trùng. Không bật debug reloader trên Pi demo. Kiểm tra wheel/dependency đúng nền tảng trước khi pin; không khẳng định mọi gói MediaPipe/OpenCV đều có binary tương thích với mọi Python ARM.

**Điều kiện đạt:** có log từ Pi thật, hoạt động đủ ba node và những tác vụ demo được chọn; thử reboot gateway, power-cycle một node, mất/kết nối lại browser và cập nhật cấu hình. Đề xuất chạy ổn định ít nhất một buổi demo dài; ghi rõ thời lượng đã thử, không gọi là soak test nhiều ngày nếu chưa thực hiện.

### 5. MP-2: chỉ thêm ppm sau khi biết mạch và calibration

Nguồn: Winsen MP-2 Manual v1.4. Dải công bố 200–10000 ppm C3H8 là phạm vi của cảm biến theo điều kiện nhà sản xuất, không phải phép gán tuyến tính cho ADC. Đường cong dùng Rs/R0 và định nghĩa tham chiếu trong datasheet đúng model. Không dùng hệ số hoặc định nghĩa R0 của MQ-2 một cách máy móc.

Cần bổ sung trước khi triển khai:
- Module/nhà sản xuất thực tế, ảnh/sơ đồ đường AO, giá trị điện trở tải và nguồn đo.
- Mạch chia áp thực tế: tài liệu nhánh cơ sở ghi R1 1 kohm, R2 1.5 kohm; phải xác nhận bằng phần cứng. Nếu AO là nút tải chưa đệm, chia áp có thể làm thay đổi tải hiệu dụng.
- Cấu hình ADC ESP32-C3, attenuation/calibration, đo điện áp đối chiếu. Không mặc định adc/4095*3.3 là điện áp chính xác.
- Khí đích (đề xuất C3H8 theo đường cong MP-2), chuẩn tham chiếu và dữ liệu kiểm chứng có kiểm soát.

Thiết kế fail-closed: khi thiếu calibration hoặc tín hiệu ngoài miền hợp lệ, giữ ADC/millivolt và `calibration_status`; trả ppm chưa khả dụng, không trả 0 ppm như thể không có khí. Nếu có ppm ước tính thì hiển thị rõ khí đích, đơn vị, phiên bản calibration và chất lượng/giới hạn.

Chưa tự đổi ngưỡng ADC thử nghiệm 1500/2500 sang ppm, chưa đổi logic bảo vệ cục bộ. Chỉ thay ngưỡng sau đánh giá và kiểm thử trên phần cứng với quy trình an toàn. Không dùng bình gas/bật lửa xả khí trong nhà để hiệu chuẩn. Quạt/relay mô hình không phải thiết bị phòng nổ và đồ án không thay thế đầu báo khí được chứng nhận.

**Điều kiện đạt:** kiểm tra chuyển ADC/mV/mạch đúng; không extrapolate đường cong không được xác thực; tình huống warm-up, disconnected, ADC sát rail, calibration lỗi và đơn vị đều được test. Không có mẫu calibration/slope bịa để làm demo.

## Giao thức chức năng cần đối chiếu chung

Một bảng contract cho cả firmware, backend và web: node ID/room, service/characteristic UUID, version, đơn vị/miền giá trị, command ID, ACK semantics, trạng thái thực tế/mong muốn, timestamp/age, cảnh báo/event/phase và ưu tiên manual/auto/safety. Kiểm tra từng thiết bị qua web và cử chỉ: light/fan/buzzer/window/exhaust/auto theo đúng node_protocol, không quảng cáo điều khiển phần cứng chưa được gán.

Bản kế hoạch không tự xác nhận 39 test cũ hoặc các lỗi cũ còn nguyên: cần chạy lại baseline ở commit triển khai và phân loại test lệch contract với lỗi code, không xóa assertion chỉ để xanh.

## Chia commit triển khai tiếp theo

1. `test(ble): latency trace and deterministic transport fixtures` — đo lường, chưa đổi điều khiển.
2. `fix(ble): readiness and coordinated discovery/reconnect` — sau baseline và repro đỏ.
3. `feat(protocol): immediate applied-state feedback` — cập nhật ba lớp đồng thời, giữ tương thích hoặc version rõ ràng.
4. `test(pi): reproducible Pi4 deployment and acceptance evidence` — bằng chứng Pi thật, không chỉ laptop.
5. `feat(mp2): calibrated C3H8 estimate with explicit validity` — CHỜ thông số mạch/calibration; không phải công việc có thể hoàn tất từ repo hiện tại.

Không đổi main, merge, flash board hoặc điều khiển tải thật trong commit kế hoạch này.

## Tài liệu tham chiếu

- MP-2 Manual v1.4: https://www.winsen-sensor.com/d/files/mp-2-manual-v1_4.pdf
- Bleak client / BLEDevice và giới hạn adapter: https://bleak.readthedocs.io/en/latest/api/client.html
- Bleak troubleshooting / asyncio và Raspberry Pi: https://bleak.readthedocs.io/en/latest/troubleshooting.html
