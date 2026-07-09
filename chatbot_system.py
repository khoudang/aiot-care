"""
chatbot_system.py — Một chatbot AI duy nhất cho AIoT Care Station.

Mục tiêu:
  - Người dùng chỉ thấy 1 chatbot: "Trợ lý AI hệ thống".
  - Backend tự quyết định có cần dùng Medical RAG hay Web Search hay không.
  - Không còn chia mode medical/general/web ở frontend.

Cách hoạt động nội bộ:
  1. Câu hỏi sức khỏe / bệnh tật:
     - Thử lấy thêm ngữ cảnh từ medical_docs bằng Medical RAG.
     - Nếu tài liệu không đủ, vẫn có thể trả lời kiến thức tham khảo chung,
       nhưng phải nói rõ giới hạn và không chẩn đoán / kê đơn.
  2. Câu hỏi cần dữ liệu mới nhất:
     - Thử Web Search trước, sau đó dùng Gemini tổng hợp.
  3. Câu hỏi tổng quát:
     - Gọi Gemini trực tiếp, không retrieve tài liệu.

Thiết kế tối ưu Raspberry Pi:
  - Tất cả câu hỏi đi qua một queue nhỏ, một worker nền xử lý tuần tự.
  - Chatbot là tác vụ ưu tiên thấp, không block BLE/camera/UART/Socket.IO.
  - Có retry ngắn cho lỗi model quá tải: 429 / 503 / high demand.
"""

from __future__ import annotations

import html
import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests

import config as app_config


CHATBOT_QUEUE_SIZE = int(getattr(app_config, "CHATBOT_QUEUE_SIZE", 3))
CHATBOT_JOB_TTL_SEC = int(getattr(app_config, "CHATBOT_JOB_TTL_SEC", 900))
CHATBOT_MAX_QUESTION_CHARS = int(getattr(app_config, "CHATBOT_MAX_QUESTION_CHARS", 2000))
CHATBOT_WORKER_IDLE_SLEEP = float(getattr(app_config, "CHATBOT_WORKER_IDLE_SLEEP", 0.08))

GEMINI_API_KEY = getattr(app_config, "GEMINI_API_KEY", "")
GEMINI_CHAT_MODEL = getattr(app_config, "GEMINI_CHAT_MODEL", "gemini-2.5-flash-lite")
GEMINI_TIMEOUT = int(getattr(app_config, "MEDICAL_RAG_REQUEST_TIMEOUT", 45))
GEMINI_MAX_RETRIES = int(getattr(app_config, "GEMINI_MAX_RETRIES", 3))
GEMINI_RETRY_BASE_DELAY = float(getattr(app_config, "GEMINI_RETRY_BASE_DELAY", 1.2))
UNIFIED_CHAT_MAX_OUTPUT_TOKENS = int(
    getattr(
        app_config,
        "UNIFIED_CHAT_MAX_OUTPUT_TOKENS",
        getattr(app_config, "GENERAL_CHAT_MAX_OUTPUT_TOKENS", 900),
    )
)

WEB_SEARCH_ENABLE = bool(getattr(app_config, "WEB_SEARCH_ENABLE", True))
WEB_SEARCH_PROVIDER = getattr(app_config, "WEB_SEARCH_PROVIDER", "duckduckgo")
WEB_SEARCH_MAX_RESULTS = int(getattr(app_config, "WEB_SEARCH_MAX_RESULTS", 5))
WEB_SEARCH_TIMEOUT = int(getattr(app_config, "WEB_SEARCH_TIMEOUT", 8))
WEB_SEARCH_USER_AGENT = getattr(
    app_config,
    "WEB_SEARCH_USER_AGENT",
    "Mozilla/5.0 AIoT-Care-Station/1.0",
)


@dataclass
class WebResult:
    title: str
    url: str
    snippet: str = ""

    def as_dict(self) -> Dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet}


# ================================================================== #
#  Gemini client có retry & Lịch sử trò chuyện
# ================================================================== #
_CHAT_HISTORY = []
MAX_HISTORY_PAIRS = 5

def _api_key() -> str:
    key = (getattr(app_config, "GEMINI_API_KEY", "") or GEMINI_API_KEY or "").strip()
    if not key:
        raise RuntimeError(
            "Chưa cấu hình GEMINI_API_KEY. Hãy tạo API key Gemini hợp lệ và đặt trong file .env."
        )
    return key


def _gemini_generate_url() -> str:
    return (
        "https://generativelanguage.googleapis.com/v1beta/"
        f"models/{GEMINI_CHAT_MODEL}:generateContent"
        f"?key={_api_key()}"
    )


def _extract_gemini_answer(data: Dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates:
        return ""
    parts = candidates[0].get("content", {}).get("parts", [])
    texts = []
    for part in parts:
        text = (part.get("text") or "").strip()
        if text:
            texts.append(text)
    return "\n".join(texts).strip()


def _is_retryable_error(status_code: int, message: str) -> bool:
    msg = (message or "").lower()
    return (
        status_code in {429, 500, 502, 503, 504}
        or "high demand" in msg
        or "temporarily" in msg
        or "unavailable" in msg
        or "quota" in msg
    )


def call_gemini_generate(
    prompt: str,
    *,
    temperature: float = 0.35,
    max_output_tokens: int = 900,
) -> str:
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ],
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": int(max_output_tokens),
        },
    }

    last_error = ""
    attempts = max(1, GEMINI_MAX_RETRIES)

    for attempt in range(1, attempts + 1):
        try:
            resp = requests.post(_gemini_generate_url(), json=payload, timeout=GEMINI_TIMEOUT)
            data = resp.json() if resp.content else {}

            if resp.status_code >= 400:
                last_error = data.get("error", {}).get("message", "Lỗi Gemini generateContent API.")
                if attempt < attempts and _is_retryable_error(resp.status_code, last_error):
                    time.sleep(GEMINI_RETRY_BASE_DELAY * attempt)
                    continue
                raise RuntimeError(last_error)

            answer = _extract_gemini_answer(data)
            return answer or "Tôi chưa tạo được câu trả lời. Vui lòng thử lại."

        except requests.RequestException as exc:
            last_error = str(exc)
            if attempt < attempts:
                time.sleep(GEMINI_RETRY_BASE_DELAY * attempt)
                continue
            raise RuntimeError(f"Không kết nối được tới Gemini API: {last_error}")

    raise RuntimeError(last_error or "Gemini API xử lý thất bại.")


# ================================================================== #
#  Nhận diện nhu cầu nội bộ: y tế / web mới nhất
# ================================================================== #
_MEDICAL_KEYWORDS = {
    "sức khỏe", "benh", "bệnh", "triệu chứng", "dấu hiệu", "đi khám",
    "cấp cứu", "bác sĩ", "thuốc", "uống thuốc", "kê đơn", "đơn thuốc",
    "đau", "sốt", "ho", "khó thở", "đau ngực", "chóng mặt", "ngất",
    "co giật", "mệt", "mệt lả", "nôn", "tiêu chảy", "đau bụng",
    "huyết áp", "tiểu đường", "đường huyết", "tim mạch", "nhịp tim",
    "spo2", "oxy", "phổi", "gan", "thận", "dạ dày", "đột quỵ",
    "dị ứng", "viêm", "nhiễm", "vết thương", "chảy máu", "tai biến",
}

_WEB_FRESHNESS_KEYWORDS = {
    "mới nhất", "hiện tại", "bây giờ", "hôm nay", "hôm qua", "tuần này",
    "tháng này", "năm nay", "vừa rồi", "gần đây", "cập nhật", "tin tức",
    "release", "phiên bản", "version", "giá", "tỷ giá", "tỉ giá", "lãi suất",
    "lịch", "thời tiết", "cổ phiếu", "crypto", "bitcoin", "luật mới",
    "quy định mới", "chính sách mới", "2025", "2026", "2027",
}


def _norm_text(text: str) -> str:
    return (text or "").lower().strip()


def looks_medical_question(question: str) -> bool:
    q = _norm_text(question)
    return any(keyword in q for keyword in _MEDICAL_KEYWORDS)


def needs_web_search(question: str) -> bool:
    q = _norm_text(question)
    return any(keyword in q for keyword in _WEB_FRESHNESS_KEYWORDS)


# ================================================================== #
#  Web search không cần dependency ngoài requests
# ================================================================== #
def _clean_html(raw: str) -> str:
    text = re.sub(r"(?is)<script.*?</script>|<style.*?</style>", " ", raw or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return " ".join(text.split())


def _decode_duckduckgo_url(url: str) -> str:
    url = html.unescape(url or "").strip()
    if not url:
        return ""

    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("/"):
        url = "https://duckduckgo.com" + url

    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    if "uddg" in qs and qs["uddg"]:
        return unquote(qs["uddg"][0])
    return url


def search_web_duckduckgo(query: str, max_results: Optional[int] = None) -> List[WebResult]:
    if not WEB_SEARCH_ENABLE:
        return []

    max_results = int(max_results or WEB_SEARCH_MAX_RESULTS)
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    headers = {"User-Agent": WEB_SEARCH_USER_AGENT}

    resp = requests.get(url, headers=headers, timeout=WEB_SEARCH_TIMEOUT)
    resp.raise_for_status()
    html_text = resp.text

    anchor_re = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        re.I | re.S,
    )
    matches = list(anchor_re.finditer(html_text))
    results: List[WebResult] = []

    for i, match in enumerate(matches):
        raw_url = match.group(1)
        raw_title = match.group(2)
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else min(len(html_text), start + 2500)
        block = html_text[start:end]

        snippet = ""
        snip_match = re.search(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(.*?)</div>',
            block,
            re.I | re.S,
        )
        if snip_match:
            snippet = _clean_html(snip_match.group(1) or snip_match.group(2) or "")

        title = _clean_html(raw_title)
        real_url = _decode_duckduckgo_url(raw_url)

        if title and real_url and not real_url.startswith("https://duckduckgo.com/y.js"):
            results.append(WebResult(title=title, url=real_url, snippet=snippet))

        if len(results) >= max_results:
            break

    return results


def search_web(query: str, max_results: Optional[int] = None) -> List[WebResult]:
    provider = (WEB_SEARCH_PROVIDER or "duckduckgo").lower().strip()
    if provider != "duckduckgo":
        raise RuntimeError(f"WEB_SEARCH_PROVIDER={provider} chưa được hỗ trợ trong bản này.")
    return search_web_duckduckgo(query, max_results=max_results)


# ================================================================== #
#  Context Medical RAG dùng như tri thức bổ sung, không còn khóa chatbot
# ================================================================== #
def retrieve_medical_context_if_needed(question: str) -> tuple[List[Dict[str, Any]], str]:
    if not looks_medical_question(question):
        return [], ""

    try:
        from medical_rag import retrieve_context

        contexts = retrieve_context(question)
        return contexts or [], ""
    except Exception as exc:
        # Không để lỗi embedding/RAG làm chết chatbot tổng.
        return [], str(exc)


def build_medical_context_text(contexts: List[Dict[str, Any]]) -> str:
    if not contexts:
        return "Không có ngữ cảnh y tế nội bộ phù hợp."

    blocks = []
    for idx, ctx in enumerate(contexts, start=1):
        source = ctx.get("source", "unknown")
        chunk_index = ctx.get("chunk_index", "?")
        score = ctx.get("score")
        score_text = f" | score={score:.3f}" if isinstance(score, (int, float)) else ""
        text = (ctx.get("text") or "").strip()
        blocks.append(f"[{idx}] {source} - đoạn {chunk_index}{score_text}\n{text}")
    return "\n\n".join(blocks)


def build_web_context_text(web_results: List[WebResult], web_error: str = "") -> str:
    if web_results:
        lines = []
        for idx, item in enumerate(web_results, start=1):
            lines.append(
                f"[{idx}] {item.title}\nURL: {item.url}\nTóm tắt: {item.snippet or 'Không có mô tả ngắn.'}"
            )
        return "\n\n".join(lines)

    if web_error:
        return f"Không lấy được kết quả web. Lỗi: {web_error}"

    return "Không dùng web search cho câu hỏi này."


def build_unified_prompt(
    question: str,
    *,
    medical_contexts: List[Dict[str, Any]],
    medical_error: str,
    web_results: List[WebResult],
    web_error: str,
    used_web_search: bool,
    history: list = None,
) -> str:
    medical_context = build_medical_context_text(medical_contexts)
    web_context = build_web_context_text(web_results, web_error)

    history_text = ""
    if history:
        h_blocks = []
        for h in history:
            h_blocks.append(f"Người dùng: {h['question']}\nAI: {h['answer']}")
        history_text = "LỊCH SỬ TRÒ CHUYỆN GẦN ĐÂY:\n" + "\n\n".join(h_blocks) + "\n\n"

    medical_note = ""
    if medical_error:
        medical_note = f"\nLưu ý nội bộ: không truy xuất được Medical RAG vì: {medical_error}"

    web_note = ""
    if used_web_search and web_error:
        web_note = f"\nLưu ý nội bộ: người dùng có thể cần dữ liệu mới, nhưng web search lỗi: {web_error}"

    return f"""
Bạn là một trợ lý AI duy nhất của hệ thống AIoT Care Station.
Không nói với người dùng rằng có các mode khác nhau. Hãy tự chọn cách trả lời phù hợp.

Nguyên tắc chung:
- Trả lời bằng tiếng Việt, rõ ràng, thực tế, dễ hiểu.
- Hỗ trợ được nhiều chủ đề: sức khỏe, IoT, AI, lập trình, điện tử, học tập, dịch thuật, báo cáo và giải thích lỗi.
- Nếu câu hỏi là kiến thức tổng quát, trả lời trực tiếp bằng kiến thức của model.
- Nếu có NGỮ CẢNH Y TẾ NỘI BỘ phù hợp, ưu tiên dùng nó như tài liệu tham khảo.
- Nếu tài liệu y tế nội bộ không đủ, có thể bổ sung kiến thức phổ thông nhưng phải nói rõ đó là thông tin tham khảo.
- Với câu hỏi sức khỏe: không chẩn đoán chắc chắn, không kê đơn thuốc, không thay thế bác sĩ.
- Nếu có dấu hiệu nguy hiểm như đau ngực, khó thở, ngất, co giật, yếu liệt, sốt cao kéo dài, chảy máu nhiều, hãy khuyên liên hệ cơ sở y tế/cấp cứu.
- Nếu có KẾT QUẢ WEB, ưu tiên dữ liệu web cho thông tin mới nhất; không bịa số liệu, giá, lịch, luật hoặc phiên bản nếu nguồn không đủ.
- Chỉ thêm mục "Nguồn tham khảo" khi thực sự có kết quả web hoặc cần nhắc tài liệu tham khảo.
{medical_note}{web_note}

{history_text}
NGỮ CẢNH Y TẾ NỘI BỘ:
{medical_context}

KẾT QUẢ WEB:
{web_context}

CÂU HỎI NGƯỜI DÙNG:
{question}
""".strip()


# ================================================================== #
#  Answer sync cho một AI duy nhất
# ================================================================== #
def answer_chat_sync(question: str) -> Dict[str, Any]:
    global _CHAT_HISTORY
    medical_contexts, medical_error = retrieve_medical_context_if_needed(question)

    used_web_search = needs_web_search(question)
    web_results: List[WebResult] = []
    web_error = ""

    if used_web_search and WEB_SEARCH_ENABLE:
        try:
            web_results = search_web(question, max_results=WEB_SEARCH_MAX_RESULTS)
        except Exception as exc:
            web_error = str(exc)
    elif used_web_search and not WEB_SEARCH_ENABLE:
        web_error = "WEB_SEARCH_ENABLE=0"

    prompt = build_unified_prompt(
        question,
        medical_contexts=medical_contexts,
        medical_error=medical_error,
        web_results=web_results,
        web_error=web_error,
        used_web_search=used_web_search,
        history=_CHAT_HISTORY,
    )

    # Nhiệt độ vừa phải để một trợ lý duy nhất có thể trả lời rộng nhưng vẫn ổn định.
    answer = call_gemini_generate(
        prompt,
        temperature=0.4,
        max_output_tokens=UNIFIED_CHAT_MAX_OUTPUT_TOKENS,
    )

    _CHAT_HISTORY.append({"question": question, "answer": answer})
    if len(_CHAT_HISTORY) > MAX_HISTORY_PAIRS:
        _CHAT_HISTORY.pop(0)

    return {
        "answer": answer,
        "sources": [
            {
                "source": ctx.get("source"),
                "chunk_index": ctx.get("chunk_index"),
                "score": ctx.get("score"),
            }
            for ctx in medical_contexts
        ],
        "web_results": [item.as_dict() for item in web_results],
    }


# ================================================================== #
#  Queue worker chung cho chatbot duy nhất
# ================================================================== #
_CHAT_QUEUE: queue.Queue[str] = queue.Queue(maxsize=CHATBOT_QUEUE_SIZE)
_JOBS: Dict[str, Dict[str, Any]] = {}
_JOBS_LOCK = threading.Lock()
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


def _cleanup_jobs() -> None:
    now = time.time()
    with _JOBS_LOCK:
        old_ids = [
            job_id for job_id, job in _JOBS.items()
            if now - float(job.get("created_at", now)) > CHATBOT_JOB_TTL_SEC
        ]
        for job_id in old_ids:
            _JOBS.pop(job_id, None)


def _worker_loop() -> None:
    while True:
        job_id = _CHAT_QUEUE.get()

        try:
            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if not job:
                    continue
                job["status"] = "running"
                job["updated_at"] = time.time()

            result = answer_chat_sync(job["question"])

            with _JOBS_LOCK:
                job = _JOBS.get(job_id)
                if job:
                    job["status"] = "done"
                    job["answer"] = result.get("answer", "")
                    job["sources"] = result.get("sources", [])
                    job["web_results"] = result.get("web_results", [])
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
            time.sleep(CHATBOT_WORKER_IDLE_SLEEP)


def ensure_worker_started() -> None:
    global _WORKER_STARTED

    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return

        thread = threading.Thread(
            target=_worker_loop,
            name="aiot-unified-chatbot-worker",
            daemon=True,
        )
        thread.start()
        _WORKER_STARTED = True


def init_unified_chatbot() -> None:
    """Gọi ở app.py nếu muốn worker chatbot chạy ngay khi app start."""
    ensure_worker_started()


def submit_chat_question(question: str, user_id: Optional[int] = None, **_ignored: Any) -> Dict[str, Any]:
    ensure_worker_started()

    q = (question or "").strip()

    if not q:
        return {"ok": False, "message": "Vui lòng nhập câu hỏi."}

    if len(q) > CHATBOT_MAX_QUESTION_CHARS:
        return {
            "ok": False,
            "message": f"Câu hỏi quá dài. Vui lòng rút gọn dưới {CHATBOT_MAX_QUESTION_CHARS} ký tự.",
        }

    _cleanup_jobs()

    if _CHAT_QUEUE.full():
        return {
            "ok": False,
            "message": "Chatbot đang xử lý câu hỏi khác. Vui lòng thử lại sau vài giây.",
        }

    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "status": "queued",
        "question": q,
        "answer": None,
        "sources": [],
        "web_results": [],
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
            "message": "Chatbot đang bận. Vui lòng thử lại sau vài giây.",
        }

    return {"ok": True, "status": "queued", "job_id": job_id}


def get_chat_job(job_id: str) -> Optional[Dict[str, Any]]:
    _cleanup_jobs()

    with _JOBS_LOCK:
        job = _JOBS.get(job_id)
        if not job:
            return None

        return {
            "id": job["id"],
            "status": job["status"],
            "answer": job.get("answer") or "",
            "sources": job.get("sources") or [],
            "web_results": job.get("web_results") or [],
            "message": job.get("message") or "",
            "created_at": job.get("created_at"),
            "updated_at": job.get("updated_at"),
        }
