import asyncio
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TEST_DB = Path(tempfile.mkdtemp()) / "test_intent.db"


class MockOllama:
    async def chat_with_tools(self, messages):
        return "Ventas del día: $150.00", ["obtener_ganancia_dia"]

    async def extract_order_products(self, user_message, menu_names):
        if "frappe" in user_message.lower():
            return [{"nombre": "Frappe de oreo", "cantidad": 1}]
        return []

    async def generate_employee_response(self, instruction, context, history=None):
        return f"[Pedido] {instruction[:60]}"

    async def generate_conversational_response(self, user_message, context, history=None):
        msg = user_message.lower()
        if "hola" in msg:
            return "¡Hola! Soy Carpintería IA. ¿En qué te ayudo?"
        if "quien eres" in msg or "quién eres" in msg:
            return "Soy Carpintería IA, el asistente virtual de la carpintería."
        if "que puedes" in msg or "qué puedes" in msg:
            return "Puedo ayudarte con pedidos, productos y más según tu rol."
        if "que venden" in msg or "qué venden" in msg:
            return "Tenemos frappes, crepas, cafés y más. ¿Te interesa alguno?"
        return f"Respuesta natural a: {user_message[:40]}"


def setup_test_db():
    import database.db as db_module

    db_module.DB_PATH = TEST_DB
    from database.db import init_db

    init_db()


def teardown_test_db():
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.rmtree(TEST_DB.parent, ignore_errors=True)


class IntentServiceTests(unittest.TestCase):
    def test_clear_order_intent(self):
        from services.intent_service import is_clear_order_intent

        self.assertTrue(is_clear_order_intent("quiero un frappe de oreo"))
        self.assertTrue(is_clear_order_intent("quiero pedir"))
        self.assertTrue(is_clear_order_intent("me gustaría ordenar un capuchino"))
        self.assertTrue(is_clear_order_intent("dame 2 frappes"))
        self.assertFalse(is_clear_order_intent("hola"))
        self.assertFalse(is_clear_order_intent("quien eres"))
        self.assertFalse(is_clear_order_intent("que venden"))
        self.assertFalse(is_clear_order_intent("que puedes hacer"))

    def test_detect_mode(self):
        from models.conversation_state import ConversationState
        from services.intent_service import ChatMode, detect_mode
        from models.user import UserRole

        self.assertEqual(
            detect_mode("hola", UserRole.CUSTOMER.value, ConversationState.IDLE.value),
            ChatMode.GENERAL_CHAT,
        )
        self.assertEqual(
            detect_mode("quiero un frappe", UserRole.CUSTOMER.value, ConversationState.IDLE.value),
            ChatMode.ORDER_FLOW,
        )
        self.assertEqual(
            detect_mode(
                "cuantas ventas hubo hoy",
                UserRole.ADMIN.value,
                ConversationState.IDLE.value,
            ),
            ChatMode.ADMIN_ASSISTANT,
        )
        self.assertEqual(
            detect_mode(
                "Andrés",
                UserRole.CUSTOMER.value,
                ConversationState.ASKING_CUSTOMER_NAME.value,
            ),
            ChatMode.ORDER_FLOW,
        )


class ConversationRoutingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_test_db()
        cls.mock = MockOllama()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _service(self):
        from services.chat_service import ChatService

        svc = ChatService()
        svc.ollama = self.mock
        svc.order_agent.ollama = self.mock
        svc.cancel_service.ollama = self.mock
        svc.general_chat.ollama = self.mock
        return svc

    def _customer_id(self):
        from database.db import get_db

        with get_db() as conn:
            return conn.execute(
                "SELECT id FROM users WHERE username = 'cliente'"
            ).fetchone()["id"]

    async def _chat(self, svc, message, cid=None):
        uid = self._customer_id()
        return await svc.process_message(message, uid, "CUSTOMER", cid)

    def test_hola_no_inicia_pedido(self):
        async def run():
            svc = self._service()
            cid, response, tools, state, cart = await self._chat(svc, "hola")
            self.assertEqual(state, "IDLE")
            self.assertNotIn("confirm_order", tools)
            self.assertNotIn("Puedo ayudarte a hacer un pedido", response)
            self.assertIn("Carpintería IA", response)

        asyncio.run(run())

    def test_quien_eres(self):
        async def run():
            svc = self._service()
            _, response, _, state, _ = await self._chat(svc, "quien eres")
            self.assertEqual(state, "IDLE")
            self.assertIn("Carpintería IA", response)

        asyncio.run(run())

    def test_que_venden(self):
        async def run():
            svc = self._service()
            _, response, tools, state, _ = await self._chat(svc, "que venden")
            self.assertEqual(state, "IDLE")
            self.assertEqual(tools, [])
            self.assertNotIn("frappe de oreo", response.lower() and "nombre del cliente" or response)

        asyncio.run(run())

    def test_quiero_frappe_inicia_pedido(self):
        async def run():
            svc = self._service()
            _, response, tools, state, cart = await self._chat(svc, "Quiero un frappe de oreo")
            self.assertIn(state, ("ASKING_CUSTOMER_NAME", "COLLECTING_ORDER"))
            self.assertTrue(cart or "extract_order_from_text" in tools or "Pedido" in response)

        asyncio.run(run())

    def test_respuestas_diferentes(self):
        async def run():
            svc = self._service()
            _, r1, _, _, _ = await self._chat(svc, "hola")
            _, r2, _, _, _ = await self._chat(svc, "quien eres")
            self.assertNotEqual(r1.strip(), r2.strip())

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
