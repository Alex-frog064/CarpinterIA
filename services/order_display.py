"""Helpers de presentación para pedidos (sin lógica de negocio)."""


def estimated_days(delivery_type: str | None) -> int:
    dt = (delivery_type or "").lower()
    if "domicilio" in dt or "instalacion" in dt or "delivery" in dt:
        return 10
    return 7


def build_order_card(order: dict) -> dict:
    items = order.get("items") or []
    return {
        "order_id": order["id"],
        "customer_name": order.get("customer_name") or "Cliente",
        "items": items,
        "total": float(order.get("total") or 0),
        "status": order.get("status") or "PENDING",
        "delivery_type": order.get("delivery_type"),
        "estimated_days": estimated_days(order.get("delivery_type")),
        "created_at": order.get("created_at"),
    }
