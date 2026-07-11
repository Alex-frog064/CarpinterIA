import hashlib
import secrets
from typing import Any

from database.db import get_db
from models.user import ActivityAction, UserRole


def _hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, password_hash: str) -> bool:
    try:
        salt, _ = password_hash.split("$", 1)
    except ValueError:
        return False
    return _hash_password(password, salt) == password_hash


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    with get_db() as conn:
        conn.execute(
            "INSERT INTO user_sessions (token, user_id) VALUES (?, ?)",
            (token, user_id),
        )
    return token


def delete_session(token: str):
    with get_db() as conn:
        conn.execute("DELETE FROM user_sessions WHERE token = ?", (token,))


def get_user_by_token(token: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT u.id, u.username, u.full_name, u.role, u.created_at
            FROM user_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token = ?
            """,
            (token,),
        ).fetchone()
    return dict(row) if row else None


def authenticate(username: str, password: str) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, password_hash, full_name, role FROM users WHERE username = ?",
            (username.strip().lower(),),
        ).fetchone()
    if not row or not verify_password(password, row["password_hash"]):
        return None
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "role": row["role"],
    }


def register_user(username: str, password: str, full_name: str, role: str = UserRole.CUSTOMER.value) -> dict | None:
    username = username.strip().lower()
    full_name = full_name.strip()
    if not username or not password or not full_name:
        return None

    with get_db() as conn:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?",
            (username,),
        ).fetchone()
        if exists:
            return None

        password_hash = _hash_password(password)
        cursor = conn.execute(
            "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
            (username, password_hash, full_name, role),
        )
        user_id = cursor.lastrowid

    return {
        "id": user_id,
        "username": username,
        "full_name": full_name,
        "role": role,
    }


def list_users() -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, username, full_name, role, created_at FROM users ORDER BY id"
        ).fetchall()
    return [dict(r) for r in rows]


def get_user_by_id(user_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT id, username, full_name, role, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
    return dict(row) if row else None
