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
    MEDICAL_RAG_AUTO_INGEST,
    MEDICAL_RAG_AUTO_INGEST_ASYNC,
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


def ensure_medical_db():
    db_path = _db_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(db_path), timeout=20)
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
    conn = sqlite3.connect(str(_db_path()), timeout=20)
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


def gemini_embed(text: str, task_type="RETRIEVAL_DOCUMENT"):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_EMBEDDING_MODEL}:embedContent"
        f"?key={_api_key()}"
    )

    payload = {
        "content": {
            "parts": [
                {"text": text}
            ]
        },
        "taskType": task_type,
    }

    resp = requests.post(url, json=payload, timeout=MEDICAL_RAG_REQUEST_TIMEOUT)
    data = resp.json() if resp.content else {}

    if resp.status_code >= 400:
        message = data.get("error", {}).get("message", "Lỗi Gemini embedding API.")
        raise RuntimeError(message)

    values = data.get("embedding", {}).get("values", [])
    if not values:
        raise RuntimeError("Gemini không trả về embedding.")

    return [float(v) for v in values]


def _is_retryable_gemini_error(status_code: int, message: str) -> bool:
    msg = (message or "").lower()
    return (
        status_code in {429, 500, 502, 503, 504}
        or "high demand" in msg
        or "temporarily" in msg
        or "unavailable" in msg
        or "quota" in msg
    )


def call_gemini_generate(prompt: str):
    """Gọi Gemini generateContent với retry ngắn cho lỗi quá tải tạm thời."""
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
            "maxOutputTokens": 600,
        },
    }

    max_retries = int(getattr(__import__("config"), "GEMINI_MAX_RETRIES", 3))
    base_delay = float(getattr(__import__("config"), "GEMINI_RETRY_BASE_DELAY", 1.2))
    last_error = ""

    for attempt in range(1, max(1, max_retries) + 1):
        try:
            resp = requests.post(url, json=payload, timeout=MEDICAL_RAG_REQUEST_TIMEOUT)
            data = resp.json() if resp.content else {}

            if resp.status_code >= 400:
                message = data.get("error", {}).get("message", "Lỗi Gemini generateContent API.")
                last_error = message
                if attempt < max_retries and _is_retryable_gemini_error(resp.status_code, message):
                    time.sleep(base_delay * attempt)
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

        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < max_retries:
                time.sleep(base_delay * attempt)
                continue
            raise RuntimeError(f"Không kết nối được tới Gemini API: {last_error}")

    raise RuntimeError(last_error or "Gemini API xử lý thất bại.")


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

    conn = sqlite3.connect(str(_db_path()), timeout=20)
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

    conn = sqlite3.connect(str(_db_path()), timeout=20)
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


def build_medical_prompt(question: str, contexts):
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

    danger_note = ""
    if has_danger_signal(question):
        danger_note = (
            "\nCâu hỏi có thể chứa dấu hiệu nguy hiểm. "
            "Hãy nhắc người dùng liên hệ cơ sở y tế hoặc cấp cứu nếu triệu chứng đang xảy ra."
        )

    return f"""
Bạn là chatbot "Bác quản gia" của hệ thống AIoT Care Station.

Vai trò:
- Hỗ trợ hỏi đáp sức khỏe, bệnh tật cơ bản bằng tiếng Việt.
- Chỉ trả lời dựa trên TÀI LIỆU THAM KHẢO được cung cấp.
- Không chẩn đoán bệnh.
- Không kê đơn thuốc.
- Không thay thế bác sĩ hoặc cơ sở y tế.
- Nếu tài liệu không đủ dữ liệu, hãy nói rõ: "Tôi chưa có đủ dữ liệu trong tài liệu để trả lời chắc chắn."
- Nếu có dấu hiệu nguy hiểm như đau ngực, khó thở, ngất, co giật, yếu liệt, sốt cao kéo dài hoặc chảy máu nhiều, hãy khuyên liên hệ cơ sở y tế ngay.
{danger_note}

TÀI LIỆU THAM KHẢO:
{context_text}

CÂU HỎI:
{question}

Trả lời theo cấu trúc:
1. Trả lời ngắn gọn, dễ hiểu.
2. Khi nào nên đi khám hoặc cần chú ý.

Không hiển thị mục "Nguồn tham khảo".
Không ghi tên file, số đoạn, citation hoặc danh sách tài liệu trong câu trả lời.
""".strip()


def answer_medical_question_sync(question: str):
    contexts = retrieve_context(question)

    if not contexts:
        if is_auto_ingest_running():
            return {
                "answer": (
                    "Tôi đang tự nạp dữ liệu y tế vào hệ thống. "
                    "Vui lòng chờ một lát rồi hỏi lại."
                ),
                "sources": [],
            }

        return {
            "answer": (
                "Tôi chưa có dữ liệu y tế trong hệ thống để trả lời. "
                "Vui lòng kiểm tra thư mục medical_docs. Nếu database RAG đang rỗng, "
                "hãy bật MEDICAL_RAG_AUTO_INGEST=1 rồi chạy lại app.py."
            ),
            "sources": [],
        }

    prompt = build_medical_prompt(question, contexts)
    answer = call_gemini_generate(prompt)

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
            "message": "Bác quản gia đang xử lý câu hỏi khác. Vui lòng thử lại sau vài giây.",
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
            "message": "Bác quản gia đang bận. Vui lòng thử lại sau vài giây.",
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


# ================================================================== #
#  Khởi động RAG khi chạy app.py + tự nạp dữ liệu nếu DB rỗng
# ================================================================== #
_AUTO_INGEST_LOCK = threading.Lock()
_AUTO_INGEST_STATE = {
    "running": False,
    "started": False,
    "done": False,
    "error": None,
    "result": None,
    "started_at": None,
    "finished_at": None,
}


def get_index_chunk_count() -> int:
    """Đếm số đoạn đã index trong medical_index/medical_rag.db."""
    ensure_medical_db()
    conn = sqlite3.connect(str(_db_path()), timeout=20)
    cur = conn.cursor()
    cur.execute("select count(*) from medical_chunks")
    count = int(cur.fetchone()[0] or 0)
    conn.close()
    return count


def is_auto_ingest_running() -> bool:
    with _AUTO_INGEST_LOCK:
        return bool(_AUTO_INGEST_STATE.get("running"))


def get_auto_ingest_state():
    with _AUTO_INGEST_LOCK:
        return dict(_AUTO_INGEST_STATE)


def _mark_auto_ingest(**kwargs):
    with _AUTO_INGEST_LOCK:
        _AUTO_INGEST_STATE.update(kwargs)


def _auto_ingest_job():
    """Nạp tài liệu nền để không làm đứng Flask/BLE/camera khi app.py khởi động."""
    _mark_auto_ingest(
        running=True,
        started=True,
        done=False,
        error=None,
        result=None,
        started_at=time.time(),
        finished_at=None,
    )

    try:
        # Chỉ reset/index lại khi DB thật sự chưa có dữ liệu.
        # Nếu trong lúc thread khởi động DB đã có dữ liệu thì chỉ load cache.
        if get_index_chunk_count() <= 0:
            print("[medical_rag] RAG index rỗng, bắt đầu tự nạp tài liệu từ medical_docs/ ...")
            reset_index()
            result = ingest_documents()
        else:
            result = {
                "total_chunks": get_index_chunk_count(),
                "files": {},
                "skipped": "index_already_has_data",
            }

        chunks = load_index_cache(force=True)

        _mark_auto_ingest(
            running=False,
            done=True,
            error=None,
            result=result,
            finished_at=time.time(),
        )
        print(f"[medical_rag] Chatbot RAG ready. Loaded {len(chunks)} chunks.")

    except Exception as exc:
        _mark_auto_ingest(
            running=False,
            done=False,
            error=str(exc),
            finished_at=time.time(),
        )
        print(f"[medical_rag] Auto ingest error: {exc}")


def init_medical_rag(auto_ingest=None, async_ingest=None):
    """
    Hàm được app.py gọi khi khởi động.

    Hoạt động:
    - Tạo medical_index/medical_rag.db nếu chưa có.
    - Start worker nền cho chatbot.
    - Nếu DB đã có dữ liệu: load cache vào RAM.
    - Nếu DB rỗng và auto_ingest=True: tự nạp tài liệu từ medical_docs/.
      Mặc định nạp trong thread nền để không làm treo UI/BLE/camera.
    """
    if auto_ingest is None:
        auto_ingest = MEDICAL_RAG_AUTO_INGEST

    if async_ingest is None:
        async_ingest = MEDICAL_RAG_AUTO_INGEST_ASYNC

    ensure_medical_db()
    ensure_worker_started()

    count = get_index_chunk_count()
    if count > 0:
        chunks = load_index_cache(force=True)
        print(f"[medical_rag] Chatbot ready. Loaded {len(chunks)} chunks from {_db_path()}")
        return {
            "ok": True,
            "ready": True,
            "chunks": len(chunks),
            "auto_ingest": False,
            "ingesting": False,
        }

    print("[medical_rag] medical_rag.db chưa có dữ liệu.")

    if not auto_ingest:
        print("[medical_rag] MEDICAL_RAG_AUTO_INGEST=0, bỏ qua tự nạp dữ liệu.")
        return {
            "ok": True,
            "ready": False,
            "chunks": 0,
            "auto_ingest": False,
            "ingesting": False,
        }

    with _AUTO_INGEST_LOCK:
        already_started = bool(_AUTO_INGEST_STATE.get("started") or _AUTO_INGEST_STATE.get("running"))

    if already_started:
        return {
            "ok": True,
            "ready": False,
            "chunks": 0,
            "auto_ingest": True,
            "ingesting": True,
        }

    if async_ingest:
        thread = threading.Thread(
            target=_auto_ingest_job,
            name="family-doctor-auto-ingest",
            daemon=True,
        )
        thread.start()
        print("[medical_rag] Auto ingest đang chạy trong nền.")
        return {
            "ok": True,
            "ready": False,
            "chunks": 0,
            "auto_ingest": True,
            "ingesting": True,
        }

    _auto_ingest_job()
    chunks = load_index_cache(force=True)
    return {
        "ok": True,
        "ready": bool(chunks),
        "chunks": len(chunks),
        "auto_ingest": True,
        "ingesting": False,
    }


# Khởi động worker ngay khi module được import, nhưng chưa xử lý gì cho tới khi có câu hỏi.
ensure_worker_started()
