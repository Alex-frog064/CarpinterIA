import json
from typing import Any

from database.db import get_db
from models.conversation_state import OrderStatus
from services.audit_log import order_logger, sales_logger

DELIVERY_FEE = 150.0  # Tarifa base de envío e instalación


def _debug_order(msg: str, **kwargs):
    parts = " | ".join(f"{k}={v}" for k, v in kwargs.items())
    order_logger.info("[DEBUG QUOTE] %s | %s", msg, parts)


def _parse_order_items(order: dict) -> list[dict]:
    raw = order.get("items_json") or order.get("items") or "[]"
    if isinstance(raw, list):
        return raw
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return []


def _validate_cart(items: list[dict]) -> dict | None:
    if not items:
        return {"exito": False, "mensaje": "No se puede crear una cotización sin servicios seleccionados."}
    return None


def calculate_order_total(cart: list[dict], delivery_type: str = "recoger") -> dict:
    """Calcula subtotal y total del pedido de carpintería."""
    subtotal = sum(
        item.get("subtotal", item.get("precio", 0) * item.get("cantidad", 1))
        for item in cart
    )
    delivery_fee = DELIVERY_FEE if delivery_type == "domicilio" else 0.0
    total = subtotal + delivery_fee
    return {
        "subtotal": round(subtotal, 2),
        "delivery_fee": round(delivery_fee, 2),
        "total": round(total, 2),
    }


def get_or_create_pending_order(
    conversation_id: str,
    items: list[dict],
    delivery_type: str,
    customer_name: str | None = None,
    address: str | None = None,
) -> dict:
    """Reutiliza cotización PENDING existente o crea una nueva."""
    cart_error = _validate_cart(items)
    if cart_error:
        return cart_error

    active = get_active_order(conversation_id)
    pedido = active.get("pedido")
    if pedido and pedido["status"] == OrderStatus.PENDING.value:
        update_order(
            pedido["id"],
            items=items,
            delivery_type=delivery_type,
            customer_name=customer_name,
            address=address,
        )
        order_logger.info("Cotización PENDING reutilizada #%s | conv=%s", pedido["id"], conversation_id[:8])
        return {
            "exito": True,
            "order_id": pedido["id"],
            "subtotal": pedido.get("subtotal"),
            "total": pedido["total"],
            "status": OrderStatus.PENDING.value,
            "reused": True,
        }
    return create_order(
        conversation_id=conversation_id,
        items=items,
        delivery_type=delivery_type,
        customer_name=customer_name,
        address=address,
        status=OrderStatus.PENDING.value,
    )



def create_order(
    conversation_id: str,
    items: list[dict],
    delivery_type: str,
    customer_name: str | None = None,
    address: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
    status: str = OrderStatus.PENDING.value,
) -> dict:
    """Crea un pedido en la tabla orders."""
    cart_error = _validate_cart(items)
    if cart_error:
        return cart_error

    totals = calculate_order_total(items, delivery_type)
    items_payload = json.dumps(items, ensure_ascii=False)

    insert_payload = {
        "conversation_id": conversation_id,
        "user_id": _resolve_user_id(conversation_id, None),
        "customer_name": customer_name,
        "delivery_type": delivery_type,
        "address": address,
        "latitude": latitude,
        "longitude": longitude,
        "items_json": items_payload,
        "subtotal": totals["subtotal"],
        "total": totals["total"],
        "status": status,
    }

    _debug_order(
        "create_order INSERT",
        cart=items_payload,
        insert_payload=json.dumps(insert_payload, ensure_ascii=False),
        state=status,
    )

    uid = _resolve_user_id(conversation_id, None)

    with get_db() as conn:
        cursor = conn.execute(
            """
            INSERT INTO orders (
                conversation_id, user_id, customer_name, delivery_type, address,
                latitude, longitude, items_json, subtotal, total, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                conversation_id,
                uid,
                customer_name,
                delivery_type,
                address,
                latitude,
                longitude,
                items_payload,
                totals["subtotal"],
                totals["total"],
                status,
            ),
        )
        order_id = cursor.lastrowid

    order_logger.info(
        "Cotización creada #%s | conv=%s | status=%s | total=$%.2f | items=%d",
        order_id,
        conversation_id[:8],
        status,
        totals["total"],
        len(items),
    )

    uid = _resolve_user_id(conversation_id, None)
    if uid:
        try:
            from services.activity_service import log_activity
            log_activity(uid, "CREATE_ORDER", {"order_id": order_id, "total": totals["total"]})
        except Exception:
            pass

    return {
        "exito": True,
        "order_id": order_id,
        "subtotal": totals["subtotal"],
        "total": totals["total"],
        "status": status,
    }


def update_order(order_id: int, **fields) -> dict:
    """Actualiza campos de una cotización existente."""
    allowed = {
        "customer_name",
        "delivery_type",
        "address",
        "latitude",
        "longitude",
        "items_json",
        "subtotal",
        "total",
        "status",
    }
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}

    if "items" in fields:
        items = fields["items"]
        cart_error = _validate_cart(items)
        if cart_error:
            return cart_error
        delivery = fields.get("delivery_type") or _get_order_field(order_id, "delivery_type")
        totals = calculate_order_total(items, delivery or "recoger")
        items_payload = json.dumps(items, ensure_ascii=False)
        updates["items_json"] = items_payload
        updates["subtotal"] = totals["subtotal"]
        updates["total"] = totals["total"]
        _debug_order(
            "update_order items",
            cart=items_payload,
            insert_payload=f"order_id={order_id}",
            state=fields.get("delivery_type", ""),
        )

    if not updates:
        return {"exito": False, "mensaje": "Sin campos para actualizar."}

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [order_id]

    _debug_order(
        "update_order SQL",
        cart=updates.get("items_json", "-"),
        insert_payload=f"SET {set_clause}",
        state=str(order_id),
    )

    with get_db() as conn:
        conn.execute(f"UPDATE orders SET {set_clause} WHERE id = ?", values)

    return {"exito": True, "order_id": order_id}


def confirm_order(order_id: int) -> dict:
    """Confirma cotización: registra trabajos/ventas y actualiza estado a CONFIRMED."""
    from tools.carpentry_tools import registrar_venta

    order = _get_order(order_id)
    if not order:
        return {"exito": False, "mensaje": "Cotización no encontrada."}

    if order["status"] == OrderStatus.CONFIRMED.value:
        order_logger.info("Cotización #%s ya confirmada (idempotente)", order_id)
        return {"exito": True, "order_id": order_id, "mensaje": "Cotización ya confirmada."}

    items = _parse_order_items(order)
    if not items:
        return {"exito": False, "mensaje": "Cotización sin servicios."}

    ventas = []
    errores = []

    for item in items:
        result = registrar_venta(item["producto"], item["cantidad"])
        if result.get("exito"):
            ventas.append(result)
            sales_logger.info(
                "Trabajo registrado | %s x%s | total=$%.2f | stock_restante=%s",
                item["producto"],
                item["cantidad"],
                result.get("total", 0),
                result.get("stock_restante"),
            )
        else:
            errores.append(f"{item['producto']}: {result.get('mensaje', 'Error')}")

    if errores:
        return {"exito": False, "mensaje": "; ".join(errores), "ventas": ventas}

    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (OrderStatus.CONFIRMED.value, order_id),
        )

    order_logger.info(
        "Cotización confirmada #%s | ventas=%d | total=$%.2f",
        order_id,
        len(ventas),
        order["total"],
    )

    if order.get("user_id"):
        try:
            from services.activity_service import log_activity
            log_activity(order["user_id"], "CONFIRM_ORDER", {"order_id": order_id, "total": order["total"]})
        except Exception:
            pass

    return {
        "exito": True,
        "order_id": order_id,
        "ventas_registradas": len(ventas),
        "total": order["total"],
        "status": OrderStatus.CONFIRMED.value,
    }



def save_customer_location(
    conversation_id: str, latitude: float, longitude: float
) -> dict:
    """Guarda ubicación GPS en conversation_state y pedido activo si existe."""
    from services.conversation_state_service import get_conversation_state, save_conversation_state

    state = get_conversation_state(conversation_id)
    save_conversation_state(
        conversation_id,
        latitude=latitude,
        longitude=longitude,
    )

    order_id = state.get("order_id")
    if order_id:
        update_order(order_id, latitude=latitude, longitude=longitude)

    return {
        "exito": True,
        "latitude": latitude,
        "longitude": longitude,
        "conversation_id": conversation_id,
    }


def get_active_order(conversation_id: str) -> dict:
    """Obtiene el pedido activo (PENDING o CONFIRMED) de una conversación."""
    with get_db() as conn:
        row = conn.execute(
            """
            SELECT * FROM orders
            WHERE conversation_id = ?
              AND status IN ('PENDING', 'CONFIRMED', 'PREPARING', 'DELIVERING')
            ORDER BY id DESC LIMIT 1
            """,
            (conversation_id,),
        ).fetchone()

    if not row:
        return {"pedido": None}

    order = dict(row)
    order["items"] = _parse_order_items(order)
    return {"pedido": order}


def cancel_order(order_id: int, user_id: int | None = None) -> dict:
    """Cancela un pedido. Solo PENDING o CONFIRMED."""
    order = _get_order(order_id)
    if not order:
        return {"exito": False, "mensaje": "Pedido no encontrado."}

    if user_id is not None and order.get("user_id") not in (None, user_id):
        return {"exito": False, "mensaje": "No tienes permiso para cancelar este pedido."}

    if order["status"] == OrderStatus.CANCELLED.value:
        return {"exito": True, "order_id": order_id, "mensaje": "Pedido ya cancelado.", "status": "CANCELLED"}

    if order["status"] in (OrderStatus.PREPARING.value, OrderStatus.DELIVERING.value):
        return {
            "exito": False,
            "mensaje": f"El pedido #{order_id} está en {order['status']} y ya no puede cancelarse.",
        }

    if order["status"] == OrderStatus.COMPLETED.value:
        return {"exito": False, "mensaje": f"El pedido #{order_id} ya fue completado."}

    if order["status"] not in (OrderStatus.PENDING.value, OrderStatus.CONFIRMED.value):
        return {"exito": False, "mensaje": f"No se puede cancelar un pedido en estado {order['status']}."}

    with get_db() as conn:
        conn.execute(
            "UPDATE orders SET status = ? WHERE id = ?",
            (OrderStatus.CANCELLED.value, order_id),
        )

    order_logger.info("Pedido cancelado #%s | user_id=%s", order_id, user_id)
    return {"exito": True, "order_id": order_id, "status": OrderStatus.CANCELLED.value}


def get_user_orders(user_id: int, limit: int = 50) -> list[dict]:
    """Lista pedidos de un usuario."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT * FROM orders WHERE user_id = ?
            ORDER BY created_at DESC LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
    result = []
    for row in rows:
        order = dict(row)
        order["items"] = _parse_order_items(order)
        result.append(order)
    return result


def list_all_orders(limit: int = 100) -> list[dict]:
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT o.*, u.username, u.full_name
            FROM orders o
            LEFT JOIN users u ON u.id = o.user_id
            ORDER BY o.created_at DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        order = dict(row)
        order["items"] = _parse_order_items(order)
        result.append(order)
    return result


def _resolve_user_id(conversation_id: str, user_id: int | None) -> int | None:
    if user_id is not None:
        return user_id
    with get_db() as conn:
        row = conn.execute(
            "SELECT user_id FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
    return row["user_id"] if row else None


def merge_cart_items(cart: list[dict], extracted: list[dict]) -> tuple[list[str], list[str]]:
    """Fusiona servicios extraídos al carrito de cotización (con madera y tamaño si aplica)."""
    from tools.carpentry_tools import (
        buscar_producto,
        buscar_tipo_madera,
        obtener_menu,
        obtener_tamanos_producto,
    )

    added = []
    errors: list[str] = []

    for item in extracted:
        categoria = item.get("categoria")
        cantidad = max(1, int(float(item.get("cantidad", 1) or 1)))
        madera_req = item.get("madera")      # tipo de madera solicitado
        tamano_req = item.get("tamano")      # tamaño solicitado

        if categoria:
            catalog_items = obtener_menu().get("productos") or []
            matches = [p for p in catalog_items if categoria in p["nombre"].lower()]
            if matches:
                if len(matches) > 1:
                    errors.append(f"ASK_FLAVORS:{categoria}:{cantidad}")
                    continue
                product = buscar_producto(matches[0]["nombre"]) if matches else None
            else:
                errors.append("Lo sentimos, ese servicio no forma parte de nuestro catálogo.")
                continue
        else:
            nombre = item.get("nombre", "").strip()
            product = buscar_producto(nombre)

        if not product:
            errors.append("Lo sentimos, ese servicio no forma parte de nuestro catálogo.")
            continue

        prod_price = product.get("price") or product.get("precio")
        if prod_price is None:
            errors.append(f"No es posible agregar {product.get('name')}: no tiene precio definido.")
            continue

        stock = product.get("stock")
        if stock is not None and stock < cantidad:
            errors.append(f"{product.get('name')} (capacidad insuficiente)")
            continue

        # Resolver modificador de madera
        wood_modifier = 1.0
        wood_name = None
        if madera_req:
            wood_info = buscar_tipo_madera(madera_req)
            if wood_info:
                wood_modifier = wood_info["price_modifier"]
                wood_name = wood_info["name"]
            else:
                from tools.carpentry_tools import obtener_tipos_madera
                woods = obtener_tipos_madera(active_only=True)
                wood_list = ", ".join(w["name"] for w in woods) if woods else "ninguna disponible"
                errors.append(
                    f"No existe el tipo de madera \"{madera_req.title()}\". "
                    f"Opciones disponibles: {wood_list}"
                )
                continue

        # Resolver modificador de tamaño
        size_modifier = 1.0
        size_label = None
        size_dims = None
        pid = product.get("id")
        if tamano_req and pid:
            sizes = obtener_tamanos_producto(pid)
            tamano_lower = tamano_req.strip().lower()
            match_size = next(
                (s for s in sizes if s["size_label"].lower() == tamano_lower
                 or tamano_lower in s["size_label"].lower()),
                None,
            )
            if match_size:
                size_modifier = match_size["price_modifier"]
                size_label = match_size["size_label"]
                size_dims = match_size["dimensions"]
            elif sizes:
                size_options = ", ".join(s["size_label"] for s in sizes)
                errors.append(
                    f"No existe tamaño \"{tamano_req.title()}\" para {product['name']}. "
                    f"Opciones disponibles: {size_options}"
                )
                continue

        precio_final = round(prod_price * wood_modifier * size_modifier, 2)

        existing = next(
            (c for c in cart if c["producto"].lower() == product["name"].lower()), None
        )
        if existing:
            existing["cantidad"] += cantidad
            existing["subtotal"] = round(existing["cantidad"] * existing["precio"], 2)
        else:
            cart.append(
                {
                    "producto": product["name"],
                    "product_id": product["id"],
                    "cantidad": cantidad,
                    "precio_base": prod_price,
                    "madera": wood_name,
                    "tamano": size_label,
                    "dimensiones": size_dims,
                    "modificador_madera": wood_modifier,
                    "modificador_tamano": size_modifier,
                    "precio": precio_final,
                    "subtotal": round(cantidad * precio_final, 2),
                }
            )
        added.append(product["name"])

    return added, errors



def _get_order(order_id: int) -> dict | None:
    with get_db() as conn:
        row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    return dict(row) if row else None


def _get_order_field(order_id: int, field: str):
    order = _get_order(order_id)
    return order.get(field) if order else None


def crear_pedido(
    conversation_id: str,
    items: list[dict],
    delivery_type: str,
    total: float,
    address: str | None = None,
    location: str | None = None,
) -> dict:
    return create_order(
        conversation_id=conversation_id,
        items=items,
        delivery_type=delivery_type,
        address=address,
        status=OrderStatus.CONFIRMED.value,
    )
