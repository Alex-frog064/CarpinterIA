OLLAMA_ADMIN_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "consultar_inventario",
            "description": "Consulta el inventario completo de la carpintería: servicios, stock de materiales, precios base y mínimos.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_venta",
            "description": "Registra una cotización confirmada / venta de un servicio de carpintería y descuenta la disponibilidad del inventario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "producto": {
                        "type": "string",
                        "description": "Nombre del servicio vendido (ej: Closet, Mueble a medida).",
                    },
                    "cantidad": {
                        "type": "number",
                        "description": "Cantidad vendida.",
                    },
                },
                "required": ["producto", "cantidad"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "registrar_gasto",
            "description": "Registra un gasto operativo de la carpintería (proveedores de madera, herramientas, servicios, insumos, etc.).",
            "parameters": {
                "type": "object",
                "properties": {
                    "concepto": {
                        "type": "string",
                        "description": "Descripción del gasto.",
                    },
                    "monto": {
                        "type": "number",
                        "description": "Monto del gasto en la moneda local.",
                    },
                },
                "required": ["concepto", "monto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_producto_mas_vendido",
            "description": "Obtiene el servicio de carpintería más cotizado/vendido históricamente con cantidades e ingresos.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "obtener_ganancia_dia",
            "description": "Calcula ingresos, gastos y ganancia neta del día actual en la carpintería.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "productos_bajo_stock",
            "description": "Lista servicios o materiales cuyo stock está en o por debajo del mínimo configurado.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recomendar_compra",
            "description": "Genera recomendaciones de compra de materiales para la carpintería.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]

ADMIN_SYSTEM_PROMPT = """Eres Carpintería IA en modo administrador.

Eres un asistente amigable y conversacional. Hablas español de México.
Ayudas con inventario de servicios y materiales, ventas, gastos, ganancias, cotizaciones y recomendaciones de compra de insumos de madera.

Cuando el usuario pregunte datos del negocio, usa las herramientas disponibles.
Responde de forma clara, breve y natural.
Presenta los datos de forma legible (listas, totales, resúmenes).
Si una operación falla, explica el error al usuario.
No fuerces cotizaciones; solo menciónalas si el usuario lo pide."""
