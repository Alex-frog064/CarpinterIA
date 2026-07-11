import json
from typing import Any

from database.db import get_db
from models.user import ActivityAction


def log_activity(user_id: int, action: str, details: dict[str, Any] | None = None):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO user_activity (user_id, action, details)
            VALUES (?, ?, ?)
            """,
            (user_id, action, json.dumps(details or {}, ensure_ascii=False)),
        )


def list_activity(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT a.id, a.user_id, u.username, u.full_name, a.action, a.details, a.created_at
            FROM user_activity a
            JOIN users u ON u.id = a.user_id
            ORDER BY a.created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        if item.get("details"):
            try:
                item["details"] = json.loads(item["details"])
            except json.JSONDecodeError:
                pass
        result.append(item)
    return result
