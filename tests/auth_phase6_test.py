import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = Path(tempfile.mkdtemp()) / "test_auth.db"


class MockOllama:
    async def chat_with_tools(self, messages):
        return "Panel admin.", []

    async def extract_order_products(self, user_message, menu_names):
        return []

    async def generate_employee_response(self, instruction, context, history=None):
        instr = instruction.lower()
        if "cancelar" in instr and "pedido" in instr:
            return "¿Deseas cancelar tu pedido #1?"
        if "cancelado" in instr:
            return "Tu pedido fue cancelado. ¿Deseas hacer uno nuevo?"
        if "preparación" in instr or "preparando" in instr:
            return "Tu pedido ya está en preparación y no puede cancelarse."
        return f"[Mock] {instruction[:60]}"

    async def generate_conversational_response(self, user_message, context, history=None):
        return f"[Mock] {user_message[:40]}"


def setup_test_db():
    import database.db as db_module

    db_module.DB_PATH = TEST_DB
    from database.db import init_db

    init_db()


def teardown_test_db():
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.rmtree(TEST_DB.parent, ignore_errors=True)


def login(client, username, password):
    res = client.post("/auth/login", json={"username": username, "password": password})
    assert res.status_code == 200, res.text
    data = res.json()
    return data["token"], data["user"]


def auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


class AuthPhase6Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_test_db()
        from backend.main import app

        cls.client = TestClient(app)
        cls.mock = MockOllama()

        from services.chat_service import ChatService
        from backend import main as main_module

        svc = ChatService()
        svc.ollama = cls.mock
        svc.order_agent.ollama = cls.mock
        svc.cancel_service.ollama = cls.mock
        svc.general_chat.ollama = cls.mock
        main_module.chat_service = svc

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def test_login_admin_y_cliente(self):
        admin_token, admin = login(self.client, "admin", "admin123")
        self.assertEqual(admin["role"], "ADMIN")

        client_token, customer = login(self.client, "cliente", "cliente123")
        self.assertEqual(customer["role"], "CUSTOMER")

        me = self.client.get("/auth/me", headers=auth_headers(admin_token))
        self.assertEqual(me.json()["username"], "admin")

    def test_login_invalido(self):
        res = self.client.post("/auth/login", json={"username": "x", "password": "y"})
        self.assertEqual(res.status_code, 401)

    def test_rutas_protegidas(self):
        res = self.client.get("/conversations")
        self.assertEqual(res.status_code, 401)

    def test_cliente_crea_pedido_y_admin_ve(self):
        token, user = login(self.client, "cliente", "cliente123")
        headers = auth_headers(token)

        from database.db import get_db
        from tools.order_tools import create_order

        chat = self.client.post(
            "/chat",
            headers=headers,
            json={"message": "Hola"},
        )
        self.assertEqual(chat.status_code, 200)
        cid = chat.json()["conversation_id"]

        order = create_order(
            conversation_id=cid,
            items=[{"producto": "Frappe de oreo", "cantidad": 1, "precio": 65.0, "subtotal": 65.0}],
            delivery_type="recoger",
            customer_name="Cliente Test",
            status="PENDING",
        )
        self.assertIn("order_id", order)

        with get_db() as conn:
            row = conn.execute("SELECT user_id FROM orders WHERE id = ?", (order["order_id"],)).fetchone()
        self.assertEqual(row["user_id"], user["id"])

        my_orders = self.client.get("/my/orders", headers=headers)
        self.assertEqual(my_orders.status_code, 200)
        self.assertTrue(any(o["id"] == order["order_id"] for o in my_orders.json()))

        admin_token, _ = login(self.client, "admin", "admin123")
        admin_orders = self.client.get("/admin/orders", headers=auth_headers(admin_token))
        self.assertEqual(admin_orders.status_code, 200)
        found = next(o for o in admin_orders.json() if o["id"] == order["order_id"])
        self.assertEqual(found["username"], "cliente")

    def test_cancelacion_pedido_pendiente(self):
        token, user = login(self.client, "cliente", "cliente123")
        headers = auth_headers(token)

        from tools.order_tools import create_order
        from database.db import get_db
        import uuid

        cid = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute(
                "INSERT INTO conversations (id, user_id) VALUES (?, ?)",
                (cid, user["id"]),
            )
            conn.execute(
                """
                INSERT INTO conversation_state (conversation_id, current_state, cart_json, collected_data_json)
                VALUES (?, 'IDLE', '[]', '{}')
                """,
                (cid,),
            )

        order = create_order(
            conversation_id=cid,
            items=[{"producto": "Frappe de oreo", "cantidad": 1, "precio": 65.0, "subtotal": 65.0}],
            delivery_type="recoger",
            customer_name="Test",
            status="PENDING",
        )
        oid = order["order_id"]

        cancel_res = self.client.post(f"/my/orders/{oid}/cancel", headers=headers)
        self.assertEqual(cancel_res.status_code, 200)
        self.assertEqual(cancel_res.json()["status"], "CANCELLED")

        with get_db() as conn:
            status = conn.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()["status"]
            activity = conn.execute(
                "SELECT action FROM user_activity WHERE user_id = ? AND action = 'CANCEL_ORDER'",
                (user["id"],),
            ).fetchall()
        self.assertEqual(status, "CANCELLED")
        self.assertTrue(any(a["action"] == "CANCEL_ORDER" for a in activity))

    def test_no_cancelar_preparing(self):
        from database.db import get_db
        from tools.order_tools import cancel_order
        import uuid

        token, user = login(self.client, "cliente", "cliente123")
        cid = str(uuid.uuid4())
        with get_db() as conn:
            conn.execute("INSERT INTO conversations (id, user_id) VALUES (?, ?)", (cid, user["id"]))
            conn.execute(
                """
                INSERT INTO orders (conversation_id, user_id, delivery_type, items_json, total, status)
                VALUES (?, ?, 'recoger', '[]', 0, 'PREPARING')
                """,
                (cid, user["id"]),
            )
            oid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        result = cancel_order(oid, user_id=user["id"])
        self.assertFalse(result["exito"])

    def test_cancelacion_por_chat(self):
        async def run():
            token, user = login(self.client, "cliente", "cliente123")
            headers = auth_headers(token)

            from database.db import get_db
            from tools.order_tools import create_order
            import uuid

            cid = str(uuid.uuid4())
            with get_db() as conn:
                conn.execute("INSERT INTO conversations (id, user_id) VALUES (?, ?)", (cid, user["id"]))
                conn.execute(
                    """
                    INSERT INTO conversation_state (conversation_id, current_state, cart_json, collected_data_json)
                    VALUES (?, 'IDLE', '[]', '{}')
                    """,
                    (cid,),
                )

            create_order(
                conversation_id=cid,
                items=[{"producto": "Frappe de oreo", "cantidad": 1, "precio": 65.0, "subtotal": 65.0}],
                delivery_type="recoger",
                customer_name="Test",
                status="PENDING",
            )

            r1 = self.client.post(
                "/chat",
                headers=headers,
                json={"message": "cancelar mi pedido", "conversation_id": cid},
            )
            self.assertEqual(r1.status_code, 200)
            self.assertIn("cancelar", r1.json()["response"].lower())

            r2 = self.client.post(
                "/chat",
                headers=headers,
                json={"message": "sí", "conversation_id": cid},
            )
            self.assertEqual(r2.status_code, 200)
            self.assertIn("cancel_order", r2.json()["tools_used"])

        asyncio.run(run())

    def test_cliente_no_accede_admin(self):
        token, _ = login(self.client, "cliente", "cliente123")
        headers = auth_headers(token)
        self.assertEqual(self.client.get("/admin/users", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/admin/activity", headers=headers).status_code, 403)
        self.assertEqual(self.client.get("/inventory", headers=headers).status_code, 403)

    def test_actividad_login_registrada(self):
        token, user = login(self.client, "cliente", "cliente123")
        from database.db import get_db

        with get_db() as conn:
            rows = conn.execute(
                "SELECT action FROM user_activity WHERE user_id = ? AND action = 'LOGIN'",
                (user["id"],),
            ).fetchall()
        self.assertGreaterEqual(len(rows), 1)

        self.client.post("/auth/logout", headers=auth_headers(token))
        with get_db() as conn:
            logout_rows = conn.execute(
                "SELECT action FROM user_activity WHERE user_id = ? AND action = 'LOGOUT'",
                (user["id"],),
            ).fetchall()
        self.assertGreaterEqual(len(logout_rows), 1)


def run_tests():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(AuthPhase6Tests)
    runner = unittest.TextTestRunner(verbosity=2)
    return runner.run(suite).wasSuccessful()


if __name__ == "__main__":
    sys.exit(0 if run_tests() else 1)
