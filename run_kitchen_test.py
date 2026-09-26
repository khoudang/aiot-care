"""Run the dashboard on Windows with only the kitchen BLE node enabled."""

import os
from pathlib import Path
import secrets
import sys


def main():
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    os.chdir(Path(__file__).resolve().parent)
    os.environ.update({
        "DATABASE": "kitchen-test.db",
        "SECRET_KEY": secrets.token_hex(32),
        "UART_ENABLE": "0",
        "CAMERA_MODE_DEFAULT": "off",
        "MEDICAL_RAG_AUTO_INGEST": "0",
    })

    import config

    config.NODES[:] = [node for node in config.NODES if node["room"] == "kitchen"]

    from app import app, socketio

    socketio.run(app, host="127.0.0.1", port=5000, debug=False,
                 allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
