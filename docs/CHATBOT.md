# Trợ lý AI

[Về README](../README.md) · [API](API.md)

Dashboard có một trợ lý chung, mở từ menu bên trái. `chatbot_system.py` xử lý
câu hỏi trong hàng đợi nền: bổ sung tài liệu Medical RAG cho câu hỏi sức khỏe,
tìm web khi cần thông tin mới hoặc gọi mô hình cho câu hỏi tổng quát.

## Cấu hình

Đặt `GEMINI_API_KEY` trong `.env` cục bộ. Các lựa chọn model và queue nằm trong
`config.py`: `GEMINI_CHAT_MODEL`, `GEMINI_EMBEDDING_MODEL`, `CHATBOT_QUEUE_SIZE`,
`CHATBOT_MAX_QUESTION_CHARS`, `WEB_SEARCH_ENABLE` và nhóm `MEDICAL_RAG_*`.
Không có key thì các chức năng gọi mô hình không sử dụng được.

Nguồn tài liệu ở `medical_docs/`; index sinh ra ở `medical_index/` và được Git bỏ qua.
Để nạp tài liệu chủ động từ thư mục gốc dự án:

```bash
python ingest_medical_docs.py
```

Việc ingest có thể gọi API embedding. `MEDICAL_RAG_AUTO_INGEST` điều khiển nạp tự
động lúc khởi động; script thử bếp đặt biến này bằng `0`.

## Luồng API

1. Đăng nhập, gửi `POST /api/chatbot` với `{"message":"Câu hỏi của bạn"}`.
2. Nhận `job_id`, thăm dò `GET /api/chatbot/result/<job_id>`.
3. Khi `status` là `done`, hiển thị `answer`, `sources` và `web_results`.

`app.py` đã khởi tạo worker; không cần sửa entry point để bật trợ lý.
Kiểm tra key, kết nối Internet, model và log nếu job báo lỗi. Nội dung trợ lý là
thông tin tham khảo, không thay thế đánh giá của nhân viên y tế.
