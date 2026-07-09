from flask import Flask
from flask_socketio import SocketIO

import iot
from config import SECRET_KEY
from database import init_db, seed_initial_users
from web import register_web


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
iot.start_background_services()


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=5000, debug=False)