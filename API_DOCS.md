# Tài liệu Hướng dẫn sử dụng API (AIoT Care Station)

Hệ thống AIoT Care Station cung cấp 2 phương thức giao tiếp cho Frontend (Web / App Mobile):
1. **REST API (HTTP/HTTPS):** Dành cho việc lấy dữ liệu 1 lần, gửi lệnh điều khiển, hoặc chat với AI.
2. **WebSocket (Socket.IO):** Dành cho việc stream dữ liệu thời gian thực (telemetry, cảnh báo cháy nổ, ngã).

---

## 1. REST API Endpoints

### 1.1 Lấy toàn bộ trạng thái hệ thống
*   **URL:** `/api/status`
*   **Method:** `GET`
*   **Yêu cầu đăng nhập:** Có (Session Cookie)
*   **Response (JSON):**
    ```json
    {
      "rooms": {
        "patient": {"temp": 25.5, "hum": 60, "gas": 400, "motion": true, "light": false, ...},
        "living": {...},
        "kitchen": {...},
        "wearable": {"heart_rate": 80, "spo2": 98}
      },
      "nodes": {
        "patient": true,
        "living": true
      },
      "camera": {"active": true, "mode": "fall_detection"},
      "alert": {"level": 0},
      "histories": {...}
    }
    ```

### 1.2 Điều khiển thiết bị (Bật/Tắt Relay, Servo)
*   **URL:** `/api/control`
*   **Method:** `POST`
*   **Content-Type:** `application/json`
*   **Yêu cầu đăng nhập:** Có
*   **Body:**
    ```json
    {
      "room": "patient",
      "device": "fan",
      "state": true
    }
    ```
    *Ghi chú: `device` có thể là `light`, `fan`, `buzzer`, `window`, `exhaust`, `auto`.*
*   **Response:** `{"status": "ok"}` hoặc `{"status": "error", "message": "..."}`

### 1.3 Chat với Bác sĩ AI (RAG)
*   **URL:** `/api/ai_chat`
*   **Method:** `POST`
*   **Content-Type:** `application/json`
*   **Yêu cầu đăng nhập:** Có
*   **Body:**
    ```json
    {
      "message": "Huyết áp của tôi hôm nay là 140/90, có sao không bác sĩ?"
    }
    ```
*   **Response:**
    ```json
    {
      "response": "Chào bạn, với chỉ số huyết áp 140/90, bạn đang ở mức tăng huyết áp độ 1 theo khuyến cáo của Bộ Y Tế. Xin hãy..."
    }
    ```

### 1.4 Lấy dữ liệu lịch sử (Vẽ biểu đồ)
*   **URL:** `/api/history`
*   **Method:** `GET`
*   **Response:** Trả về chuỗi JSON chứa mảng thời gian (`labels`) và các mảng giá trị của từng cảm biến theo thời gian.

### 1.5 Luồng Video Camera (MJPEG Stream)
*   **URL:** `/video_feed`
*   **Method:** `GET`
*   **Cách dùng Frontend:** Gắn thẳng URL này vào thẻ `<img src="/video_feed">`. Pi sẽ tự động trả về luồng video liên tục. Luồng này sẽ tự động dừng nếu không có ai xem (để tiết kiệm CPU).

---

## 2. Giao thức Real-time (Socket.IO)

Nếu bạn làm App React Native, Flutter, hay Web Vue/React, bạn nên dùng thư viện `socket.io-client` để kết nối vào cổng `5000`.

### 2.1 Các sự kiện Client LẮNG NGHE (On)

*   `telemetry_update`: Kích hoạt mỗi 1 giây. Chứa toàn bộ dữ liệu trạng thái mới nhất giống hệt API `/api/status`. Dùng cái này để update UI không bị giật lag.
*   `alert`: Nhận cảnh báo cháy nổ, phát hiện ngã lập tức.
    *   *Payload:* `{"message": "Phát hiện ngã tại phòng người bệnh!", "level": 2}`
*   `ai_response`: Dùng cho cơ chế chat AI bất đồng bộ (tránh request timeout).
    *   *Payload:* `{"response": "Nội dung trả lời từ AI..."}`

### 2.2 Các sự kiện Client GỬI ĐI (Emit)

*   `control_device`: Điều khiển thiết bị tốc độ cao (không cần chờ phản hồi HTTP).
    *   *Gửi đi:* `socket.emit('control_device', {"room": "kitchen", "device": "window", "state": true});`
