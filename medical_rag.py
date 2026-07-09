"""
medical_rag.py — Backend RAG cho chatbot "Bác sĩ gia đình".

Mục tiêu tối ưu Raspberry Pi 4:
- Không xử lý câu hỏi chatbot trực tiếp trong request Flask.
- Đẩy câu hỏi vào hàng đợi nhỏ, 1 worker nền xử lý tuần tự.
- Cache vector index trong RAM để truy xuất nhanh.
- Giới hạn context gửi lên Gemini để giảm thời gian phản hồi.
- Chatbot là tác vụ ưu tiên thấp, không tranh luồng chính BLE/camera/Socket.IO.

Lưu ý an toàn:
- Chatbot chỉ cung cấp thông tin sức khỏe cơ bản theo tài liệu đã nạp.
- Không chẩn đoán bệnh, không kê đơn thuốc, không thay thế bác sĩ.
"""

import json
import math
import queue
import re
import sqlite3
import threading
import time
import uuid
from pathlib import Path

import requests

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None

try:
    from docx import Document
except Exception:
    Document = None

from config import (
    GEMINI_API_KEY,
    GEMINI_CHAT_MODEL,
    GEMINI_EMBEDDING_MODEL,
    MEDICAL_DOCS_DIR,
    MEDICAL_INDEX_DB,
    MEDICAL_RAG_CHUNK_OVERLAP,
    MEDICAL_RAG_CHUNK_SIZE,
    MEDICAL_RAG_JOB_TTL_SEC,
    MEDICAL_RAG_MAX_CONTEXT_CHARS,
    MEDICAL_RAG_QUEUE_SIZE,
    MEDICAL_RAG_REQUEST_TIMEOUT,
    MEDICAL_RAG_TOP_K,
    MEDICAL_RAG_WORKER_IDLE_SLEEP,
)


# ================================================================== #
#  Dấu hiệu nguy hiểm — để chatbot nhắc đi khám/cấp cứu
# ================================================================== #
DANGER_KEYWORDS = [
    "đau ngực",
    "khó thở",
    "ngất",
    "co giật",
    "yếu liệt",
    "liệt nửa người",
    "lơ mơ",
    "tím tái",
    "chảy máu nhiều",
    "nôn ra máu",
    "đau bụng dữ dội",
    "sốt cao không hạ",
    "sốt cao kéo dài",
    "tay chân lạnh",
    "mệt lả",
]


# ================================================================== #
#  Ẩn nguồn tham khảo khỏi câu trả lời hiển thị cho người dùng
# ================================================================== #
_SOURCE_SECTION_RE = re.compile(
    r"(?ims)\n\s*(?:\d+\.\s*)?(?:nguồn tham khảo|tài liệu tham khảo|nguồn)\s*:.*$"
)


def strip_sources_from_answer(answer: str) -> str:
    """Xóa phần nguồn tham khảo nếu model vẫn tự sinh ra ở cuối câu trả lời."""
    clean = (answer or "").strip()
    if not clean:
        return ""
    clean = _SOURCE_SECTION_RE.sub("", clean).strip()
    return clean


# ================================================================== #
#  SQLite index
# ================================================================== #
def _db_path() -> Path:
    return Path(MEDICAL_INDEX_DB)


def _docs_dir() -> Path:
    return Path(MEDICAL_DOCS_DIR)


def _get_db_connection():
    conn = sqlite3.connect(str(_db_path()), timeout=20)
    conn.execute("pragma journal_mode = WAL")
    conn.execute("pragma synchronous = NORMAL")
    conn.execute("pragma busy_timeout = 5000")
    return conn


def ensure_medical_db():
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        create table if not exists medical_chunks (
            id integer primary key autoincrement,
            source text not null,
            chunk_index integer not null,
            text text not null,
            embedding text not null,
            created_at datetime default current_timestamp
        )
        """
    )
    cur.execute(
        "create index if not exists idx_medical_chunks_source on medical_chunks(source)"
    )
    conn.commit()
    conn.close()


def reset_index():
    ensure_medical_db()
    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("delete from medical_chunks")
    conn.commit()
    conn.close()
    clear_index_cache()


# ================================================================== #
#  Đọc tài liệu
# ================================================================== #
def _read_txt(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")


def _read_pdf(path: Path) -> str:
    if PdfReader is None:
        raise RuntimeError("Chưa cài pypdf. Chạy: pip install pypdf")
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)


def _read_docx(path: Path) -> str:
    if Document is None:
        raise RuntimeError("Chưa cài python-docx. Chạy: pip install python-docx")
    doc = Document(str(path))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".txt":
        return _read_txt(path)
    if suffix == ".pdf":
        return _read_pdf(path)
    if suffix == ".docx":
        return _read_docx(path)
    return ""


def chunk_text(text: str, chunk_size=None, overlap=None):
    chunk_size = int(chunk_size or MEDICAL_RAG_CHUNK_SIZE)
    overlap = int(overlap or MEDICAL_RAG_CHUNK_OVERLAP)

    clean = " ".join((text or "").split())
    if not clean:
        return []

    chunks = []
    start = 0
    length = len(clean)

    while start < length:
        end = min(start + chunk_size, length)
        chunk = clean[start:end].strip()

        if len(chunk) >= 80:
            chunks.append(chunk)

        if end >= length:
            break

        start = max(0, end - overlap)

    return chunks


# ================================================================== #
#  Gemini API
# ================================================================== #
def _api_key():
    # Đọc động từ config đã import; nếu muốn đổi key, restart app sau khi set env.
    key = (GEMINI_API_KEY or "").strip()
    if not key:
        raise RuntimeError(
            "Chưa cấu hình GEMINI_API_KEY. Hãy đặt biến môi trường GEMINI_API_KEY rồi chạy lại app."
        )
    return key


def gemini_embed(text: str, task_type="RETRIEVAL_DOCUMENT", max_retries=3):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_EMBEDDING_MODEL}:embedContent"
        f"?key={_api_key()}"
    )

    payload = {
        "model": f"models/{GEMINI_EMBEDDING_MODEL}",
        "content": {
            "parts": [
                {"text": text}
            ]
        },
        "taskType": task_type,
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=MEDICAL_RAG_REQUEST_TIMEOUT)
            data = resp.json() if resp.content else {}

            if resp.status_code >= 400:
                message = data.get("error", {}).get("message", "Lỗi Gemini embedding API.")
                if "high demand" in message.lower() or resp.status_code in [429, 503, 500]:
                    print(f"Server Gemini đang quá tải, thử lại lần {attempt + 1}/{max_retries} sau 5 giây...")
                    time.sleep(5)
                    continue
                raise RuntimeError(message)

            values = data.get("embedding", {}).get("values", [])
            if not values:
                raise RuntimeError("Gemini không trả về embedding.")

            return [float(v) for v in values]
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Lỗi mạng: {str(e)}")
            time.sleep(5)
            
    raise RuntimeError("Gemini API liên tục báo quá tải. Vui lòng thử lại sau.")


def call_gemini_generate(prompt: str, max_retries=3):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_CHAT_MODEL}:generateContent"
        f"?key={_api_key()}"
    )

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 700,
        },
    }

    for attempt in range(max_retries):
        try:
            resp = requests.post(url, json=payload, timeout=MEDICAL_RAG_REQUEST_TIMEOUT)
            data = resp.json() if resp.content else {}

            if resp.status_code >= 400:
                message = data.get("error", {}).get("message", "Lỗi Gemini generateContent API.")
                if "high demand" in message.lower() or resp.status_code in [429, 503, 500]:
                    print(f"Server Gemini đang quá tải, thử lại lần {attempt + 1}/{max_retries} sau 5 giây...")
                    import time
                    time.sleep(5)
                    continue
                raise RuntimeError(message)

            answer = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )

            answer = strip_sources_from_answer(answer)
            return answer or "Tôi chưa tạo được câu trả lời. Vui lòng thử lại."
            
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Lỗi mạng: {str(e)}")
            import time
            time.sleep(5)
            
    raise RuntimeError("Gemini API liên tục báo quá tải. Vui lòng thử lại sau.")


# ================================================================== #
#  Ingest tài liệu
# ================================================================== #
def ingest_documents():
    docs_dir = _docs_dir()
    docs_dir.mkdir(parents=True, exist_ok=True)
    ensure_medical_db()

    supported_exts = {".txt", ".pdf", ".docx"}
    files = [
        path for path in sorted(docs_dir.iterdir())
        if path.is_file() and path.suffix.lower() in supported_exts
    ]

    conn = _get_db_connection()
    cur = conn.cursor()

    total_chunks = 0
    per_file = {}

    for path in files:
        text = read_document(path)
        chunks = chunk_text(text)
        per_file[path.name] = len(chunks)

        for idx, chunk in enumerate(chunks):
            emb = gemini_embed(chunk, task_type="RETRIEVAL_DOCUMENT")
            cur.execute(
                """
                insert into medical_chunks (source, chunk_index, text, embedding)
                values (?, ?, ?, ?)
                """,
                (path.name, idx, chunk, json.dumps(emb, ensure_ascii=False)),
            )
            total_chunks += 1

            # Nhường CPU/I/O nhẹ trên Pi 4, tránh làm đơ nếu ingest khi app đang chạy.
            time.sleep(0.08)

        conn.commit()

    conn.close()
    clear_index_cache()
    return {"total_chunks": total_chunks, "files": per_file}


# ================================================================== #
#  Cache index trong RAM
# ================================================================== #
_INDEX_CACHE = []
_INDEX_CACHE_SIG = None
_INDEX_LOCK = threading.Lock()


def _index_signature():
    db_path = _db_path()
    if not db_path.exists():
        return None
    st = db_path.stat()
    return (st.st_mtime_ns, st.st_size)


def clear_index_cache():
    global _INDEX_CACHE, _INDEX_CACHE_SIG
    with _INDEX_LOCK:
        _INDEX_CACHE = []
        _INDEX_CACHE_SIG = None


def load_index_cache(force=False):
    global _INDEX_CACHE, _INDEX_CACHE_SIG

    ensure_medical_db()
    sig = _index_signature()

    with _INDEX_LOCK:
        if not force and _INDEX_CACHE and _INDEX_CACHE_SIG == sig:
            return list(_INDEX_CACHE)

    conn = _get_db_connection()
    cur = conn.cursor()
    cur.execute("select source, chunk_index, text, embedding from medical_chunks")
    rows = cur.fetchall()
    conn.close()

    cache = []
    for source, chunk_index, text, embedding_json in rows:
        try:
            embedding = [float(v) for v in json.loads(embedding_json)]
        except Exception:
            continue
        cache.append(
            {
                "source": source,
                "chunk_index": int(chunk_index),
                "text": text,
                "embedding": embedding,
            }
        )

    with _INDEX_LOCK:
        _INDEX_CACHE = cache
        _INDEX_CACHE_SIG = sig

    return list(cache)


# ================================================================== #
#  Search context
# ================================================================== #
def cosine_similarity(a, b):
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0

    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y

    denom = math.sqrt(norm_a) * math.sqrt(norm_b)
    if denom <= 0:
        return 0.0

    return dot / denom


def retrieve_context(question: str, top_k=None):
    top_k = int(top_k or MEDICAL_RAG_TOP_K)
    chunks = load_index_cache()

    if not chunks:
        return []

    query_emb = gemini_embed(question, task_type="RETRIEVAL_QUERY")

    scored = []
    for item in chunks:
        score = cosine_similarity(query_emb, item["embedding"])
        scored.append(
            {
                "source": item["source"],
                "chunk_index": item["chunk_index"],
                "text": item["text"],
                "score": score,
            }
        )

    scored.sort(key=lambda row: row["score"], reverse=True)
    return scored[:top_k]


def has_danger_signal(question: str) -> bool:
    q = (question or "").lower()
    return any(keyword in q for keyword in DANGER_KEYWORDS)


# ================================================================== #
#  Lịch sử trò chuyện (Memory)
# ================================================================== #
_CHAT_HISTORY = []
MAX_HISTORY_PAIRS = 5

def build_medical_prompt(question: str, contexts, history: list = None):
    used_chars = 0
    blocks = []

    for ctx in contexts:
        text = ctx["text"]
        if used_chars + len(text) > MEDICAL_RAG_MAX_CONTEXT_CHARS:
            remaining = MEDICAL_RAG_MAX_CONTEXT_CHARS - used_chars
            if remaining <= 300:
                break
            text = text[:remaining]

        blocks.append(
            f"[Nguồn: {ctx['source']} - đoạn {ctx['chunk_index']}]\n{text}"
        )
        used_chars += len(text)

    context_text = "\n\n".join(blocks)

    history_text = ""
    if history:
        h_blocks = []
        for h in history:
            h_blocks.append(f"Người dùng: {h['question']}\nAI: {h['answer']}")
        history_text = "LỊCH SỬ TRÒ CHUYỆN GẦN ĐÂY:\n" + "\n\n".join(h_blocks) + "\n\n"

    danger_note = ""
    if has_danger_signal(question):
        danger_note = (
            "\nCâu hỏi có thể chứa dấu hiệu nguy hiểm. "
            "Hãy nhắc người dùng liên hệ cơ sở y tế hoặc cấp cứu nếu triệu chứng đang xảy ra."
        )

    return f"""
Bạn là chatbot "Bác sĩ gia đình" của hệ thống AIoT Care Station.

Vai trò:
- Hỗ trợ hỏi đáp sức khỏe, tư vấn y tế và trò chuyện giao tiếp bằng tiếng Việt.
- ƯU TIÊN dùng TÀI LIỆU THAM KHẢO CỤC BỘ (bên dưới) để trả lời nếu có liên quan.
- Nếu tài liệu cục bộ không đề cập hoặc người dùng hỏi chuyện ngoài lề, bạn ĐƯỢC PHÉP dùng kiến thức y khoa uy tín của bạn hoặc trò chuyện tự nhiên.
- Vẫn tuân thủ: Không tự ý chẩn đoán khẳng định bệnh, không kê đơn thuốc.
- Nếu có dấu hiệu nguy hiểm như đau ngực, khó thở, ngất, co giật, yếu liệt, sốt cao kéo dài hoặc chảy máu nhiều, hãy khuyên liên hệ cơ sở y tế ngay.
{danger_note}

{history_text}
TÀI LIỆU THAM KHẢO CỤC BỘ (Nếu có):
{context_text}

CÂU HỎI MỚI NHẤT:
{question}

Trả lời theo cấu trúc:
1. Trả lời thân thiện, dễ hiểu.
2. Khi nào nên đi khám hoặc cần chú ý (nếu đó là câu hỏi về bệnh tật).

Không hiển thị mục "Nguồn tham khảo".
Không ghi tên file, số đoạn, citation hoặc danh sách tài liệu trong câu trả lời.
""".strip()


def answer_medical_question_sync(question: str):
    global _CHAT_HISTORY
    contexts = retrieve_context(question)

    prompt = build_medical_prompt(question, contexts, _CHAT_HISTORY)
    answer = call_gemini_generate(prompt)

    _CHAT_HISTORY.append({"question": question, "answer": answer})
    if len(_CHAT_HISTORY) > MAX_HISTORY_PAIRS:
        _CHAT_HISTORY.pop(0)

    sources = [
        {
            "source": ctx["source"],
            "chunk_index": ctx["chunk_index"],
            "score": round(float(ctx["score"]), 4),
        }
        for ctx in contexts
    ]

    return {"answer": answer, "sources": sources}


# ================================================================== #
#  Worker nền ưu tiên thấp cho chatbot
# ================================================================== #
_CHAT_QUEUE = queue.Queue(maxsize=MEDICAL_RAG_QUEUE_SIZE)
_JOBS = {}
_JOBS_LOCK = threading.Lock()
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _cleanup_jobs():
    now = time.time()
    with _JOBS_LOCK:
        old_ids = [
            job_id for job_id, job in _JOBS.items()
            if now - job.get("created_at", now) > MEDICAL_RAG_JOB_TTL_SEC
        ]
        for job_id in old_ids:
            _JOBS.pop(job_id, None)


def _worker_loop():
    while True:
        job_id = _CHAT_QUEUE.get()

        try:
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if not job:
                    continue
                job["status"] = "running"
                job["updated_at"] = time.time()

            question = job["question"]
            result = answer_medical_question_sync(question)

            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job:
                    job["status"] = "done"
                    job["answer"] = result.get("answer", "")
                    job["sources"] = result.get("sources", [])
                    job["updated_at"] = time.time()

        except Exception as exc:
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job:
                    job["status"] = "error"
                    job["message"] = str(exc)
                    job["updated_at"] = time.time()

        finally:
            _CHAT_QUEUE.task_done()
            _cleanup_jobs()

            # Nhường tài nguyên cho BLE/camera/Socket.IO.
            time.sleep(MEDICAL_RAG_WORKER_IDLE_SLEEP)


def ensure_worker_started():
    global _WORKER_STARTED

    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return

        thread = threading.Thread(
            target=_worker_loop,
            name="family-doctor-rag-worker",
            daemon=True,
        )
        thread.start()
        _WORKER_STARTED = True


def submit_medical_question(question: str, user_id=None):
    ensure_worker_started()

    q = (question or "").strip()
    if not q:
        return {"ok": False, "message": "Vui lòng nhập câu hỏi."}

    if len(q) > 1200:
        return {"ok": False, "message": "Câu hỏi quá dài. Vui lòng rút gọn dưới 1200 ký tự."}

    _cleanup_jobs()

    if _CHAT_QUEUE.full():
        return {
            "ok": False,
            "message": "Bác sĩ gia đình đang xử lý câu hỏi khác. Vui lòng thử lại sau vài giây.",
        }

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "question": q,
        "answer": None,
        "sources": [],
        "message": "",
        "user_id": user_id,
        "created_at": time.time(),
        "updated_at": time.time(),
    }

    with _JOBS_LOCK:
        _JOBS[job_id] = job

    try:
        _CHAT_QUEUE.put_nowait(job_id)
    except queue.Full:
        with _JOBS_LOCK:
            _JOBS.pop(job_id, None)
        return {
            "ok": False,
            "message": "Bác sĩ gia đình đang bận. Vui lòng thử lại sau vài giây.",
        }

    return {"ok": True, "status": "queued", "job_id": job_id}


def get_medical_job(job_id: str):
    _cleanup_jobs()

    with _JOBS_LOCK:
        job = _JOBS.get(job_id)

        if not job:
            return None

        # Không trả về question/user_id để tránh lộ dữ liệu không cần thiết.
        return {
            "id": job["id"],
            "status": job["status"],
            "answer": job.get("answer"),
            "sources": job.get("sources") or [],
            "message": job.get("message") or "",
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }


# Khởi động worker ngay khi module được import, nhưng chưa xử lý gì cho tới khi có câu hỏi.
ensure_worker_started()
