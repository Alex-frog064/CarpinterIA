"""Helpers de presentación para pedidos (sin lógica de negocio)."""


def estimated_days(delivery_type: str | None) -> int:
    dt = (delivery_type or "").lower()
    if "domicilio" in dt or "instalacion" in dt or "delivery" in dt:
        return 10
    return 7


def build_order_card(order: dict) -> dict:
    items = order.get("items") or []
    total = float(order.get("total") or 0)
    subtotal = float(order.get("subtotal") or 0)
    delivery_fee = total - subtotal if total > subtotal else 0.0
    return {
        "order_id": order["id"],
        "customer_name": order.get("customer_name") or "Cliente",
        "items": items,
        "subtotal": round(subtotal, 2),
        "delivery_fee": round(delivery_fee, 2),
        "total": total,
        "status": order.get("status") or "PENDING",
        "delivery_type": order.get("delivery_type"),
        "estimated_days": estimated_days(order.get("delivery_type")),
        "created_at": order.get("created_at"),
    }
