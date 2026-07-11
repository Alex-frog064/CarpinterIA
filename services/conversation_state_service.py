import json
from typing import Any

from database.db import get_db
from models.conversation_state import ConversationState
from services.audit_log import state_logger


def _ensure_state_row(conversation_id: str):
    with get_db() as conn:
        exists = conn.execute(
            "SELECT conversation_id FROM conversation_state WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchone()
        if not exists:
            conn.execute(
                """
                INSERT INTO conversation_state (conversation_id, current_state, cart_json, collected_data_json)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, ConversationState.IDLE.value, "[]", "{}"),
            )


def get_conversation_state(conversation_id: str) -> dict[str, Any]:
    _ensure_state_row(conversation_id)
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT current_state, cart_json, collected_data_json, updated_at
            FROM conversation_state WHERE conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()

    cart = _parse_json(row["cart_json"], [])
    collected = _parse_json(row["collected_data_json"], {})

    return {
        "state": row["current_state"] or ConversationState.IDLE.value,
        "cart": cart,
        "collected": collected,
        "customer_name": collected.get("customer_name"),
        "delivery_type": collected.get("delivery_type"),
        "delivery_address": collected.get("address"),
        "latitude": collected.get("latitude"),
        "longitude": collected.get("longitude"),
        "order_id": collected.get("order_id"),
        "pending_generic": collected.get("pending_generic"),
        "updated_at": row["updated_at"],
    }


def save_conversation_state(conversation_id: str, **fields):
    _ensure_state_row(conversation_id)
    state_data = get_conversation_state(conversation_id)

    if "state" in fields:
        state_data["state"] = fields["state"]
    if "cart" in fields:
        state_data["cart"] = fields["cart"]

    collected = dict(state_data.get("collected") or {})
    for key in (
        "customer_name",
        "delivery_type",
        "address",
        "latitude",
        "longitude",
        "order_id",
        "location_text",
        "pending_cancel_order_id",
        "pending_generic",
    ):
        if key in fields:
            if fields[key] is None:
                collected.pop(key, None)
            else:
                collected[key] = fields[key]

    if "delivery_address" in fields:
        collected["address"] = fields["delivery_address"]
    if "delivery_location" in fields:
        collected["location_text"] = fields["delivery_location"]

    with get_db() as conn:
        conn.execute(
            """
            UPDATE conversation_state
            SET current_state = ?, cart_json = ?, collected_data_json = ?, updated_at = CURRENT_TIMESTAMP
            WHERE conversation_id = ?
            """,
            (
                state_data["state"],
                json.dumps(state_data["cart"], ensure_ascii=False),
                json.dumps(collected, ensure_ascii=False),
                conversation_id,
            ),
        )

    if "state" in fields:
        state_logger.info(
            "Estado → %s | conversation_id=%s | cart_items=%d",
            state_data["state"],
            conversation_id[:8],
            len(state_data["cart"]),
        )


def reset_order_state(conversation_id: str):
    _ensure_state_row(conversation_id)
    with get_db() as conn:
        conn.execute(
            """
            UPDATE conversation_state
            SET current_state = ?, cart_json = ?, collected_data_json = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE conversation_id = ?
            """,
            (ConversationState.IDLE.value, "[]", "{}", conversation_id),
        )


def _parse_json(raw: str | None, default: Any) -> Any:
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default
