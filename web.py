import time

from flask import (
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

import iot
from medical_rag import get_medical_job, submit_medical_question
from config import ALLOW_REGISTER
from database import (
    admin_required,
    create_user,
    fetch_admin_users,
    fetch_audit_logs,
    fetch_login_logs,
    get_config_value,
    get_current_user,
    get_db_connection,
    get_user_by_username,
    log_audit,
    log_login,
    login_required,
    set_config_value,
    socket_auth_required,
    fetch_gesture_mappings,
    upsert_gesture_mapping,
    delete_gesture_mapping,
    clear_login_logs,
    clear_audit_logs,
    fetch_kitchen_alerts,
)


def get_client_ip():
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def is_admin_self_target(target_user_id):
    current_user_id = session.get("user_id")
    return current_user_id is not None and int(current_user_id) == int(target_user_id)


def register_web(app, socketio):
    # ----------------------------------------------------------------- #
    #  Trang / xác thực
    # ----------------------------------------------------------------- #
    @app.route("/")
    def root():
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if "user_id" in session:
            return redirect(url_for("dashboard"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()

            if not username or not password:
                flash("Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu.", "error")
                return render_template("login.html", allow_register=ALLOW_REGISTER)

            user = get_user_by_username(username)

            if user and int(user["is_suspended"]) == 1:
                flash("Tài khoản của bạn đang bị khóa. Vui lòng liên hệ admin.", "error")
                return render_template("login.html", allow_register=ALLOW_REGISTER)

            if user and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                session["username"] = user["username"]
                session["role"] = user["role"]

                log_login(user["id"], get_client_ip())
                log_audit("Đăng nhập hệ thống", user_id=user["id"])

                flash("Đăng nhập thành công.", "success")
                return redirect(url_for("dashboard"))

            flash("Sai tên đăng nhập hoặc mật khẩu.", "error")

        return render_template("login.html", allow_register=ALLOW_REGISTER)

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if not ALLOW_REGISTER:
            flash("Chức năng tạo tài khoản hiện đang tắt.", "error")
            return redirect(url_for("login"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "").strip()
            confirm_password = request.form.get("confirm_password", "").strip()
            register_code = request.form.get("register_code", "").strip()
            admin_register_code = get_config_value("admin_register_code", "FAMILY2026")

            if not username or not password or not confirm_password or not register_code:
                flash("Vui lòng nhập đầy đủ thông tin.", "error")
                return render_template("register.html")

            if len(username) < 3:
                flash("Tên đăng nhập phải từ 3 ký tự trở lên.", "error")
                return render_template("register.html")

            if len(password) < 6:
                flash("Mật khẩu phải từ 6 ký tự trở lên.", "error")
                return render_template("register.html")

            if password != confirm_password:
                flash("Mật khẩu xác nhận không khớp.", "error")
                return render_template("register.html")

            if register_code != admin_register_code:
                flash("Mã nội bộ không đúng.", "error")
                return render_template("register.html")

            if get_user_by_username(username):
                flash("Tên đăng nhập đã tồn tại.", "error")
                return render_template("register.html")

            try:
                create_user(username, password, role="member")
                log_audit(f"Tạo tài khoản mới: {username}", user_id=None)
                flash("Tạo tài khoản thành công. Hãy đăng nhập để sử dụng hệ thống.", "success")
                return redirect(url_for("login"))
            except Exception as exc:
                flash(f"Lỗi tạo tài khoản: {exc}", "error")

        return render_template("register.html")

    @app.route("/logout")
    def logout():
        user_id = session.get("user_id")
        if user_id:
            log_audit("Đăng xuất hệ thống", user_id=user_id)
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        user = get_current_user()
        return render_template("index.html", username=user["username"], role=user["role"])

    # ----------------------------------------------------------------- #
    #  Video stream (MJPEG) — chỉ khi camera đang bật
    # ----------------------------------------------------------------- #
    @app.route("/video_feed")
    @login_required
    def video_feed():
        def generate():
            iot.add_viewer()
            try:
                while True:
                    if not iot.is_camera_active():
                        time.sleep(0.1)
                        continue
                    frame = iot.get_latest_frame()
                    if frame:
                        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
                    time.sleep(0.03)
            finally:
                iot.remove_viewer()

        return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.route("/api/history")
    @login_required
    def api_history():
        return jsonify(iot.snapshot_histories())

    @app.route("/api/state")
    @login_required
    def api_state():
        return jsonify(iot.snapshot_all())


    # ----------------------------------------------------------------- #
    #  Chatbot y tế RAG — "Bác sĩ gia đình"
    #  Câu hỏi được đưa vào worker nền để không làm nghẽn luồng realtime.
    # ----------------------------------------------------------------- #
    @app.route("/api/medical_chat", methods=["POST"])
    @login_required
    def api_medical_chat():
        payload = request.get_json(silent=True) or {}
        question = (payload.get("message") or "").strip()

        result = submit_medical_question(
            question,
            user_id=session.get("user_id"),
        )

        if not result.get("ok"):
            return jsonify(result), 429

        return jsonify(result), 202

    @app.route("/api/medical_chat/result/<job_id>", methods=["GET"])
    @login_required
    def api_medical_chat_result(job_id):
        job = get_medical_job(job_id)

        if not job:
            return jsonify({
                "ok": False,
                "status": "not_found",
                "message": "Không tìm thấy tác vụ chatbot hoặc tác vụ đã hết hạn."
            }), 404

        if job["status"] in {"queued", "running"}:
            return jsonify({
                "ok": True,
                "status": job["status"],
                "message": "Bác sĩ gia đình đang tra cứu tài liệu y tế..."
            })

        if job["status"] == "done":
            return jsonify({
                "ok": True,
                "status": "done",
                "answer": job.get("answer") or "",
                "sources": job.get("sources") or [],
            })

        return jsonify({
            "ok": False,
            "status": "error",
            "message": job.get("message") or "Chatbot y tế xử lý thất bại."
        }), 500

    # ---- Ánh xạ cử chỉ (Yêu cầu 2) ----
    @app.route("/api/gesture_mappings", methods=["GET"])
    @login_required
    def api_gesture_mappings_get():
        return jsonify({
            "ok": True,
            "mappings": fetch_gesture_mappings(),
            "options": iot.available_gesture_options(),
        })

    @app.route("/api/gesture_mappings", methods=["POST"])
    @login_required
    def api_gesture_mappings_post():
        payload = request.get_json(silent=True) or {}
        gesture = (payload.get("gesture_name") or "").strip()
        device = (payload.get("target_device") or "").strip()
        action = (payload.get("action") or "").strip()

        valid_gestures = {g["key"] for g in iot.available_gesture_options()["gestures"]}
        valid_devices = {d["key"] for d in iot.available_gesture_options()["devices"]}
        valid_actions = {a["key"] for a in iot.available_gesture_options()["actions"]}

        if gesture not in valid_gestures:
            return jsonify({"ok": False, "message": "Cử chỉ không hợp lệ."}), 400
        if device not in valid_devices:
            return jsonify({"ok": False, "message": "Thiết bị không hợp lệ."}), 400
        if action not in valid_actions:
            return jsonify({"ok": False, "message": "Hành động không hợp lệ."}), 400

        upsert_gesture_mapping(gesture, device, action)
        iot.reload_gesture_map()
        log_audit(f"Cập nhật cử chỉ: {gesture} -> {device}/{action}", user_id=session.get("user_id"))
        return jsonify({"ok": True, "message": "Đã lưu ánh xạ cử chỉ.", "mappings": fetch_gesture_mappings()})

    @app.route("/api/gesture_mappings/<gesture_name>", methods=["DELETE"])
    @login_required
    def api_gesture_mappings_delete(gesture_name):
        delete_gesture_mapping(gesture_name.strip())
        iot.reload_gesture_map()
        log_audit(f"Xóa ánh xạ cử chỉ: {gesture_name}", user_id=session.get("user_id"))
        return jsonify({"ok": True, "message": "Đã xóa.", "mappings": fetch_gesture_mappings()})

    # ---- Lịch sử cảnh báo phòng bếp (Yêu cầu 4) ----
    @app.route("/api/kitchen_alerts", methods=["GET"])
    @login_required
    def api_kitchen_alerts():
        return jsonify({"ok": True, "alerts": fetch_kitchen_alerts(50)})

    # ----------------------------------------------------------------- #
    #  Admin REST (giữ nguyên)
    # ----------------------------------------------------------------- #
    @app.route("/api/admin/users", methods=["GET"])
    @admin_required
    def api_admin_users():
        return jsonify({"ok": True, "users": fetch_admin_users()})

    @app.route("/api/admin/users/<int:user_id>/edit", methods=["POST"])
    @admin_required
    def api_admin_edit_user(user_id):
        payload = request.get_json(silent=True) or {}
        new_username = (payload.get("username") or "").strip()
        new_password = (payload.get("password") or "").strip()

        if not new_username:
            return jsonify({"ok": False, "message": "Tên đăng nhập không được để trống."}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("select * from users where id = ?", (user_id,))
        target_user = cur.fetchone()

        if not target_user:
            conn.close()
            return jsonify({"ok": False, "message": "Không tìm thấy tài khoản."}), 404

        cur.execute("select id from users where username = ? and id != ?", (new_username, user_id))
        if cur.fetchone():
            conn.close()
            return jsonify({"ok": False, "message": "Tên đăng nhập đã tồn tại."}), 409

        if new_password:
            cur.execute(
                "update users set username = ?, password_hash = ? where id = ?",
                (new_username, generate_password_hash(new_password), user_id),
            )
        else:
            cur.execute("update users set username = ? where id = ?", (new_username, user_id))

        conn.commit()
        conn.close()

        log_audit(f"Sửa tài khoản id={user_id}, username={new_username}", user_id=session.get("user_id"))
        return jsonify({"ok": True, "message": "Cập nhật tài khoản thành công.", "users": fetch_admin_users()})

    @app.route("/api/admin/users/<int:user_id>/suspend", methods=["POST"])
    @admin_required
    def api_admin_suspend_user(user_id):
        if is_admin_self_target(user_id):
            return jsonify({"ok": False, "message": "Admin không thể tự khóa/mở khóa chính mình."}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("select * from users where id = ?", (user_id,))
        target_user = cur.fetchone()

        if not target_user:
            conn.close()
            return jsonify({"ok": False, "message": "Không tìm thấy tài khoản."}), 404

        next_status = 0 if int(target_user["is_suspended"]) == 1 else 1
        cur.execute("update users set is_suspended = ? where id = ?", (next_status, user_id))
        conn.commit()
        conn.close()

        action_text = "Mở khóa tài khoản" if next_status == 0 else "Khóa tài khoản"
        log_audit(f"{action_text}: id={user_id}, username={target_user['username']}", user_id=session.get("user_id"))
        return jsonify({"ok": True, "message": f"{action_text} thành công.", "users": fetch_admin_users()})

    @app.route("/api/admin/users/<int:user_id>", methods=["DELETE"])
    @admin_required
    def api_admin_delete_user(user_id):
        if is_admin_self_target(user_id):
            return jsonify({"ok": False, "message": "Admin không thể tự xóa chính mình."}), 400

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("select * from users where id = ?", (user_id,))
        target_user = cur.fetchone()

        if not target_user:
            conn.close()
            return jsonify({"ok": False, "message": "Không tìm thấy tài khoản."}), 404

        username = target_user["username"]
        cur.execute("delete from login_logs where user_id = ?", (user_id,))
        cur.execute("delete from audit_logs where user_id = ?", (user_id,))
        cur.execute("delete from users where id = ?", (user_id,))
        conn.commit()
        conn.close()

        log_audit(f"Xóa tài khoản: id={user_id}, username={username}", user_id=session.get("user_id"))
        return jsonify({"ok": True, "message": "Xóa tài khoản thành công.", "users": fetch_admin_users()})

    @app.route("/api/admin/logs", methods=["GET"])
    @admin_required
    def api_admin_logs():
        return jsonify({"ok": True, "login_logs": fetch_login_logs(), "audit_logs": fetch_audit_logs()})

    @app.route("/api/admin/logs", methods=["DELETE"])
    @admin_required
    def api_admin_logs_clear():
        payload = request.get_json(silent=True) or {}
        target = (payload.get("target") or "all").strip()
        if target in ("login", "all"):
            clear_login_logs()
        if target in ("audit", "all"):
            clear_audit_logs()
        log_audit(f"Xóa lịch sử ({target})", user_id=session.get("user_id"))
        return jsonify({
            "ok": True,
            "message": "Đã xóa lịch sử.",
            "login_logs": fetch_login_logs(),
            "audit_logs": fetch_audit_logs(),
        })

    @app.route("/api/admin/configs", methods=["GET", "POST"])
    @admin_required
    def api_admin_configs():
        if request.method == "GET":
            return jsonify({
                "ok": True,
                "configs": {
                    "admin_register_code": get_config_value("admin_register_code", ""),
                    "telegram_bot_token": get_config_value("telegram_bot_token", ""),
                    "telegram_chat_id": get_config_value("telegram_chat_id", ""),
                },
            })

        payload = request.get_json(silent=True) or {}
        admin_register_code = (payload.get("admin_register_code") or "").strip()
        telegram_bot_token = (payload.get("telegram_bot_token") or "").strip()
        telegram_chat_id = (payload.get("telegram_chat_id") or "").strip()

        if not admin_register_code:
            return jsonify({"ok": False, "message": "Mã đăng ký admin không được để trống."}), 400

        set_config_value("admin_register_code", admin_register_code)
        set_config_value("telegram_bot_token", telegram_bot_token)
        set_config_value("telegram_chat_id", telegram_chat_id)

        log_audit("Cập nhật cấu hình hệ thống", user_id=session.get("user_id"))
        return jsonify({
            "ok": True,
            "message": "Cập nhật cấu hình thành công.",
            "configs": {
                "admin_register_code": admin_register_code,
                "telegram_bot_token": telegram_bot_token,
                "telegram_chat_id": telegram_chat_id,
            },
        })

    # ----------------------------------------------------------------- #
    #  Socket.IO — realtime (BLE, không MQTT)
    # ----------------------------------------------------------------- #
    @socketio.on("connect")
    def handle_connect():
        if "user_id" not in session:
            return False
        return None

    @socketio.on("request_initial_state")
    def handle_request_initial_state():
        if not socket_auth_required():
            return
        iot.emit_full_state()

    @socketio.on("set_device")
    def handle_set_device(data):
        if not socket_auth_required():
            return
        data = data or {}
        iot.set_device(
            room=data.get("room"),
            device=data.get("device"),
            state=data.get("state"),
            value=data.get("value"),
            source="manual",
            user_id=session.get("user_id"),
        )

    @socketio.on("set_camera_mode")
    def handle_set_camera_mode(data):
        if not socket_auth_required():
            return
        mode = (data or {}).get("mode", "auto")
        result = iot.set_camera_mode(mode, user_id=session.get("user_id"))
        log_audit(f"Đặt chế độ camera: {mode}", user_id=session.get("user_id"))
        socketio.emit("camera_sync", {"active": result["active"], "mode": result["mode"]})

    @socketio.on("set_tracking")
    def handle_set_tracking(data):
        if not socket_auth_required():
            return
        enabled = bool((data or {}).get("enabled", True))
        iot.set_tracking(enabled, user_id=session.get("user_id"))

    @socketio.on("confirm_safe")
    def handle_confirm_safe(_data):
        if not socket_auth_required():
            return
        iot.confirm_safe(user_id=session.get("user_id"))

    # ---- Tương thích ngược ----
    @socketio.on("toggle_camera_state")
    def handle_camera(data):
        if not socket_auth_required():
            return
        desired = bool((data or {}).get("status", False))
        new_status = iot.set_camera_state(desired, user_id=session.get("user_id"))
        log_audit("Bật camera" if desired else "Tắt camera", user_id=session.get("user_id"))
        socketio.emit("camera_sync", {"active": new_status, "mode": "on" if desired else "off"})

    @socketio.on("control_device")
    def handle_manual(data):
        if not socket_auth_required():
            return
        iot.queue_command(
            (data or {}).get("command"),
            source="manual",
            gesture="manual_click",
            user_id=session.get("user_id"),
        )
