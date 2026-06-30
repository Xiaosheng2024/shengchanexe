import base64
import configparser
import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta

from web_admin_app import database


PASSWORD_ITERATIONS = 310_000
SESSION_COOKIE_NAME = "mes_admin_session"
SESSION_TTL_SECONDS = 8 * 60 * 60
LOGIN_FAILURE_LIMIT = 5
LOGIN_LOCK_MINUTES = 5
PROTECTED_MESSAGE = "超级管理员账号受保护，不能在后台修改或删除"
WEAK_PASSWORDS = {
    "admin",
    "admin123",
    "123456",
    "12345678",
    "password",
    "000000",
    "111111",
}


def _b64encode(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def hash_password(password):
    validate_password_strength(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS)
    return f"pbkdf2_sha256${PASSWORD_ITERATIONS}${_b64encode(salt)}${_b64encode(digest)}"


def verify_password(password, password_hash):
    try:
        algorithm, iterations, salt, expected = password_hash.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            _b64decode(salt),
            int(iterations),
        )
        return hmac.compare_digest(digest, _b64decode(expected))
    except (TypeError, ValueError):
        return False


def validate_password_strength(password):
    if len(password or "") < 8:
        raise ValueError("新密码长度至少为8位")
    if password.strip().lower() in WEAK_PASSWORDS:
        raise ValueError("新密码过于简单，请使用更强的密码")


def ensure_session_secret():
    config = configparser.ConfigParser()
    if database.CONFIG_PATH.exists():
        config.read(database.CONFIG_PATH, encoding="utf-8")
    secret = config.get("SECURITY", "session_secret", fallback="").strip()
    if secret:
        return secret
    secret = secrets.token_urlsafe(48)
    if "SECURITY" not in config:
        config["SECURITY"] = {}
    config["SECURITY"]["session_secret"] = secret
    with database.CONFIG_PATH.open("w", encoding="utf-8") as file:
        config.write(file)
    return secret


def load_session_secret():
    config = configparser.ConfigParser()
    config.read(database.CONFIG_PATH, encoding="utf-8")
    secret = config.get("SECURITY", "session_secret", fallback="").strip()
    if not secret:
        raise RuntimeError("缺少 SECURITY.session_secret")
    return secret


def create_session_token(user):
    now = int(datetime.now().timestamp())
    payload = {
        "user_id": user["id"],
        "username": user["username"],
        "role": user["role"],
        "user_updated_at": str(user.get("updated_at") or ""),
        "login_time": now,
        "exp": now + SESSION_TTL_SECONDS,
        "nonce": secrets.token_hex(8),
    }
    encoded = _b64encode(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    signature = hmac.new(load_session_secret().encode("utf-8"), encoded.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded}.{_b64encode(signature)}"


def parse_session_token(token):
    try:
        encoded, signature = token.split(".", 1)
        expected = hmac.new(
            load_session_secret().encode("utf-8"),
            encoded.encode("ascii"),
            hashlib.sha256,
        ).digest()
        if not hmac.compare_digest(expected, _b64decode(signature)):
            return None
        payload = json.loads(_b64decode(encoded).decode("utf-8"))
        if int(payload.get("exp", 0)) < int(datetime.now().timestamp()):
            return None
        user = get_user_by_id(int(payload.get("user_id", 0)))
        if not user or not user["is_active"]:
            return None
        if user["username"] != payload.get("username") or user["role"] != payload.get("role"):
            return None
        if str(user.get("updated_at") or "") != payload.get("user_updated_at"):
            return None
        return user
    except (ValueError, TypeError, json.JSONDecodeError):
        return None


def session_cookie(token):
    return (
        f"{SESSION_COOKIE_NAME}={token}; Path=/; HttpOnly; SameSite=Strict; "
        f"Max-Age={SESSION_TTL_SECONDS}"
    )


def expired_session_cookie():
    return f"{SESSION_COOKIE_NAME}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


def safe_user(row):
    if not row:
        return None
    data = database.row_to_dict(row)
    data.pop("password_hash", None)
    data["is_builtin"] = bool(data["is_builtin"])
    data["is_active"] = bool(data["is_active"])
    data["protected"] = data["role"] == "super_admin" or data["is_builtin"]
    return data


def get_user_by_id(user_id):
    with database.get_conn() as conn:
        row = conn.execute("SELECT * FROM web_admin_users WHERE id = ?", (user_id,)).fetchone()
    return safe_user(row)


def get_user_by_username(username, include_hash=False):
    with database.get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM web_admin_users WHERE username = ?",
            ((username or "").strip(),),
        ).fetchone()
    if include_hash:
        return database.row_to_dict(row)
    return safe_user(row)


def list_users():
    with database.get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM web_admin_users ORDER BY is_builtin DESC, username"
        ).fetchall()
    return [safe_user(row) for row in rows]


def list_login_logs(limit=100):
    limit = min(max(int(limit), 1), 500)
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, username, role, ip_address, user_agent, success, message, created_at
            FROM web_admin_login_logs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    records = [database.row_to_dict(row) for row in rows]
    for record in records:
        record["success"] = bool(record["success"])
    return records


def log_auth_event(username, role, ip_address, user_agent, success, message):
    with database.get_conn() as conn:
        conn.execute(
            """
            INSERT INTO web_admin_login_logs
            (username, role, ip_address, user_agent, success, message, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                username or "",
                role or "",
                ip_address or "",
                user_agent or "",
                bool(success),
                message or "",
                database.now_text(),
            ),
        )


def login_is_locked(username, ip_address):
    threshold = (datetime.now() - timedelta(minutes=LOGIN_LOCK_MINUTES)).isoformat(timespec="seconds")
    with database.get_conn() as conn:
        rows = conn.execute(
            """
            SELECT success
            FROM web_admin_login_logs
            WHERE created_at >= ? AND (username = ? OR ip_address = ?)
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (threshold, username, ip_address, LOGIN_FAILURE_LIMIT + 1),
        ).fetchall()
    consecutive_failures = 0
    for row in rows:
        if bool(row["success"]):
            break
        consecutive_failures += 1
    return consecutive_failures >= LOGIN_FAILURE_LIMIT


def authenticate(username, password, ip_address="", user_agent=""):
    username = (username or "").strip()
    if login_is_locked(username, ip_address):
        log_auth_event(username, "", ip_address, user_agent, False, "登录失败次数过多，锁定5分钟")
        return None, "登录失败次数过多，请5分钟后重试"
    user = get_user_by_username(username, include_hash=True)
    if not user or not user["is_active"] or not verify_password(password or "", user["password_hash"]):
        log_auth_event(username, user["role"] if user else "", ip_address, user_agent, False, "账号或密码错误")
        return None, "账号或密码错误"
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE web_admin_users SET last_login_at = ?, updated_at = ? WHERE id = ?",
            (database.now_text(), database.now_text(), user["id"]),
        )
    log_auth_event(username, user["role"], ip_address, user_agent, True, "登录成功")
    return get_user_by_id(user["id"]), ""


def bootstrap_builtin_accounts(admin_password, super_admin_password):
    validate_password_strength(admin_password)
    validate_password_strength(super_admin_password)
    created = []
    with database.get_conn() as conn:
        for username, password, role, display_name, is_builtin in (
            ("admin", admin_password, "admin", "客户管理员", False),
            ("super_admin", super_admin_password, "super_admin", "超级管理员", True),
        ):
            existing = conn.execute(
                "SELECT id FROM web_admin_users WHERE username = ?",
                (username,),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """
                INSERT INTO web_admin_users
                (username, password_hash, role, display_name, is_builtin, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    username,
                    hash_password(password),
                    role,
                    display_name,
                    is_builtin,
                    True,
                    database.now_text(),
                    database.now_text(),
                ),
            )
            created.append(username)
    return created


def validate_builtin_accounts():
    admin = get_user_by_username("admin")
    super_admin = get_user_by_username("super_admin")
    if not admin or not super_admin:
        raise RuntimeError("Web 管理账号尚未初始化，请先执行服务器账号初始化脚本")
    if super_admin["role"] != "super_admin" or not super_admin["is_builtin"] or not super_admin["is_active"]:
        raise RuntimeError("super_admin 账号保护属性不正确")


def change_own_password(user_id, old_password, new_password):
    user = get_user_by_username(get_user_by_id(user_id)["username"], include_hash=True)
    if user["role"] == "super_admin" or user["is_builtin"]:
        raise ValueError(PROTECTED_MESSAGE)
    if not verify_password(old_password or "", user["password_hash"]):
        raise ValueError("旧密码不正确")
    validate_password_strength(new_password)
    if verify_password(new_password, user["password_hash"]):
        raise ValueError("新密码不能与旧密码相同")
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE web_admin_users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), database.now_text(), user_id),
        )


def reset_password_from_server(username, new_password, allow_super_admin=False):
    user = get_user_by_username(username)
    if not user:
        raise ValueError("用户不存在")
    if user["role"] == "super_admin" and not allow_super_admin:
        raise ValueError(PROTECTED_MESSAGE)
    with database.get_conn() as conn:
        conn.execute(
            "UPDATE web_admin_users SET password_hash = ?, is_active = ?, updated_at = ? WHERE id = ?",
            (hash_password(new_password), True, database.now_text(), user["id"]),
        )


def create_admin_user(payload):
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    if not username:
        raise ValueError("用户名不能为空")
    if username == "super_admin":
        raise ValueError(PROTECTED_MESSAGE)
    validate_password_strength(password)
    with database.get_conn() as conn:
        existing = conn.execute("SELECT id FROM web_admin_users WHERE username = ?", (username,)).fetchone()
        if existing:
            raise ValueError("用户名已存在")
        cursor = conn.execute(
            """
            INSERT INTO web_admin_users
            (username, password_hash, role, display_name, is_builtin, is_active, created_at, updated_at)
            VALUES (?, ?, 'admin', ?, ?, ?, ?, ?)
            """,
            (
                username,
                hash_password(password),
                (payload.get("display_name") or "").strip(),
                False,
                True,
                database.now_text(),
                database.now_text(),
            ),
        )
    return get_user_by_id(cursor.lastrowid)


def update_admin_user(user_id, payload):
    user = get_user_by_id(user_id)
    if not user:
        raise ValueError("用户不存在")
    if user["protected"]:
        raise ValueError(PROTECTED_MESSAGE)
    username = (payload.get("username") or user["username"]).strip()
    if username == "super_admin":
        raise ValueError(PROTECTED_MESSAGE)
    with database.get_conn() as conn:
        duplicate = conn.execute(
            "SELECT id FROM web_admin_users WHERE username = ? AND id <> ?",
            (username, user_id),
        ).fetchone()
        if duplicate:
            raise ValueError("用户名已存在")
        conn.execute(
            """
            UPDATE web_admin_users
            SET username = ?, display_name = ?, role = 'admin', is_active = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                username,
                (payload.get("display_name") or user["display_name"]).strip(),
                bool(payload.get("is_active", user["is_active"])),
                database.now_text(),
                user_id,
            ),
        )
    return get_user_by_id(user_id)


def delete_admin_user(user_id, current_user_id):
    user = get_user_by_id(user_id)
    if not user:
        return
    if user["protected"]:
        raise ValueError(PROTECTED_MESSAGE)
    if user_id == current_user_id:
        raise ValueError("不能删除当前登录账号")
    with database.get_conn() as conn:
        conn.execute("DELETE FROM web_admin_users WHERE id = ?", (user_id,))
