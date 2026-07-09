from flask import Flask
from flask_socketio import SocketIO

import iot
from config import SECRET_KEY
from database import init_db, seed_initial_users
from web import register_web
from medical_rag import init_medical_rag
from chatbot_system import init_unified_chatbot


app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode="threading",
    manage_session=False,
)

iot.init_iot(socketio)
register_web(app, socketio)

init_db()
seed_initial_users()

# Ưu tiên start các service IoT trước
iot.start_background_services()

# Sau đó chuẩn bị Medical RAG nền.
# Nếu medical_index/medical_rag.db chưa có dữ liệu, hệ thống có thể tự nạp RAG trong nền.
init_medical_rag()

# Start worker của chatbot AI duy nhất.
# Không bắt buộc vì worker có thể tự start khi có câu hỏi đầu tiên,
# nhưng gọi ở đây giúp request đầu tiên không phải khởi tạo thread.
init_unified_chatbot()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)