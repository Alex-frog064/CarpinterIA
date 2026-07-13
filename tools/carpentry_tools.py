from datetime import date

from database.db import get_db
from services.audit_log import sales_logger

PRODUCT_SIZE_LIMITS = {
    "silla": {
        "alto": (70, 110),
        "ancho": (35, 55),
        "fondo": (35, 50),
        "unidades": "cm",
        "desc": "Altura total 85–100 cm, ancho 40–50 cm, fondo 40–45 cm",
    },
    "mesa": {
        "alto": (70, 80),
        "ancho": (70, 200),
        "largo": (100, 300),
        "unidades": "cm",
        "desc": "Alto 75 cm estándar. 4 personas: 120×80 cm, 6 personas: 150–180×90 cm",
    },
    "closet": {
        "alto": (200, 240),
        "ancho": (100, 240),
        "fondo": (50, 65),
        "unidades": "cm",
        "desc": "Grande: 240×180–240×60 cm. Mediano: 210–230×120–180×55–60 cm",
    },
    "cocina": {
        "alto": (80, 95),
        "ancho": (35, 110),
        "profundidad": (50, 65),
        "unidades": "cm",
        "desc": "Altura 85–90 cm, profundidad 55–60 cm. Ancho por módulo: 40, 60, 80, 100 cm",
    },
    "librero": {
        "alto": (100, 230),
        "ancho": (50, 110),
        "fondo": (20, 40),
        "unidades": "cm",
        "desc": "Alto 120–220 cm, ancho 60–100 cm, fondo 25–35 cm",
    },
    "puerta": {
        "alto": (190, 240),
        "ancho": (60, 130),
        "grosor": (2.5, 6),
        "unidades": "cm / grosor en cm",
        "desc": "Interior: 200–210×70–90 cm. Principal: 210–240×90–120 cm",
    },
    "piso": {
        "largo": (80, 230),
        "ancho": (6, 20),
        "grosor": (1, 2.5),
        "unidades": "cm",
        "desc": "Duela: 8–15 cm ancho, 90–220 cm largo, 1.5–2 cm grosor. Venta por m²",
    },
    "restauracion": None,
}


def _match_product_to_limit(product_name: str) -> dict | None:
    name_lower = product_name.lower()
    for key, limits in PRODUCT_SIZE_LIMITS.items():
        if limits is None:
            continue
        if key in name_lower:
            return limits
    return None


def validar_dimensiones_producto(product_name: str, alto: float = None, ancho: float = None,
                                  fondo: float = None, largo: float = None,
                                  profundidad: float = None, grosor: float = None) -> str | None:
    limits = _match_product_to_limit(product_name)
    if limits is None:
        return None

    checks = []
    if alto is not None and "alto" in limits:
        checks.append(("Alto", alto, limits["alto"]))
    if ancho is not None and "ancho" in limits:
        checks.append(("Ancho", ancho, limits["ancho"]))
    if fondo is not None and "fondo" in limits:
        checks.append(("Fondo", fondo, limits["fondo"]))
    if largo is not None and "largo" in limits:
        checks.append(("Largo", largo, limits["largo"]))
    if profundidad is not None and "profundidad" in limits:
        checks.append(("Profundidad", profundidad, limits["profundidad"]))
    if grosor is not None and "grosor" in limits:
        checks.append(("Grosor", grosor, limits["grosor"]))

    errors = []
    for name, value, (min_v, max_v) in checks:
        if value < min_v:
            errors.append(f"{name}: {value} cm es menor al mínimo de {min_v} cm")
        elif value > max_v:
            errors.append(f"{name}: {value} cm excede el máximo de {max_v} cm")

    if errors:
        return (
            f"Las dimensiones exceden los límites para {product_name}:\n"
            + "\n".join(f"  • {e}" for e in errors)
            + f"\n\nRango permitido: {limits['desc']}"
        )
    return None


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
    """Devuelve productos disponibles para cotizaciones (con tamaños y rango de precios)."""
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

        # Obtener todos los tipos de madera y sus modificadores
        wood_rows = conn.execute(
            "SELECT price_modifier FROM wood_types WHERE active = 1"
        ).fetchall()
        wood_mods = [r["price_modifier"] for r in wood_rows] or [1.0]
        min_wood = min(wood_mods)
        max_wood = max(wood_mods)

    productos = []
    for r in rows:
        pid = r["id"]
        precio_base = r["price"]

        # Tamaños del producto
        size_rows_prod = []
        with get_db() as conn2:
            size_rows_prod = conn2.execute(
                "SELECT id, product_id, size_label, dimensions, price_modifier FROM product_sizes WHERE product_id = ? ORDER BY price_modifier",
                (pid,),
            ).fetchall()

        sizes = [
            {
                "id": s["id"],
                "size_label": s["size_label"],
                "dimensions": s["dimensions"],
                "price_modifier": s["price_modifier"],
                "precio_calculado": round(precio_base * s["price_modifier"], 2),
            }
            for s in size_rows_prod
        ]

        size_mods = [s["price_modifier"] for s in size_rows_prod] or [1.0]
        min_size = min(size_mods)
        max_size = max(size_mods)

        precio_minimo = round(precio_base * min_wood * min_size, 2)
        precio_maximo = round(precio_base * max_wood * max_size, 2)

        productos.append(
            {
                "id": pid,
                "nombre": r["name"],
                "stock": r["stock"],
                "precio": precio_base,
                "precio_minimo": precio_minimo,
                "precio_maximo": precio_maximo,
                "temperatura": r["temperature"],
                "categoria": r["category"],
                "tamanos": sizes,
            }
        )

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


# ── Tipos de Madera ───────────────────────────────────────────────────────────

def obtener_tipos_madera(active_only: bool = True) -> list[dict]:
    """Devuelve lista de tipos de madera disponibles con sus modificadores de precio."""
    with get_db() as conn:
        if active_only:
            rows = conn.execute(
                "SELECT id, name, price_modifier, description, active FROM wood_types WHERE active = 1 ORDER BY price_modifier"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, name, price_modifier, description, active FROM wood_types ORDER BY price_modifier"
            ).fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "price_modifier": r["price_modifier"],
            "description": r["description"],
            "active": bool(r["active"]),
        }
        for r in rows
    ]


def crear_tipo_madera(name: str, price_modifier: float, description: str | None = None) -> dict:
    """Crea un nuevo tipo de madera."""
    if price_modifier <= 0:
        return {"exito": False, "mensaje": "El modificador de precio debe ser mayor a 0."}
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM wood_types WHERE LOWER(name) = LOWER(?)", (name,)).fetchone()
        if exists:
            return {"exito": False, "mensaje": f"Ya existe un tipo de madera con el nombre '{name}'."}
        cursor = conn.execute(
            "INSERT INTO wood_types (name, price_modifier, description) VALUES (?, ?, ?)",
            (name.strip(), price_modifier, description),
        )
        row = conn.execute(
            "SELECT id, name, price_modifier, description, active FROM wood_types WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return {
        "exito": True,
        "wood_type": {"id": row["id"], "name": row["name"], "price_modifier": row["price_modifier"],
                      "description": row["description"], "active": bool(row["active"])},
    }


def actualizar_tipo_madera(
    wood_type_id: int,
    price_modifier: float | None = None,
    description: str | None = None,
    active: bool | None = None,
) -> dict:
    """Actualiza un tipo de madera existente."""
    updates = []
    params: list = []
    if price_modifier is not None:
        if price_modifier <= 0:
            return {"exito": False, "mensaje": "El modificador debe ser mayor a 0."}
        updates.append("price_modifier = ?")
        params.append(price_modifier)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if active is not None:
        updates.append("active = ?")
        params.append(1 if active else 0)
    if not updates:
        return {"exito": False, "mensaje": "No hay cambios para aplicar."}
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM wood_types WHERE id = ?", (wood_type_id,)).fetchone()
        if not exists:
            return {"exito": False, "mensaje": "Tipo de madera no encontrado."}
        conn.execute(
            f"UPDATE wood_types SET {', '.join(updates)} WHERE id = ?",
            (*params, wood_type_id),
        )
        row = conn.execute(
            "SELECT id, name, price_modifier, description, active FROM wood_types WHERE id = ?",
            (wood_type_id,),
        ).fetchone()
    return {
        "exito": True,
        "wood_type": {"id": row["id"], "name": row["name"], "price_modifier": row["price_modifier"],
                      "description": row["description"], "active": bool(row["active"])},
    }


def eliminar_tipo_madera(wood_type_id: int) -> dict:
    """Desactiva un tipo de madera (soft delete)."""
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM wood_types WHERE id = ?", (wood_type_id,)).fetchone()
        if not exists:
            return {"exito": False, "mensaje": "Tipo de madera no encontrado."}
        conn.execute("UPDATE wood_types SET active = 0 WHERE id = ?", (wood_type_id,))
    return {"exito": True, "mensaje": f"Tipo de madera #{wood_type_id} desactivado."}


def buscar_tipo_madera(nombre: str) -> dict | None:
    """Busca un tipo de madera activo por nombre (coincidencia parcial)."""
    nombre_lower = nombre.strip().lower()
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, name, price_modifier, description FROM wood_types WHERE active = 1"
        ).fetchall()
    for row in rows:
        if row["name"].lower() == nombre_lower:
            return dict(row)
    for row in rows:
        if nombre_lower in row["name"].lower() or row["name"].lower() in nombre_lower:
            return dict(row)
    return None


# ── Tamaños de Producto ───────────────────────────────────────────────────────

def obtener_tamanos_producto(product_id: int) -> list[dict]:
    """Devuelve los tamaños disponibles para un producto."""
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, product_id, size_label, dimensions, price_modifier FROM product_sizes WHERE product_id = ? ORDER BY price_modifier",
            (product_id,),
        ).fetchall()
    return [
        {
            "id": r["id"],
            "product_id": r["product_id"],
            "size_label": r["size_label"],
            "dimensions": r["dimensions"],
            "price_modifier": r["price_modifier"],
        }
        for r in rows
    ]


def crear_tamano_producto(
    product_id: int,
    size_label: str,
    price_modifier: float,
    dimensions: str | None = None,
) -> dict:
    """Añade un tamaño a un producto."""
    if price_modifier <= 0:
        return {"exito": False, "mensaje": "El modificador de precio debe ser mayor a 0."}
    with get_db() as conn:
        prod = conn.execute("SELECT 1 FROM products WHERE id = ?", (product_id,)).fetchone()
        if not prod:
            return {"exito": False, "mensaje": "Producto no encontrado."}
        exists = conn.execute(
            "SELECT 1 FROM product_sizes WHERE product_id = ? AND LOWER(size_label) = LOWER(?)",
            (product_id, size_label),
        ).fetchone()
        if exists:
            return {"exito": False, "mensaje": f"Ya existe el tamaño '{size_label}' para este producto."}
        cursor = conn.execute(
            "INSERT INTO product_sizes (product_id, size_label, dimensions, price_modifier) VALUES (?, ?, ?, ?)",
            (product_id, size_label.strip(), dimensions, price_modifier),
        )
        row = conn.execute(
            "SELECT id, product_id, size_label, dimensions, price_modifier FROM product_sizes WHERE id = ?",
            (cursor.lastrowid,),
        ).fetchone()
    return {
        "exito": True,
        "size": {"id": row["id"], "product_id": row["product_id"], "size_label": row["size_label"],
                 "dimensions": row["dimensions"], "price_modifier": row["price_modifier"]},
    }


def actualizar_tamano_producto(
    size_id: int,
    price_modifier: float | None = None,
    dimensions: str | None = None,
) -> dict:
    """Actualiza un tamaño de producto existente."""
    updates = []
    params: list = []
    if price_modifier is not None:
        if price_modifier <= 0:
            return {"exito": False, "mensaje": "El modificador debe ser mayor a 0."}
        updates.append("price_modifier = ?")
        params.append(price_modifier)
    if dimensions is not None:
        updates.append("dimensions = ?")
        params.append(dimensions)
    if not updates:
        return {"exito": False, "mensaje": "No hay cambios para aplicar."}
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM product_sizes WHERE id = ?", (size_id,)).fetchone()
        if not exists:
            return {"exito": False, "mensaje": "Tamaño no encontrado."}
        conn.execute(
            f"UPDATE product_sizes SET {', '.join(updates)} WHERE id = ?",
            (*params, size_id),
        )
        row = conn.execute(
            "SELECT id, product_id, size_label, dimensions, price_modifier FROM product_sizes WHERE id = ?",
            (size_id,),
        ).fetchone()
    return {
        "exito": True,
        "size": {"id": row["id"], "product_id": row["product_id"], "size_label": row["size_label"],
                 "dimensions": row["dimensions"], "price_modifier": row["price_modifier"]},
    }


def eliminar_tamano_producto(size_id: int) -> dict:
    """Elimina un tamaño de producto."""
    with get_db() as conn:
        exists = conn.execute("SELECT 1 FROM product_sizes WHERE id = ?", (size_id,)).fetchone()
        if not exists:
            return {"exito": False, "mensaje": "Tamaño no encontrado."}
        conn.execute("DELETE FROM product_sizes WHERE id = ?", (size_id,))
    return {"exito": True, "mensaje": f"Tamaño #{size_id} eliminado."}


# ── Cálculo de precio con modificadores ──────────────────────────────────────

def calcular_precio_con_modificadores(
    precio_base: float,
    wood_modifier: float = 1.0,
    size_modifier: float = 1.0,
) -> float:
    """Calcula el precio final aplicando modificadores de madera y tamaño."""
    return round(precio_base * wood_modifier * size_modifier, 2)


def obtener_rango_precios_producto(product_id: int, precio_base: float) -> dict:
    """Calcula el rango de precios (mínimo - máximo) para un producto según maderas y tamaños."""
    with get_db() as conn:
        wood_rows = conn.execute(
            "SELECT price_modifier FROM wood_types WHERE active = 1"
        ).fetchall()
        size_rows = conn.execute(
            "SELECT price_modifier FROM product_sizes WHERE product_id = ?",
            (product_id,),
        ).fetchall()

    wood_mods = [r["price_modifier"] for r in wood_rows] or [1.0]
    size_mods = [r["price_modifier"] for r in size_rows] or [1.0]

    min_price = round(precio_base * min(wood_mods) * min(size_mods), 2)
    max_price = round(precio_base * max(wood_mods) * max(size_mods), 2)
    return {"min": min_price, "max": max_price}


def obtener_catalogo_completo() -> dict:
    """Devuelve el catálogo completo de productos con precios base, rangos, maderas y tamaños disponibles."""
    with get_db() as conn:
        rows = conn.execute(
            """
            SELECT id, name, stock, price,
                   COALESCE(temperature, 'ESTANDAR') AS temperature,
                   COALESCE(category, 'MOBILIARIO') AS category
            FROM products
            WHERE stock > 0 AND menu_visible = 1
            ORDER BY category, name
            """
        ).fetchall()

        wood_rows = conn.execute(
            "SELECT id, name, price_modifier, description FROM wood_types WHERE active = 1 ORDER BY price_modifier"
        ).fetchall()
        wood_types = [
            {
                "id": w["id"],
                "name": w["name"],
                "price_modifier": w["price_modifier"],
                "description": w["description"],
            }
            for w in wood_rows
        ]

    productos = []
    for r in rows:
        pid = r["id"]
        precio_base = r["price"]

        size_rows_prod = []
        with get_db() as conn2:
            size_rows_prod = conn2.execute(
                "SELECT id, product_id, size_label, dimensions, price_modifier FROM product_sizes WHERE product_id = ? ORDER BY price_modifier",
                (pid,),
            ).fetchall()

        sizes = [
            {
                "id": s["id"],
                "size_label": s["size_label"],
                "dimensions": s["dimensions"],
                "price_modifier": s["price_modifier"],
                "precio_calculado": round(precio_base * s["price_modifier"], 2),
            }
            for s in size_rows_prod
        ]

        wood_mods = [w["price_modifier"] for w in wood_rows] or [1.0]
        size_mods = [s["price_modifier"] for s in size_rows_prod] or [1.0]

        precio_minimo = round(precio_base * min(wood_mods) * min(size_mods), 2)
        precio_maximo = round(precio_base * max(wood_mods) * max(size_mods), 2)

        productos.append(
            {
                "id": pid,
                "nombre": r["name"],
                "precio_base": precio_base,
                "precio_minimo": precio_minimo,
                "precio_maximo": precio_maximo,
                "categoria": r["category"],
                "tamanos": sizes,
            }
        )

    return {
        "productos": productos,
        "tipos_madera": wood_types,
        "total": len(productos),
    }

