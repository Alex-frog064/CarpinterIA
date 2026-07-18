"""Optimized data seeder for stress testing.

Generates 10,000+ realistic records (targeting 50,000) for the Carpinteria SQLite database.
Uses bulk inserts and transactions for performance.

Usage:
    python scripts/seeder.py
    python scripts/seeder.py --count 50000
    python scripts/seeder.py --reset
"""

import argparse
import hashlib
import json
import random
import secrets
import sqlite3
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from database.db import DB_PATH

# --- Data constants ---

FIRST_NAMES = [
    "María", "Juan", "Carlos", "Ana", "Pedro", "Laura", "Miguel", "Sofía",
    "José", "Elena", "Roberto", "Carmen", "Fernando", "Isabel", "Antonio",
    "Patricia", "Luis", "Rosa", "Jorge", "Marta", "Diego", "Lucía", "Ricardo",
    "Valentina", "Francisco", "Camila", "Sergio", "Daniela", "Alejandro", "Paula",
    "Andrés", "Adriana", "Manuel", "Claudia", "David", "Gabriela", "Daniel",
    "Alicia", "Raúl", "Beatriz", "Pablo", "Teresa", "Eduardo", "Natalia",
    "Tomás", "Diana", "Santiago", "Fernanda", "Óscar", "Victoria",
]

LAST_NAMES = [
    "García", "López", "Hernández", "Martínez", "González", "Rodríguez",
    "Pérez", "Sánchez", "Ramírez", "Torres", "Flores", "Rivera", "Gómez",
    "Díaz", "Cruz", "Morales", "Reyes", "Ortiz", "Gutiérrez", "Chávez",
    "Ramos", "Ruiz", "Alvarez", "Mendoza", "Castillo", "Jiménez", "Vargas",
    "Romero", "Medina", "Herrera", "Aguilar", "Rangel", "Castro", "Vázquez",
]

STREETS = [
    "Morelos", "Hidalgo", "Juárez", "Revolución", "Independencia",
    "Madero", "Zaragoza", "Allende", "Iturbide", "Aldama",
    "5 de Mayo", "16 de Septiembre", "20 de Noviembre", "Benito Juárez",
    "Insurgentes", "Reforma", "Paseo de la Reforma", "Av. Universidad",
]

NEIGHBORHOODS = [
    "Centro", "La Condesa", "Roma Norte", "Coyoacán", "San Ángel",
    "Del Valle", "Narvarte", "Escandón", "Hipódromo", "Juárez",
    "Tlalpan", "Coyoacán", "Azcapotzalco", "Gustavo A. Madero",
    "Iztacalco", "Venustiano Carranza",
]

CITIES = ["CDX", "Guadalajara", "Monterrey", "Puebla", "Querétaro", "Toluca"]

PRODUCTS = [
    "Mueble a medida", "Puerta de madera", "Closet", "Cocina integral",
    "Mesa de comedor", "Restauración", "Piso de madera", "Librero",
    "Escalera", "Ventana",
]

ORDER_STATUSES = ["PENDING", "CONFIRMED", "PREPARING", "DELIVERING", "COMPLETED", "CANCELLED"]
STATUS_WEIGHTS = [20, 30, 15, 10, 20, 5]

DELIVERY_TYPES = ["recoger", "domicilio"]
DELIVERY_WEIGHTS = [40, 60]

STATES = ["IDLE", "COLLECTING_INFO", "CONFIRMING_ORDER", "AWAITING_PAYMENT", "COMPLETED"]

USER_MESSAGES = [
    "Hola, ¿qué servicios ofrecen?",
    "Quisiera cotizar un closet",
    "¿Cuánto cuesta una puerta de madera?",
    "¿Qué tipos de madera tienen?",
    "Quiero pedir una mesa de comedor para 6 personas",
    "¿Hacen envíos a domicilio?",
    "Necesito un mueble a medida",
    "¿Cuánto tarda en estar listo un closet?",
    "Quiero cancelar mi pedido",
    "¿Qué horario tienen?",
    "Buenos días",
    "¿Tienen kokos?",
    "¿Cuánto cuesta instalar un piso de madera?",
    "Me gustaría conocer el catálogo",
    "¿Cuánto cuesta una escalera de madera?",
]

ASSISTANT_RESPONSES = [
    "¡Hola! Bienvenido a Carpintería Artesanal. ¿En qué puedo ayudarte?",
    "¡Claro! Tenemos closets desde $5,500 MXN. ¿Qué tamaño necesitas?",
    "Las puertas de madera están desde $1,800 MXN. ¿Le interesa alguna en particular?",
    "Trabajamos con MDF, Pino, Cedro, Roble, Nogal y Caoba. ¿Tiene preferencia?",
    "Perfecto, una mesa de 6 personas como la de $5,800 MXN. ¿Qué tipo de madera le gustaría?",
    "Sí, ofrecemos envío a domicilio por $150 MXN adicionales. ¿En qué zona se encuentra?",
    "¡Excelente! Para un mueble a medida necesitamos conocer sus medidas y preferencias.",
    "Un closet tarda aproximadamente 10-15 días hábiles en estar listo.",
    "Entendido. Para cancelar su pedido, necesito el número de orden.",
    "Nuestro horario es de lunes a viernes de 9:00 a 18:00 y sábados de 9:00 a 14:00.",
    "¡Buenos días! ¿Cómo puedo ayudarle hoy?",
    "No contamos con kokos, pero sí con多种tipos de madera de calidad.",
    "La instalación de piso de madera tiene un costo adicional de $150 por m².",
    "¡Por supuesto! Puede ver nuestro catálogo completo en la sección de productos.",
    "Una escalera de madera tiene un precio base de $8,500 MXN, dependiendo de los peldaños.",
]

EXPENSE_CONCEPTS = [
    "Compra de madera de pino", "Compra de madera de cedro", "Herramientas nuevas",
    "Mantenimiento de taller", "Transporte de materiales", "Barniz y pintura",
    "Tornillos y herrajes", "Alquiler de equipo", "Servicio de electricista",
    "Limpieza del taller", "Papelería y útiles", "Capacitación del personal",
    "Seguro del taller", "Publicidad en redes", "Mantenimiento de vehículo",
    "Suministros de oficina", "Reparación de herramientas", "Flete de entrega",
    "Material de empaque", "Licencias y permisos",
]

ACTIVITY_ACTIONS = [
    "login", "view_order", "create_order", "update_order", "cancel_order",
    "view_products", "search_products", "view_conversation", "send_message",
    "update_stock", "view_reports", "export_data", "change_settings",
]


def _hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120_000).hex()
    return f"{salt}${digest}"


def _random_date(start: datetime, end: datetime, rng: random.Random) -> datetime:
    delta = end - start
    random_seconds = rng.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=random_seconds)


def _generate_items_json(rng: random.Random) -> list[dict]:
    num_items = rng.randint(1, 3)
    items = []
    for _ in range(num_items):
        product = rng.choice(PRODUCTS)
        quantity = rng.randint(1, 5)
        base_price = rng.uniform(800, 8000)
        items.append({
            "producto": product,
            "cantidad": quantity,
            "precio": round(base_price, 2),
            "subtotal": round(base_price * quantity, 2),
        })
    return items


def seed_database(target_count: int = 50000, db_path: str | None = None) -> dict:
    """Seed the database with realistic test data.

    Args:
        target_count: Number of conversations to generate (default 50000).
        db_path: Path to SQLite database. Uses DB_PATH from database.db if None.

    Returns:
        dict with stats about the seeding operation.
    """
    db_path = Path(db_path) if db_path else DB_PATH
    print(f"Database: {db_path}")
    print(f"Target: {target_count:,} conversations")

    rng = random.Random(42)
    start_time = time.time()

    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = OFF")

    try:
        # Ensure schema exists
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tools_used TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS products (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                stock REAL NOT NULL DEFAULT 0,
                price REAL NOT NULL DEFAULT 0,
                min_stock REAL NOT NULL DEFAULT 5
            );
            CREATE TABLE IF NOT EXISTS sales (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                product_id INTEGER NOT NULL,
                quantity REAL NOT NULL,
                total REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (product_id) REFERENCES products(id)
            );
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                concept TEXT NOT NULL,
                amount REAL NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                customer_name TEXT,
                delivery_type TEXT NOT NULL,
                address TEXT,
                latitude REAL,
                longitude REAL,
                items_json TEXT NOT NULL,
                subtotal REAL NOT NULL DEFAULT 0,
                total REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                user_id INTEGER REFERENCES users(id),
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS conversation_state (
                conversation_id TEXT PRIMARY KEY,
                current_state TEXT NOT NULL DEFAULT 'IDLE',
                cart_json TEXT DEFAULT '[]',
                collected_data_json TEXT DEFAULT '{}',
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (conversation_id) REFERENCES conversations(id)
            );
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT NOT NULL,
                role TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS user_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                details TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

        # Clear existing data from seeder tables (keep users, products, wood_types, product_sizes)
        tables_to_clear = [
            "conversation_state", "messages", "orders", "sales", "expenses",
            "user_activity", "conversations",
        ]
        for table in tables_to_clear:
            conn.execute(f"DELETE FROM {table}")

        # Ensure admin and customer users exist
        _ensure_users(conn)

        # Get user IDs
        user_ids = [row[0] for row in conn.execute("SELECT id FROM users").fetchall()]
        customer_user_ids = [
            row[0] for row in conn.execute("SELECT id FROM users WHERE role = 'CUSTOMER'").fetchall()
        ]
        if not customer_user_ids:
            customer_user_ids = user_ids

        # Get product IDs for sales
        product_ids = [
            row[0] for row in conn.execute("SELECT id FROM products").fetchall()
        ]
        if not product_ids:
            product_ids = [1]

        # --- Generate conversations ---
        print("Generating conversations...")
        now = datetime.now()
        start_date = now - timedelta(days=90)

        conv_ids = []
        conv_rows = []
        for i in range(target_count):
            conv_id = str(uuid.uuid4())
            conv_ids.append(conv_id)
            created_at = _random_date(start_date, now, rng).strftime("%Y-%m-%d %H:%M:%S")
            conv_rows.append((conv_id, created_at))

        conn.executemany(
            "INSERT INTO conversations (id, created_at) VALUES (?, ?)",
            conv_rows,
        )
        print(f"  Inserted {target_count:,} conversations")

        # --- Generate messages (2-8 per conversation) ---
        print("Generating messages...")
        msg_rows = []
        conv_state_rows = []
        for i, conv_id in enumerate(conv_ids):
            num_messages = rng.randint(2, 8)
            msg_time = datetime.strptime(conv_rows[i][1], "%Y-%m-%d %H:%M:%S")

            for j in range(num_messages):
                role = "user" if j % 2 == 0 else "assistant"
                if role == "user":
                    content = rng.choice(USER_MESSAGES)
                else:
                    content = rng.choice(ASSISTANT_RESPONSES)

                msg_time += timedelta(seconds=rng.randint(5, 300))
                created_at = msg_time.strftime("%Y-%m-%d %H:%M:%S")
                tools_used = None
                if role == "assistant" and rng.random() < 0.3:
                    tools_used = json.dumps([rng.choice(["order_tools", "carpentry_tools", "rag_agent"])])
                msg_rows.append((conv_id, role, content, tools_used, created_at))

            # Generate conversation_state
            state = rng.choice(STATES)
            cart = _generate_items_json(rng) if state != "IDLE" else []
            collected = {}
            if state in ("COLLECTING_INFO", "CONFIRMING_ORDER"):
                collected = {
                    "delivery_type": rng.choice(DELIVERY_TYPES),
                    "address": _random_address(rng),
                    "customer_name": _random_name(rng),
                }
            conv_state_rows.append((
                conv_id, state,
                json.dumps(cart, ensure_ascii=False),
                json.dumps(collected, ensure_ascii=False),
                msg_time.strftime("%Y-%m-%d %H:%M:%S"),
            ))

            if (i + 1) % 5000 == 0:
                print(f"  Messages progress: {i + 1:,}/{target_count:,}")

        conn.executemany(
            "INSERT INTO messages (conversation_id, role, content, tools_used, created_at) VALUES (?, ?, ?, ?, ?)",
            msg_rows,
        )
        print(f"  Inserted {len(msg_rows):,} messages")

        conn.executemany(
            "INSERT INTO conversation_state (conversation_id, current_state, cart_json, collected_data_json, updated_at) VALUES (?, ?, ?, ?, ?)",
            conv_state_rows,
        )
        print(f"  Inserted {len(conv_state_rows):,} conversation states")

        # --- Generate orders (~60% of conversations) ---
        print("Generating orders...")
        order_conv_ids = rng.sample(conv_ids, min(int(target_count * 0.6), len(conv_ids)))
        order_rows = []
        sale_rows = []

        for conv_id in order_conv_ids:
            conv_idx = conv_ids.index(conv_id)
            customer_name = _random_name(rng)
            delivery_type = rng.choices(DELIVERY_TYPES, weights=DELIVERY_WEIGHTS, k=1)[0]
            address = _random_address(rng) if delivery_type == "domicilio" else None
            latitude = round(rng.uniform(19.3, 19.5), 6) if delivery_type == "domicilio" else None
            longitude = round(rng.uniform(-99.2, -99.0), 6) if delivery_type == "domicilio" else None
            items = _generate_items_json(rng)
            subtotal = round(sum(item["subtotal"] for item in items), 2)
            delivery_fee = 150.0 if delivery_type == "domicilio" else 0.0
            total = round(subtotal + delivery_fee, 2)
            status = rng.choices(ORDER_STATUSES, weights=STATUS_WEIGHTS, k=1)[0]
            user_id = rng.choice(customer_user_ids) if customer_user_ids else None
            created_at = conv_rows[conv_idx][1]

            order_rows.append((
                conv_id, customer_name, delivery_type, address,
                latitude, longitude, json.dumps(items, ensure_ascii=False),
                subtotal, total, status, created_at, user_id,
            ))

            # Generate sales for completed/confirmed orders
            if status in ("COMPLETED", "CONFIRMED", "PREPARING"):
                product_id = rng.choice(product_ids)
                quantity = rng.randint(1, 5)
                sale_total = round(total, 2)
                sale_rows.append((product_id, quantity, sale_total, created_at))

        conn.executemany(
            """INSERT INTO orders
               (conversation_id, customer_name, delivery_type, address,
                latitude, longitude, items_json, subtotal, total, status, created_at, user_id)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            order_rows,
        )
        print(f"  Inserted {len(order_rows):,} orders")

        # --- Generate sales ---
        print("Generating sales...")
        conn.executemany(
            "INSERT INTO sales (product_id, quantity, total, created_at) VALUES (?, ?, ?, ?)",
            sale_rows,
        )
        print(f"  Inserted {len(sale_rows):,} sales")

        # --- Generate expenses (~5000) ---
        print("Generating expenses...")
        expense_count = min(5000, target_count // 10 + 500)
        expense_rows = []
        for i in range(expense_count):
            concept = rng.choice(EXPENSE_CONCEPTS)
            amount = round(rng.uniform(100, 15000), 2)
            created_at = _random_date(start_date, now, rng).strftime("%Y-%m-%d %H:%M:%S")
            expense_rows.append((concept, amount, created_at))

        conn.executemany(
            "INSERT INTO expenses (concept, amount, created_at) VALUES (?, ?, ?)",
            expense_rows,
        )
        print(f"  Inserted {len(expense_rows):,} expenses")

        # --- Generate user activity ---
        print("Generating user activity...")
        activity_count = min(10000, target_count // 5)
        activity_rows = []
        for i in range(activity_count):
            user_id = rng.choice(user_ids)
            action = rng.choice(ACTIVITY_ACTIONS)
            details = f"Action {action} performed"
            created_at = _random_date(start_date, now, rng).strftime("%Y-%m-%d %H:%M:%S")
            activity_rows.append((user_id, action, details, created_at))

        conn.executemany(
            "INSERT INTO user_activity (user_id, action, details, created_at) VALUES (?, ?, ?, ?)",
            activity_rows,
        )
        print(f"  Inserted {len(activity_rows):,} user activity records")

        # Commit all
        conn.commit()
        elapsed = time.time() - start_time

        # Final stats
        stats = {}
        for table in ["conversations", "messages", "orders", "sales", "expenses", "user_activity", "conversation_state"]:
            stats[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        total_records = sum(stats.values())
        records_per_sec = total_records / elapsed if elapsed > 0 else 0

        print(f"\n{'='*50}")
        print(f"SEEDING COMPLETE")
        print(f"{'='*50}")
        print(f"Conversations:     {stats['conversations']:>10,}")
        print(f"Messages:          {stats['messages']:>10,}")
        print(f"Orders:            {stats['orders']:>10,}")
        print(f"Sales:             {stats['sales']:>10,}")
        print(f"Expenses:          {stats['expenses']:>10,}")
        print(f"User Activity:     {stats['user_activity']:>10,}")
        print(f"Conv. States:      {stats['conversation_state']:>10,}")
        print(f"{'='*50}")
        print(f"Total records:     {total_records:>10,}")
        print(f"Time:              {elapsed:>10.2f}s")
        print(f"Records/sec:       {records_per_sec:>10,.0f}")
        print(f"{'='*50}")

        return {
            "stats": stats,
            "total_records": total_records,
            "elapsed_seconds": elapsed,
            "records_per_second": records_per_sec,
        }

    finally:
        conn.close()


def _ensure_users(conn: sqlite3.Connection):
    """Ensure admin and customer users exist."""
    seeds = [
        ("admin", "admin123", "Administrador", "ADMIN"),
        ("cliente", "cliente123", "Cliente Demo", "CUSTOMER"),
    ]
    for username, password, full_name, role in seeds:
        exists = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO users (username, password_hash, full_name, role) VALUES (?, ?, ?, ?)",
                (username, _hash_password(password), full_name, role),
            )


def _random_name(rng: random.Random) -> str:
    return f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)} {rng.choice(LAST_NAMES)}"


def _random_address(rng: random.Random) -> str:
    street_num = rng.randint(1, 500)
    street = rng.choice(STREETS)
    neighborhood = rng.choice(NEIGHBORHOODS)
    city = rng.choice(CITIES)
    return f"Calle {street} {street_num}, Col. {neighborhood}, {city}"


def main():
    parser = argparse.ArgumentParser(description="Seed the Carpinteria database with test data.")
    parser.add_argument("--count", type=int, default=50000, help="Target number of conversations (default: 50000)")
    parser.add_argument("--reset", action="store_true", help="Clear existing data before seeding")
    parser.add_argument("--db", type=str, default=None, help="Path to SQLite database file")
    args = parser.parse_args()

    seed_database(target_count=args.count, db_path=args.db)


if __name__ == "__main__":
    main()
