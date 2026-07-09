from datetime import datetime, timezone, timedelta
from functools import wraps
import sqlite3

from flask import jsonify, redirect, session, flash, url_for
from flask_socketio import disconnect
from werkzeug.security import generate_password_hash

from config import DATABASE, DEFAULT_CONFIGS, INITIAL_USERS

# Ánh xạ cử chỉ mặc định: (gesture_name, target_device, action)
DEFAULT_GESTURE_MAPPINGS = [
    ("open", "light", "on"),      # bàn tay mở  -> bật đèn
    ("fist", "light", "off"),     # nắm tay     -> tắt đèn
    ("one", "fan", "on"),         # 1 ngón      -> bật quạt
    ("two", "fan", "off"),        # 2 ngón      -> tắt quạt
]


VN_TIMEZONE = timezone(timedelta(hours=7))


def vn_now():
    return datetime.now(VN_TIMEZONE)


def vn_now_sql():
    return vn_now().strftime("%Y-%m-%d %H:%M:%S")


def get_db_connection():
    conn = sqlite3.connect(DATABASE, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma foreign_keys = on")
    return conn


def column_exists(conn, table_name, column_name):
    cur = conn.cursor()
    cur.execute(f"pragma table_info({table_name})")
    rows = cur.fetchall()
    return any(row[1] == column_name for row in rows)


def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        create table if not exists users (
            id integer primary key autoincrement,
            username text not null unique,
            password_hash text not null,
            role text not null default 'member',
            is_suspended integer not null default 0,
            created_at datetime default (datetime('now', '+7 hours'))
        )
        """
    )

    if not column_exists(conn, "users", "is_suspended"):
        cur.execute(
            "alter table users add column is_suspended integer not null default 0"
        )

    cur.execute(
        """
        create table if not exists login_logs (
            id integer primary key autoincrement,
            user_id integer not null,
            ip_address text,
            timestamp datetime default (datetime('now', '+7 hours')),
            foreign key (user_id) references users(id)
        )
        """
    )

    cur.execute(
        """
        create table if not exists audit_logs (
            id integer primary key autoincrement,
            user_id integer,
            action text not null,
            timestamp datetime default (datetime('now', '+7 hours')),
            foreign key (user_id) references users(id)
        )
        """
    )

    cur.execute(
        """
        create table if not exists system_configs (
            id integer primary key autoincrement,
            key text not null unique,
            value text,
            updated_at datetime default (datetime('now', '+7 hours'))
        )
        """
    )

    cur.execute(
        """
        create table if not exists gesture_mappings (
            id integer primary key autoincrement,
            gesture_name text not null unique,
            target_device text not null,
            action text not null,
            updated_at datetime default (datetime('now', '+7 hours'))
        )
        """
    )

    # Ánh xạ cử chỉ mặc định (giữ hành vi cũ) — chỉ chèn nếu bảng trống
    cur.execute("select count(*) from gesture_mappings")
    if cur.fetchone()[0] == 0:
        for g, dev, act in DEFAULT_GESTURE_MAPPINGS:
            cur.execute(
                "insert or ignore into gesture_mappings (gesture_name, target_device, action) values (?, ?, ?)",
                (g, dev, act),
            )

    for key, value in DEFAULT_CONFIGS.items():
        cur.execute(
            "insert or ignore into system_configs (key, value) values (?, ?)",
            (key, value),
        )

    conn.commit()
    conn.close()


def seed_initial_users():
    conn = get_db_connection()
    cur = conn.cursor()

    for user in INITIAL_USERS:
        username = user["username"].strip()
        password = user["password"]
        role = user.get("role", "member")

        cur.execute("select id from users where username = ?", (username,))
        exists = cur.fetchone()

        if not exists:
            cur.execute(
                """
                insert into users (username, password_hash, role, is_suspended)
                values (?, ?, ?, 0)
                """,
                (
                    username,
                    generate_password_hash(password),
                    role,
                ),
            )

    conn.commit()
    conn.close()


def get_user_by_username(username):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("select * from users where username = ?", (username,))
    user = cur.fetchone()
    conn.close()
    return user


def get_user_by_id(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("select * from users where id = ?", (user_id,))
    user = cur.fetchone()
    conn.close()
    return user


def create_user(username, password, role="member"):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        insert into users (username, password_hash, role, is_suspended)
        values (?, ?, ?, 0)
        """,
        (
            username.strip(),
            generate_password_hash(password),
            role,
        ),
    )

    conn.commit()
    conn.close()


def get_config_value(key_name, default=""):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("select value from system_configs where key = ?", (key_name,))
    row = cur.fetchone()
    conn.close()

    if row:
        return row["value"] or default

    return default


def set_config_value(key_name, value):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        insert into system_configs (key, value, updated_at)
        values (?, ?, datetime('now', '+7 hours'))
        on conflict(key) do update set
            value = excluded.value,
            updated_at = datetime('now', '+7 hours')
        """,
        (key_name, value),
    )

    conn.commit()
    conn.close()


def log_login(user_id, ip_address):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        insert into login_logs (user_id, ip_address, timestamp)
        values (?, ?, ?)
        """,
        (user_id, ip_address, vn_now_sql()),
    )

    conn.commit()
    conn.close()


def log_audit(action, user_id=None):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        insert into audit_logs (user_id, action, timestamp)
        values (?, ?, ?)
        """,
        (user_id, action, vn_now_sql()),
    )

    conn.commit()
    conn.close()


def fetch_admin_users():
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select id, username, role, is_suspended, created_at
        from users
        order by role desc, id asc
        """
    )

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def fetch_login_logs(limit=100):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select
            ll.id,
            ll.user_id,
            u.username,
            ll.ip_address,
            ll.timestamp
        from login_logs ll
        left join users u on u.id = ll.user_id
        order by ll.id desc
        limit ?
        """,
        (limit,),
    )

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def fetch_audit_logs(limit=200):
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        select
            al.id,
            al.user_id,
            u.username,
            al.action,
            al.timestamp
        from audit_logs al
        left join users u on u.id = al.user_id
        order by al.id desc
        limit ?
        """,
        (limit,),
    )

    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_current_user():
    user_id = session.get("user_id")

    if not user_id:
        return None

    return get_user_by_id(user_id)


def is_user_active(user_row):
    if not user_row:
        return False

    return int(user_row["is_suspended"]) == 0


def ensure_session_user_is_active():
    user = get_current_user()

    if not user or not is_user_active(user):
        session.clear()
        return None

    return user


def login_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))

        user = ensure_session_user_is_active()

        if not user:
            flash("Phiên đăng nhập không còn hợp lệ hoặc tài khoản đã bị khóa.", "error")
            return redirect(url_for("login"))

        return view_func(*args, **kwargs)

    return wrapper


def admin_required(view_func):
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return jsonify({
                "ok": False,
                "message": "Chưa đăng nhập."
            }), 401

        user = ensure_session_user_is_active()

        if not user:
            return jsonify({
                "ok": False,
                "message": "Phiên đăng nhập không hợp lệ hoặc tài khoản đã bị khóa."
            }), 401

        if user["role"] != "admin":
            return jsonify({
                "ok": False,
                "message": "Bạn không có quyền truy cập."
            }), 403

        return view_func(*args, **kwargs)

    return wrapper


def socket_auth_required():
    if "user_id" not in session:
        disconnect()
        return False

    user = get_current_user()

    if not user or not is_user_active(user):
        session.clear()
        disconnect()
        return False

    return True


# ================================================================== #
#  Ánh xạ cử chỉ (Yêu cầu 2)
# ================================================================== #
def fetch_gesture_mappings():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        "select gesture_name, target_device, action from gesture_mappings order by gesture_name asc"
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def upsert_gesture_mapping(gesture_name, target_device, action):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        insert into gesture_mappings (gesture_name, target_device, action, updated_at)
        values (?, ?, ?, datetime('now', '+7 hours'))
        on conflict(gesture_name) do update set
            target_device = excluded.target_device,
            action = excluded.action,
            updated_at = datetime('now', '+7 hours')
        """,
        (gesture_name, target_device, action),
    )
    conn.commit()
    conn.close()


def delete_gesture_mapping(gesture_name):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("delete from gesture_mappings where gesture_name = ?", (gesture_name,))
    conn.commit()
    conn.close()


# ================================================================== #
#  Xóa lịch sử (Yêu cầu 3)
# ================================================================== #
def clear_login_logs():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("delete from login_logs")
    conn.commit()
    conn.close()


def clear_audit_logs():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("delete from audit_logs")
    conn.commit()
    conn.close()


# ================================================================== #
#  Lịch sử cảnh báo phòng bếp (Yêu cầu 4) — lọc từ audit_logs
# ================================================================== #
def fetch_kitchen_alerts(limit=50):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute(
        """
        select al.id, u.username, al.action, al.timestamp
        from audit_logs al
        left join users u on u.id = al.user_id
        where lower(al.action) like '%gas%'
           or lower(al.action) like '%khói%'
           or lower(al.action) like '%khoi%'
           or lower(al.action) like '%lửa%'
           or lower(al.action) like '%lua%'
           or lower(al.action) like '%cháy%'
           or lower(al.action) like '%chay%'
           or lower(al.action) like '%khẩn%'
           or lower(al.action) like '%khan%'
        order by al.id desc
        limit ?
        """,
        (limit,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows
