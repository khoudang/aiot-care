# Hướng dẫn Hiệu chuẩn và Hợp đồng Dữ liệu Cảm biến Khí MP-2

## 1. Thông tin cảm biến & Cấu hình phần cứng

* **Loại cảm biến:** Winsen MP-2 Micro Semiconductor Gas Sensor.
* **Tài liệu tham chiếu:** *Winsen MP-2 Technical Manual v1.4* (Zhengzhou Winsen Electronics Technology Co., Ltd).
* **Khí phát hiện mục tiêu:** Khí gas dễ cháy — chính: Propan ($C_3H_8$), Butan ($C_4H_{10}$), Methane ($CH_4$), cồn (Alcohol), khói gas.
* **Dải nồng độ phát hiện công bố:** 200 – 10000 ppm ($C_3H_8$).
* **Nguồn nuôi & mạch gia nhiệt (Heater):**
  * Điện thế nguồn mạch đo ($V_c$): $\le 24\text{ V DC}$ (mạch thực tế: $5.0\text{ V DC}$).
  * Điện thế sấy ($V_h$): $5.0\text{ V DC} \pm 0.1\text{ V}$.
  * Điện trở sấy ($R_H$): $105 \pm 10\ \Omega$.
  * Công suất tiêu thụ sấy ($P_H$): $\approx 240\text{ mW}$.
* **Mạch phân áp đầu ra tới ESP32-C3:**
  * Đầu ra Analog ($V_{AO}$) từ module 5V đi qua cầu chia áp:
    $$R_1 = 1.0\text{ k}\Omega,\quad R_2 = 1.5\text{ k}\Omega \implies V_{ADC} = V_{AO} \times \frac{1.5}{1.0 + 1.5} = 0.6 \times V_{AO}$$
  * Giới hạn điện áp vào chân `GPIO0` của ESP32-C3: $0.6 \times 5.0\text{ V} = 3.0\text{ V} \le 3.3\text{ V}$ (an toàn cho ADC).
  * Chân số `GPIO1` (Digital Out từ module) KHÔNG tham gia xử lý cảnh báo do nguy cơ điện áp 5V và ngưỡng so sánh thô không điều chỉnh được từ gateway.

---

## 2. Nguyên tắc "Trung thực kỹ thuật" (Sensor Honesty)

1. **Tuyệt đối KHÔNG giả lập ppm:**
   * Cảm biến bán dẫn MP-2 có đường đặc tính nồng độ phi tuyến tính dạng log-log ($R_s/R_0$ theo ppm).
   * Giá trị đọc về từ ADC ($0 - 4095$) tỷ lệ thuận với điện thế nút phân áp, **KHÔNG PHẢI** là nồng độ ppm tuyến tính.
   * Hệ thống trả về giá trị thô `gas: <int>` kèm siêu dữ liệu:
     * `gas_unit: "raw_adc"`
     * `calibration_status: "uncalibrated"`
     * `ppm_c3h8: null` (hoặc `unavailable`)
2. **Không đồng nhất `smoke: false` với cảm biến khói chuyên dụng:**
   * Node bếp không có đầu báo khói quang học độc lập. Trường `smoke: false` trong payload chỉ giữ lại để tương thích ngược với schema cũ. Giao diện người dùng và tài liệu phải ghi rõ chỉ có cảm biến khí MP-2 và cảm biến lửa.
3. **Giữ nguyên logic an toàn bảo vệ fail-closed:**
   * Ngưỡng cảnh báo nhẹ (`GAS_WARN_THRESHOLD = 1500`) và khẩn cấp (`GAS_HIGH_THRESHOLD = 2500`) là các ngưỡng ADC thô trên mạch thực nghiệm.
   * Giữ nguyên thời gian tích lũy an toàn liên tục $10\text{ giây}$ trước khi cho phép vào trạng thái chờ xác nhận (`WAIT_CONFIRM`).

---

## 3. Điều kiện tiên quyết trước khi triển khai tính ppm

Để chuyển đổi từ điện áp ADC sang nồng độ ppm $C_3H_8$ tin cậy, bắt buộc phải có đầy đủ các dữ kiện sau trên phần cứng thực tế:
1. **Sơ đồ nguyên lý module MP-2:** Đo chính xác giá trị điện trở tải $R_L$ được hàn trên module thực tế (thường từ $1\text{ k}\Omega$ đến $47\text{ k}\Omega$).
2. **Thời gian sấy ổn định (Preheating Time):** Cảm biến MP-2 cần sấy tối thiểu $24\text{ giờ}$ (burn-in) trước lần hiệu chuẩn đầu tiên, và tối thiểu $2 - 5\text{ phút}$ sau mỗi lần cấp nguồn.
3. **Hiệu chuẩn điểm chuẩn ($R_0$):** Đo giá trị $R_s$ trong buồng khí sạch có nhiệt độ ($20^\circ\text{C} \pm 2$) và độ ẩm ($55\% \pm 5\%$) chuẩn để tính $R_0$.
4. **Bù nhiệt ẩm:** Sử dụng công thức đường cong hiệu chỉnh nhiệt độ/độ ẩm từ datasheet Winsen MP-2:
   $$\alpha = f(T, H)$$
5. **Đường chuẩn thực nghiệm:** Khảo sát nồng độ khí chuẩn $C_3H_8$ ($200\text{ ppm}, 1000\text{ ppm}, 2000\text{ ppm}$) trong buồng kín thử nghiệm chuyên dụng có kiểm soát an toàn phòng chống cháy nổ.
