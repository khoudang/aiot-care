"""
Cấu hình hệ thống AIoT Care Station.

Kiến trúc truyền dữ liệu: BLE (Bluetooth Low Energy) cho cả 3 node cảm biến,
và UART (serial) để gửi góc quay servo tracking người ở phòng bệnh.
KHÔNG dùng MQTT.
"""

import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass


# ------------------------------------------------------------------ #
#  Ứng dụng / phiên / cơ sở dữ liệu
# ------------------------------------------------------------------ #
SECRET_KEY = os.getenv("SECRET_KEY", "smart_home_secret_key_2026_change_me")
DATABASE = os.getenv("DATABASE", "smart_home.db")
ALLOW_REGISTER = os.getenv("ALLOW_REGISTER", "1") == "1"

INITIAL_USERS = [
    {"username": "admin", "password": "admin123", "role": "admin"},
    {"username": "khoi", "password": "khoi1234", "role": "member"},
    {"username": "dien", "password": "dien1234", "role": "member"},
    {"username": "khang", "password": "khang1234", "role": "member"},
]

DEFAULT_CONFIGS = {
    "admin_register_code": os.getenv("ADMIN_REGISTER_CODE", "FAMILY2026"),
    "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
    "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
}


# ------------------------------------------------------------------ #
#  BLE — ba node cảm biến
#  Mỗi node là một ESP32 quảng bá BLE. Pi kết nối cả ba theo MAC.
#  Có thể dùng chung UUID notify/command nếu firmware ba node giống nhau,
#  hoặc override riêng cho từng node bằng biến môi trường.
# ------------------------------------------------------------------ #
BLE_NOTIFY_UUID = os.getenv("BLE_NOTIFY_UUID", "beb5483e-36e1-4688-b7f5-ea07361b26a8")
BLE_COMMAND_UUID = os.getenv("BLE_COMMAND_UUID", "1c95d5e3-d03b-4c71-b54d-172fa5545a74")

NODES = [
    {
        "room": "patient",
        "name": "Phòng người bệnh",
        "mac": os.getenv("BLE_MAC_PATIENT", "a0:f2:62:a5:6d:16"),
        "notify_uuid": os.getenv("BLE_NOTIFY_UUID_PATIENT", BLE_NOTIFY_UUID),
        "command_uuid": os.getenv("BLE_COMMAND_UUID_PATIENT", BLE_COMMAND_UUID),
    },
    {
        "room": "living",
        "name": "Phòng khách",
        "mac": os.getenv("BLE_MAC_LIVING", "a0:f2:62:a5:6d:17"),
        "notify_uuid": os.getenv("BLE_NOTIFY_UUID_LIVING", BLE_NOTIFY_UUID),
        "command_uuid": os.getenv("BLE_COMMAND_UUID_LIVING", BLE_COMMAND_UUID),
    },
    {
        "room": "kitchen",
        "name": "Phòng bếp",
        "mac": os.getenv("BLE_MAC_KITCHEN", "E8:3D:C1:9D:A5:16"),
        "notify_uuid": os.getenv("BLE_NOTIFY_UUID_KITCHEN", BLE_NOTIFY_UUID),
        "command_uuid": os.getenv("BLE_COMMAND_UUID_KITCHEN", BLE_COMMAND_UUID),
    },
    {
        # Node thứ 4: Gateway nhận dữ liệu BLE từ vòng đeo tay (MAX30102)
        # đọc nhịp tim + SpO2, rồi gửi tiếp lên Pi qua BLE.
        "room": "wearable",
        "name": "Vòng đeo sức khỏe",
        "mac": os.getenv("BLE_MAC_WEARABLE", "a0:f2:62:a5:6d:19"),
        "notify_uuid": os.getenv("BLE_NOTIFY_UUID_WEARABLE", BLE_NOTIFY_UUID),
        "command_uuid": os.getenv("BLE_COMMAND_UUID_WEARABLE", BLE_COMMAND_UUID),
    },
]

# Alias tương thích ngược (một số script cũ có thể tham chiếu)
TARGET_MAC = NODES[0]["mac"]
CHARACTERISTIC_UUID = BLE_NOTIFY_UUID
COMMAND_UUID = BLE_COMMAND_UUID

BLE_RECONNECT_DELAY = float(os.getenv("BLE_RECONNECT_DELAY", "3"))


# ------------------------------------------------------------------ #
#  UART — gửi góc servo tracking (Pi -> ESP(1) điều khiển servo pan)
#  Khung gửi: "A<angle>\n"  (ví dụ "A090\n"). Firmware ESP(1) parse góc.
# ------------------------------------------------------------------ #
UART_ENABLE = os.getenv("UART_ENABLE", "1") == "1"
UART_PORT = os.getenv("UART_PORT", "/dev/ttyUSB0")   # hoặc /dev/serial0 trên Pi GPIO
UART_BAUD = int(os.getenv("UART_BAUD", "115200"))

SERVO_MIN = int(os.getenv("SERVO_MIN", "0"))
SERVO_MAX = int(os.getenv("SERVO_MAX", "180"))
SERVO_CENTER = int(os.getenv("SERVO_CENTER", "90"))
SERVO_KP = float(os.getenv("SERVO_KP", "0.06"))          # hệ số điều khiển tỉ lệ
SERVO_DEADZONE_PX = int(os.getenv("SERVO_DEADZONE_PX", "24"))  # vùng chết quanh tâm (px)
SERVO_SMOOTHING = float(os.getenv("SERVO_SMOOTHING", "0.35"))  # EMA làm mượt (0..1)
SERVO_INVERT = os.getenv("SERVO_INVERT", "0") == "1"     # đảo chiều nếu servo quay ngược
SERVO_SEND_INTERVAL = float(os.getenv("SERVO_SEND_INTERVAL", "0.08"))  # tối đa ~12 Hz


# ------------------------------------------------------------------ #
#  Camera + AI (chỉ ở phòng người bệnh)
# ------------------------------------------------------------------ #
VIDEO_SOURCE = int(os.getenv("VIDEO_SOURCE", "0"))
CAMERA_WIDTH = int(os.getenv("CAMERA_WIDTH", "320"))
CAMERA_HEIGHT = int(os.getenv("CAMERA_HEIGHT", "240"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "65"))
PROCESS_EVERY_N_FRAMES = int(os.getenv("PROCESS_EVERY_N_FRAMES", "3"))  # cử chỉ chạy mỗi N frame
STREAM_SLEEP = float(os.getenv("STREAM_SLEEP", "0.01"))
STATUS_EMIT_INTERVAL = float(os.getenv("STATUS_EMIT_INTERVAL", "0.2"))

ENABLE_GESTURE = os.getenv("ENABLE_GESTURE", "1") == "1"
ENABLE_TRACKING = os.getenv("ENABLE_TRACKING", "1") == "1"
ENABLE_FALL = os.getenv("ENABLE_FALL", "1") == "1"

# Camera bật theo PIR: "auto" = tự bật khi có chuyển động, tự tắt sau timeout.
CAMERA_MODE_DEFAULT = os.getenv("CAMERA_MODE_DEFAULT", "auto")  # auto | on | off
CAMERA_MOTION_TIMEOUT = float(os.getenv("CAMERA_MOTION_TIMEOUT", "20"))  # giây không thấy PIR -> tắt

# Phát hiện té ngã (heuristic từ pose)
FALL_HOLD_SEC = float(os.getenv("FALL_HOLD_SEC", "3.5"))      # giữ tư thế bất thường bao lâu mới báo
FALL_TORSO_DEG = float(os.getenv("FALL_TORSO_DEG", "55"))     # góc thân so với phương đứng
FALL_ASPECT = float(os.getenv("FALL_ASPECT", "1.1"))         # tỉ lệ rộng/cao bbox


# ------------------------------------------------------------------ #
#  Điều khiển / cảnh báo
# ------------------------------------------------------------------ #
COMMAND_DEBOUNCE_SEC = float(os.getenv("COMMAND_DEBOUNCE_SEC", "1.0"))
GESTURE_COOLDOWN_SEC = float(os.getenv("GESTURE_COOLDOWN_SEC", "1.2"))
MAX_HISTORY = int(os.getenv("MAX_HISTORY", "30"))
ALERT_COOLDOWN_SEC = float(os.getenv("ALERT_COOLDOWN_SEC", "60"))

# Ngưỡng khí gas (đơn vị ADC/ppm tùy cảm biến). Lọc bằng trung bình trượt trong iot.py.
GAS_WARN_THRESHOLD = float(os.getenv("GAS_WARN_THRESHOLD", "1500"))
GAS_HIGH_THRESHOLD = float(os.getenv("GAS_HIGH_THRESHOLD", "2500"))
GAS_SMOOTH_WINDOW = int(os.getenv("GAS_SMOOTH_WINDOW", "5"))


# ------------------------------------------------------------------ #
#  Ngưỡng sức khỏe (vòng đeo MAX30102: nhịp tim + SpO2)
#  Vượt ngưỡng -> cảnh báo hệ thống + gửi Telegram.
# ------------------------------------------------------------------ #
SPO2_WARN = float(os.getenv("SPO2_WARN", "95"))          # SpO2 < 95% -> bất ổn
SPO2_CRITICAL = float(os.getenv("SPO2_CRITICAL", "90"))  # SpO2 < 90% -> nguy hiểm
HR_LOW = float(os.getenv("HR_LOW", "50"))                # nhịp tim < 50 bpm -> chậm bất thường
HR_HIGH = float(os.getenv("HR_HIGH", "120"))             # nhịp tim > 120 bpm -> nhanh bất thường
HEALTH_HOLD_SEC = float(os.getenv("HEALTH_HOLD_SEC", "6"))  # giữ bất thường bao lâu mới báo (giảm nhiễu)

# ------------------------------------------------------------------ #
#  AI / Medical RAG - Chatbot "Bác sĩ gia đình"
#  Khuyến nghị: đặt GEMINI_API_KEY trong biến môi trường hoặc file .env.
#  Không nên hard-code API key trực tiếp vào mã nguồn khi đưa lên Git.
# ------------------------------------------------------------------ #
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash-lite")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

MEDICAL_DOCS_DIR = os.getenv("MEDICAL_DOCS_DIR", "medical_docs")
MEDICAL_INDEX_DB = os.getenv("MEDICAL_INDEX_DB", "medical_index/medical_rag.db")
MEDICAL_RAG_TOP_K = int(os.getenv("MEDICAL_RAG_TOP_K", "5"))

# Tối ưu cho Raspberry Pi 4:
# - Chỉ chạy 1 worker chatbot nền, tránh tranh CPU với BLE/camera/Socket.IO.
# - Queue nhỏ để không dồn nhiều câu hỏi cùng lúc làm treo hệ thống.
# - Context giới hạn để giảm token và giảm thời gian gọi Gemini.
MEDICAL_RAG_QUEUE_SIZE = int(os.getenv("MEDICAL_RAG_QUEUE_SIZE", "2"))
MEDICAL_RAG_JOB_TTL_SEC = int(os.getenv("MEDICAL_RAG_JOB_TTL_SEC", "900"))
MEDICAL_RAG_MAX_CONTEXT_CHARS = int(os.getenv("MEDICAL_RAG_MAX_CONTEXT_CHARS", "6500"))
MEDICAL_RAG_CHUNK_SIZE = int(os.getenv("MEDICAL_RAG_CHUNK_SIZE", "900"))
MEDICAL_RAG_CHUNK_OVERLAP = int(os.getenv("MEDICAL_RAG_CHUNK_OVERLAP", "160"))
MEDICAL_RAG_REQUEST_TIMEOUT = int(os.getenv("MEDICAL_RAG_REQUEST_TIMEOUT", "45"))
MEDICAL_RAG_WORKER_IDLE_SLEEP = float(os.getenv("MEDICAL_RAG_WORKER_IDLE_SLEEP", "0.08"))
MEDICAL_RAG_AUTO_INGEST = os.getenv("MEDICAL_RAG_AUTO_INGEST", "1") == "1"
MEDICAL_RAG_AUTO_INGEST_ASYNC = os.getenv("MEDICAL_RAG_AUTO_INGEST_ASYNC", "1") == "1"

# ------------------------------------------------------------------ #
#  Chatbot AI hệ thống — một trợ lý duy nhất
#  - Không còn chia mode ở frontend.
#  - Backend tự dùng Medical RAG khi câu hỏi liên quan sức khỏe.
#  - Backend tự dùng Web Search khi câu hỏi cần dữ liệu mới nhất.
#  - Còn lại gọi LLM trực tiếp.
# ------------------------------------------------------------------ #
CHATBOT_QUEUE_SIZE = int(os.getenv("CHATBOT_QUEUE_SIZE", "3"))
CHATBOT_JOB_TTL_SEC = int(os.getenv("CHATBOT_JOB_TTL_SEC", "900"))
CHATBOT_MAX_QUESTION_CHARS = int(os.getenv("CHATBOT_MAX_QUESTION_CHARS", "2000"))
CHATBOT_WORKER_IDLE_SLEEP = float(os.getenv("CHATBOT_WORKER_IDLE_SLEEP", "0.08"))

UNIFIED_CHAT_MAX_OUTPUT_TOKENS = int(os.getenv("UNIFIED_CHAT_MAX_OUTPUT_TOKENS", "900"))
GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
GEMINI_RETRY_BASE_DELAY = float(os.getenv("GEMINI_RETRY_BASE_DELAY", "1.2"))

# Web Search chỉ dùng khi backend nhận thấy câu hỏi cần thông tin mới/cập nhật.
# Mặc định dùng DuckDuckGo HTML, không cần thêm dependency ngoài requests.
WEB_SEARCH_ENABLE = os.getenv("WEB_SEARCH_ENABLE", "1") == "1"
WEB_SEARCH_PROVIDER = os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo")
WEB_SEARCH_MAX_RESULTS = int(os.getenv("WEB_SEARCH_MAX_RESULTS", "5"))
WEB_SEARCH_TIMEOUT = int(os.getenv("WEB_SEARCH_TIMEOUT", "8"))
WEB_SEARCH_USER_AGENT = os.getenv(
    "WEB_SEARCH_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AIoT-Care-Station/1.0",
)

