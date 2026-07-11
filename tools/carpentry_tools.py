from datetime import date

from database.db import get_db
from services.audit_log import sales_logger


def consultar_inventario() -> dict:
    """Devuelve el inventario completo de productos/servicios."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, stock, price, min_stock, menu_visible,
                   COALESCE(temperature, 'ESTANDAR') AS temperature,
                   COALESCE(category, 'MOBILIARIO') AS category
            FROM products ORDER BY name
            """
        ).fetchall()

    if not rows:
        return {"productos": [], "total_productos": 0}

    productos = [
        {
            "id": r["id"],
            "nombre": r["name"],
            "stock": r["stock"],
            "precio": r["price"],
            "stock_minimo": r["min_stock"],
            "menu_visible": bool(r["menu_visible"]),
            "activo": bool(r["menu_visible"]),
            "temperatura": r.get("temperature") if isinstance(r, dict) else r["temperature"],
            "categoria": r.get("category") if isinstance(r, dict) else r["category"],
        }
        for r in rows
    ]
    return {"productos": productos, "total_productos": len(productos)}


def actualizar_producto(
    product_id: int,
    stock: float | None = None,
    price: float | None = None,
    menu_visible: bool | None = None,
) -> dict:
    """Actualiza stock, precio o visibilidad de un servicio/producto (panel admin)."""
    updates = []
    params: list = []

    if stock is not None:
        if stock < 0:
            return {"exito": False, "mensaje": "El stock no puede ser negativo."}
        updates.append("stock = ?")
        params.append(stock)
    if price is not None:
        if price < 0:
            return {"exito": False, "mensaje": "El precio no puede ser negativo."}
        updates.append("price = ?")
        params.append(price)
    if menu_visible is not None:
        updates.append("menu_visible = ?")
        params.append(1 if menu_visible else 0)

    if not updates:
        return {"exito": False, "mensaje": "No hay cambios para aplicar."}

    with get_db() as conn:
        exists = conn.execute("SELECT id FROM products WHERE id = ?", (product_id,)).fetchone()
        if not exists:
            return {"exito": False, "mensaje": "Producto no encontrado."}
        conn.execute(
            f"UPDATE products SET {', '.join(updates)} WHERE id = ?",
            (*params, product_id),
        )
        row = conn.execute(
            "SELECT id, name, stock, price, min_stock, menu_visible FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()

    return {
        "exito": True,
        "producto": {
            "id": row["id"],
            "nombre": row["name"],
            "stock": row["stock"],
            "precio": row["price"],
            "stock_minimo": row["min_stock"],
            "menu_visible": bool(row["menu_visible"]),
            "activo": bool(row["menu_visible"]),
        },
    }


def obtener_stats_dashboard() -> dict:
    """Agrega métricas para el dashboard admin (solo lectura)."""
    hoy = date.today().isoformat()
    with get_db() as conn:
        ventas_dia = conn.execute(
            "SELECT COALESCE(SUM(total), 0) AS total FROM sales WHERE DATE(created_at) = ?",
            (hoy,),
        ).fetchone()["total"]
        pedidos_activos = conn.execute(
            """
            SELECT COUNT(*) AS c FROM orders
            WHERE status IN ('PENDING', 'CONFIRMED', 'PREPARING', 'DELIVERING')
            """
        ).fetchone()["c"]
        pedidos_cancelados = conn.execute(
            "SELECT COUNT(*) AS c FROM orders WHERE status = 'CANCELLED'"
        ).fetchone()["c"]
        usuarios_registrados = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]

    return {
        "ventas_dia": ventas_dia,
        "pedidos_activos": pedidos_activos,
        "pedidos_cancelados": pedidos_cancelados,
        "usuarios_registrados": usuarios_registrados,
    }


def registrar_venta(producto: str, cantidad: float) -> dict:
    """Registra una venta de servicio y descuenta stock/capacidad."""
    if cantidad <= 0:
        return {"exito": False, "mensaje": "La cantidad debe ser mayor a cero."}

    with get_db() as conn:
        row = conn.execute(
            "SELECT id, name, stock, price FROM products WHERE LOWER(name) = LOWER(?)",
            (producto.strip(),),
        ).fetchone()

        if not row:
            return {"exito": False, "mensaje": f"Producto/servicio '{producto}' no encontrado."}

        if row["stock"] < cantidad:
            return {
                "exito": False,
                "mensaje": f"Capacidad insuficiente. Disponible: {row['stock']}, solicitado: {cantidad}.",
            }

        total = row["price"] * cantidad
        nuevo_stock = row["stock"] - cantidad

        conn.execute(
            "INSERT INTO sales (product_id, quantity, total) VALUES (?, ?, ?)",
            (row["id"], cantidad, total),
        )
        conn.execute(
            "UPDATE products SET stock = ? WHERE id = ?",
            (nuevo_stock, row["id"]),
        )

    sales_logger.info(
        "Venta registrada | %s x%s | total=$%.2f | stock_restante=%s",
        row["name"],
        cantidad,
        total,
        nuevo_stock,
    )

    return {
        "exito": True,
        "producto": row["name"],
        "cantidad": cantidad,
        "total": total,
        "stock_restante": nuevo_stock,
    }


def registrar_gasto(concepto: str, monto: float) -> dict:
    """Registra un gasto operativo de la carpintería (materiales, insumos, etc.)."""
    if monto <= 0:
        return {"exito": False, "mensaje": "El monto debe ser mayor a cero."}

    with get_db() as conn:
        conn.execute(
            "INSERT INTO expenses (concept, amount) VALUES (?, ?)",
            (concepto.strip(), monto),
        )

    return {"exito": True, "concepto": concepto, "monto": monto}


def obtener_producto_mas_vendido() -> dict:
    """Obtiene el servicio con mayor cantidad vendida (histórico)."""
    with get_db() as conn:
        row = conn.execute("""
            SELECT p.name, SUM(s.quantity) AS total_vendido, SUM(s.total) AS ingresos
            FROM sales s
            JOIN products p ON p.id = s.product_id
            GROUP BY p.id
            ORDER BY total_vendido DESC
            LIMIT 1
        """).fetchone()

    if not row:
        return {"mensaje": "No hay cotizaciones confirmadas/ventas registradas aún."}

    return {
        "producto": row["name"],
        "cantidad_vendida": row["total_vendido"],
        "ingresos_generados": row["ingresos"],
    }


def obtener_ganancia_dia() -> dict:
    """Calcula ingresos, gastos y ganancia neta del día actual."""
    hoy = date.today().isoformat()

    with get_db() as conn:
        ingresos = conn.execute(
            "SELECT COALESCE(SUM(total), 0) AS total FROM sales WHERE DATE(created_at) = ?",
            (hoy,),
        ).fetchone()["total"]

        gastos = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM expenses WHERE DATE(created_at) = ?",
            (hoy,),
        ).fetchone()["total"]

    ganancia = ingresos - gastos
    return {
        "fecha": hoy,
        "ingresos": ingresos,
        "gastos": gastos,
        "ganancia_neta": ganancia,
    }


def productos_bajo_stock() -> dict:
    """Lista servicios/productos cuyo stock/disponibilidad está por debajo del mínimo."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT name, stock, min_stock FROM products WHERE stock <= min_stock ORDER BY stock"
        ).fetchall()

    if not rows:
        return {"productos": [], "mensaje": "Todos los servicios/productos tienen stock suficiente."}

    productos = [
        {
            "nombre": r["name"],
            "stock_actual": r["stock"],
            "stock_minimo": r["min_stock"],
            "faltante": max(0, r["min_stock"] - r["stock"]),
        }
        for r in rows
    ]
    return {"productos": productos, "total_bajo_stock": len(productos)}


def recomendar_compra() -> dict:
    """Recomienda insumos o reposiciones para servicios/productos con stock bajo."""
    inventario_bajo = productos_bajo_stock()
    productos = inventario_bajo.get("productos", [])

    if not productos:
        return {"recomendaciones": [], "mensaje": "No se requieren compras de insumos por ahora."}

    recomendaciones = []
    for p in productos:
        cantidad_sugerida = max(p["faltante"], p["stock_minimo"])
        recomendaciones.append(
            {
                "producto": p["nombre"],
                "stock_actual": p["stock_actual"],
                "cantidad_recomendada": cantidad_sugerida,
                "motivo": f"Stock ({p['stock_actual']}) por debajo del mínimo ({p['stock_minimo']})",
            }
        )

    return {"recomendaciones": recomendaciones, "total_items": len(recomendaciones)}


DEFAULT_MENU_PRODUCTS = [
    ("Mueble a medida", 15.0, 3500.0, 3.0),
    ("Puerta de madera", 15.0, 2800.0, 3.0),
    ("Closet", 10.0, 5500.0, 2.0),
    ("Cocina integral", 8.0, 12000.0, 2.0),
    ("Mesa de comedor", 10.0, 4200.0, 3.0),
    ("Restauración de mueble", 15.0, 1500.0, 5.0),
    ("Piso de madera (m²)", 80.0, 850.0, 10.0),
    ("Librero", 10.0, 3200.0, 3.0),
    ("Escalera de madera", 6.0, 8500.0, 2.0),
    ("Ventana de madera", 15.0, 2200.0, 3.0),
]


def _seed_default_menu(conn):
    for name, stock, price, min_stock in DEFAULT_MENU_PRODUCTS:
        exists = conn.execute(
            "SELECT 1 FROM products WHERE LOWER(name) = LOWER(?)",
            (name,),
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO products (name, stock, price, min_stock) VALUES (?, ?, ?, ?)",
                (name, stock, price, min_stock),
            )


def obtener_menu() -> dict:
    """Devuelve productos disponibles para cotizaciones."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, stock, price,
                   COALESCE(temperature, 'ESTANDAR') AS temperature,
                   COALESCE(category, 'MOBILIARIO') AS category
            FROM products
            WHERE stock > 0 AND menu_visible = 1
            ORDER BY name
            """
        ).fetchall()

        if not rows:
            _seed_default_menu(conn)
            rows = conn.execute(
                """
                SELECT id, name, stock, price, 'ESTANDAR' as temperature, 'MOBILIARIO' as category FROM products
                WHERE stock > 0 AND menu_visible = 1
                ORDER BY name
                """
            ).fetchall()

    productos = [
        {
            "id": r["id"],
            "nombre": r["name"],
            "stock": r["stock"],
            "precio": r["price"],
            "temperatura": r["temperature"],
            "categoria": r["category"],
        }
        for r in rows
    ]
    return {"productos": productos}


def buscar_producto(nombre: str) -> dict | None:
    """Busca un servicio/producto por nombre (coincidencia parcial)."""
    nombre_lower = nombre.strip().lower()
    with get_db() as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(products)").fetchall()]
        select_cols = ["id", "name", "stock", "price"]
        if "temperature" in cols:
            select_cols.append("temperature")
        if "category" in cols:
            select_cols.append("category")
        sql = f"SELECT {', '.join(select_cols)} FROM products WHERE stock > 0 AND menu_visible = 1 ORDER BY name"
        rows = conn.execute(sql).fetchall()

    for row in rows:
        if row["name"].lower() == nombre_lower:
            return dict(row)

    for row in rows:
        if nombre_lower in row["name"].lower() or row["name"].lower() in nombre_lower:
            return dict(row)

    keywords = nombre_lower.split()
    best = None
    best_score = 0
    for row in rows:
        name_lower = row["name"].lower()
        score = sum(1 for kw in keywords if kw in name_lower)
        if score > best_score:
            best_score = score
            best = row

    return dict(best) if best and best_score > 0 else None


from tools.order_tools import (
    calculate_order_total,
    cancel_order,
    confirm_order,
    create_order,
    get_active_order,
    save_customer_location,
    update_order,
)

TOOL_REGISTRY = {
    "consultar_inventario": consultar_inventario,
    "registrar_venta": registrar_venta,
    "registrar_gasto": registrar_gasto,
    "obtener_producto_mas_vendido": obtener_producto_mas_vendido,
    "obtener_ganancia_dia": obtener_ganancia_dia,
    "productos_bajo_stock": productos_bajo_stock,
    "recomendar_compra": recomendar_compra,
    "create_order": create_order,
    "update_order": update_order,
    "confirm_order": confirm_order,
    "calculate_order_total": calculate_order_total,
    "save_customer_location": save_customer_location,
    "get_active_order": get_active_order,
    "cancel_order": cancel_order,
}
