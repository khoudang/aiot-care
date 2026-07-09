# AIoT Care Station — Chatbot AI duy nhất

Bản này bỏ hoàn toàn phần chia mode ở frontend. Người dùng chỉ thấy **một chatbot duy nhất**: `Trợ lý AI hệ thống`.

```text
Chatbot AI hệ thống
├── Tự dùng Medical RAG khi câu hỏi liên quan sức khỏe / bệnh tật
├── Tự dùng Web Search khi câu hỏi cần dữ liệu mới nhất
└── Gọi LLM trực tiếp cho câu hỏi tổng quát
```

## 1. Luồng xử lý

```text
User hỏi chatbot
      ↓
POST /api/chatbot
      ↓
Backend đưa câu hỏi vào queue nền
      ↓
Worker tự phân tích câu hỏi
      ├─ Nếu là câu hỏi sức khỏe → lấy thêm context từ medical_docs
      ├─ Nếu cần dữ liệu mới nhất → tìm web rồi tổng hợp
      └─ Nếu là câu hỏi tổng quát → gọi LLM trực tiếp
      ↓
GET /api/chatbot/result/<job_id>
      ↓
Frontend hiển thị câu trả lời
```

## 2. File cần thay đổi

```text
chatbot_system.py          # viết lại: chỉ còn một AI, không mode
web.py                     # đổi API /api/chatbot, bỏ /api/chatbot/modes
config.py                  # đổi cấu hình chatbot một AI
app.py                     # thêm init_unified_chatbot() nếu muốn worker start sẵn
.env.chatbot.example       # cấu hình mẫu mới
README_CHATBOT.md          # tài liệu này
```

## 3. API mới

### Gửi câu hỏi

```http
POST /api/chatbot
Content-Type: application/json
```

```json
{
  "message": "BLE Mesh là gì?"
}
```

Response:

```json
{
  "ok": true,
  "status": "queued",
  "job_id": "..."
}
```

### Lấy kết quả

```http
GET /api/chatbot/result/<job_id>
```

Khi đang xử lý:

```json
{
  "ok": true,
  "status": "running",
  "message": "Trợ lý AI đang xử lý câu hỏi..."
}
```

Khi hoàn tất:

```json
{
  "ok": true,
  "status": "done",
  "answer": "...",
  "sources": [],
  "web_results": []
}
```

## 4. Tương thích API cũ

Hai endpoint cũ vẫn được giữ để frontend cũ không lỗi:

```http
POST /api/medical_chat
GET /api/medical_chat/result/<job_id>
```

Nhưng bên trong không còn ép chạy riêng `medical mode`. Endpoint cũ cũng dùng cùng một chatbot AI duy nhất.

## 5. app.py có cần thêm gì không?

Có thể thêm:

```python
from chatbot_system import init_unified_chatbot
```

Sau `init_medical_rag()` gọi:

```python
init_unified_chatbot()
```

Dòng này không bắt buộc, vì worker chatbot sẽ tự start khi có câu hỏi đầu tiên. Tuy nhiên nên thêm để worker sẵn sàng ngay khi app chạy.

## 6. Cấu hình .env

```env
GEMINI_API_KEY=YOUR_VALID_GEMINI_API_KEY
GEMINI_CHAT_MODEL=gemini-2.5-flash-lite
GEMINI_EMBEDDING_MODEL=gemini-embedding-001

CHATBOT_QUEUE_SIZE=3
CHATBOT_JOB_TTL_SEC=900
CHATBOT_MAX_QUESTION_CHARS=2000
UNIFIED_CHAT_MAX_OUTPUT_TOKENS=900

GEMINI_MAX_RETRIES=3
GEMINI_RETRY_BASE_DELAY=1.2

MEDICAL_RAG_TOP_K=4
MEDICAL_RAG_MAX_CONTEXT_CHARS=4000
MEDICAL_RAG_AUTO_INGEST=0

WEB_SEARCH_ENABLE=1
WEB_SEARCH_PROVIDER=duckduckgo
WEB_SEARCH_MAX_RESULTS=5
WEB_SEARCH_TIMEOUT=8
```

## 7. Lưu ý

- Nếu `GEMINI_API_KEY` sai, cả chatbot tổng quát và Medical RAG đều lỗi.
- Nếu câu hỏi sức khỏe nhưng index medical chưa có dữ liệu, chatbot vẫn trả lời được bằng kiến thức tham khảo chung, nhưng sẽ nói rõ giới hạn.
- Nếu câu hỏi cần dữ liệu mới nhưng máy không truy cập được web, chatbot vẫn có thể trả lời tổng quát và báo rằng không lấy được dữ liệu mới.
