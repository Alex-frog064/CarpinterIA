import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

# Configurar path del proyecto
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Base de datos temporal para pruebas
TEST_DB = Path(tempfile.mkdtemp()) / "test_audit.db"


class MockOllama:
    """Mock de Ollama para pruebas sin red."""

    async def chat_with_tools(self, messages):
        return "Modo administración activo.", []

    async def extract_order_products(self, user_message, menu_names):
        return []

    async def generate_employee_response(self, instruction, context, history=None):
        instr = instruction.lower()
        if "nombre" in instr:
            return "¿A nombre de quién será el pedido?"
        if "recoger" in instr or "domicilio" in instr:
            return "¿Será para recoger o para entrega a domicilio?"
        if "dirección" in instr:
            return "¿Cuál es tu dirección?"
        if "ubicación" in instr or "botón" in instr:
            return "Comparte tu ubicación usando el botón 📍"
        if "confirma" in instr and "pedido" in instr:
            return "¿Deseas confirmar el pedido?"
        if "registrado" in instr or "exitosamente" in instr:
            return "¡Pedido confirmado! Venta registrada correctamente."
        if "cancelado" in instr:
            return "Pedido cancelado."
        return f"[Mock] {instruction[:80]}"

    async def generate_conversational_response(self, user_message, context, history=None):
        if "hola" in user_message.lower():
            return "¡Hola! Soy Carpintería IA."
        return f"[Mock chat] {user_message[:40]}"


def setup_test_db():
    import database.db as db_module

    db_module.DB_PATH = TEST_DB
    from database.db import init_db

    init_db()


def teardown_test_db():
    if TEST_DB.exists():
        TEST_DB.unlink()
    shutil.rmtree(TEST_DB.parent, ignore_errors=True)


class AuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        setup_test_db()
        cls.mock_ollama = MockOllama()

    @classmethod
    def tearDownClass(cls):
        teardown_test_db()

    def _new_chat_service(self):
        from services.chat_service import ChatService

        svc = ChatService()
        svc.ollama = self.mock_ollama
        svc.order_agent.ollama = self.mock_ollama
        svc.cancel_service.ollama = self.mock_ollama
        svc.general_chat.ollama = self.mock_ollama
        return svc

    def _customer_id(self):
        from database.db import get_db

        with get_db() as conn:
            row = conn.execute(
                "SELECT id FROM users WHERE username = 'cliente'"
            ).fetchone()
        return row["id"]

    async def _chat(self, svc, message, cid=None):
        uid = self._customer_id()
        return await svc.process_message(message, uid, "CUSTOMER", cid)

    async def _location(self, svc, cid, lat, lng):
        uid = self._customer_id()
        return await svc.process_location(cid, lat, lng, uid, "CUSTOMER")

    def test_caso1_flujo_completo_domicilio(self):
        async def run():
            svc = self._new_chat_service()
            cid = None

            steps = [
                ("Quiero una Mesa de comedor (120x80cm)", "ASKING_CUSTOMER_NAME"),
                ("Andrés", "ASKING_DELIVERY_TYPE"),
                ("Domicilio", "ASKING_ADDRESS"),
                ("Calle 50 #123", "ASKING_LOCATION"),
            ]

            for msg, expected_state in steps:
                cid, _, tools, state, cart = await self._chat(svc, msg, cid)
                self.assertEqual(state, expected_state, f"Fallo en '{msg}': estado {state}")
                if msg.startswith("Quiero"):
                    self.assertTrue(len(cart) >= 1, "Carrito vacío tras detectar producto")
                    self.assertEqual(cart[0]["producto"], "Mesa de comedor (120x80cm)")

            # Ubicación GPS
            cid, _, tools, state, cart = await self._location(svc, cid, 19.4326, -99.1332)
            self.assertEqual(state, "CONFIRMING_ORDER")
            self.assertIn("save_customer_location", tools)

            # Confirmar pedido
            from database.db import get_db
            from tools.carpentry_tools import buscar_producto

            product = buscar_producto("Mesa de comedor (120x80cm)")
            stock_before = product["stock"]

            cid, _, tools, state, cart = await self._chat(svc, "Sí", cid)
            self.assertEqual(state, "ORDER_COMPLETED")
            self.assertIn("confirm_order", tools)

            product_after = buscar_producto("Mesa de comedor (120x80cm)")
            self.assertEqual(product_after["stock"], stock_before - 1, "Stock no descontado")

            with get_db() as conn:
                orders = conn.execute(
                    "SELECT * FROM orders WHERE conversation_id = ?", (cid,)
                ).fetchall()
                sales = conn.execute(
                    "SELECT COUNT(*) as c FROM sales s JOIN products p ON p.id = s.product_id WHERE p.name = ?",
                    ("Mesa de comedor (120x80cm)",),
                ).fetchone()["c"]

            self.assertEqual(len(orders), 1, f"Pedidos duplicados: {len(orders)}")
            self.assertEqual(orders[0]["status"], "CONFIRMED")
            self.assertEqual(sales, 1, "Ventas duplicadas")

            # Doble confirmación no debe duplicar ventas
            cid2, _, _, state2, _ = await self._chat(svc, "Sí", cid)
            with get_db() as conn:
                sales2 = conn.execute(
                    "SELECT COUNT(*) as c FROM sales s JOIN products p ON p.id = s.product_id WHERE p.name = ?",
                    ("Mesa de comedor (120x80cm)",),
                ).fetchone()["c"]
            self.assertEqual(sales2, 1, "Venta duplicada tras doble confirmación")

            return cid

        asyncio.run(run())

    def test_caso2_persistencia_estado(self):
        async def run():
            svc1 = self._new_chat_service()
            cid, _, _, state, cart = await self._chat(svc1, "Quiero una Mesa de comedor (120x80cm)", None)
            self.assertEqual(state, "ASKING_CUSTOMER_NAME")
            self.assertEqual(len(cart), 1)

            # Simular recarga: nuevo servicio, mismo conversation_id
            svc2 = self._new_chat_service()
            uid = self._customer_id()
            st = svc2.get_conversation_state(cid, uid, "CUSTOMER")
            self.assertEqual(st["state"], "ASKING_CUSTOMER_NAME")
            self.assertEqual(len(st["cart"]), 1)
            self.assertEqual(st["cart"][0]["producto"], "Mesa de comedor (120x80cm)")

            cid2, _, _, state2, cart2 = await self._chat(svc2, "Andrés", cid)
            self.assertEqual(cid2, cid)
            self.assertEqual(state2, "ASKING_DELIVERY_TYPE")

        asyncio.run(run())

    def test_caso5_ventas_descuentan_inventario(self):
        from tools.carpentry_tools import buscar_producto, registrar_venta

        product = buscar_producto("Silla de madera (Estándar)")
        if not product:
            self.skipTest("Silla de madera (Estándar) no en menú")
        stock = product["stock"]
        r = registrar_venta("Silla de madera (Estándar)", 1)
        self.assertTrue(r["exito"])
        after = buscar_producto("Silla de madera (Estándar)")
        self.assertEqual(after["stock"], stock - 1)

    def test_caso6_no_pedidos_duplicados(self):
        async def run():
            svc = self._new_chat_service()
            cid, _, _, _, _ = await self._chat(svc, "Quiero una Mesa de comedor (120x80cm)", None)
            await self._chat(svc, "Andrés", cid)
            await self._chat(svc, "Domicilio", cid)

            from database.db import get_db

            with get_db() as conn:
                count = conn.execute(
                    "SELECT COUNT(*) as c FROM orders WHERE conversation_id = ? AND status = 'PENDING'",
                    (cid,),
                ).fetchone()["c"]
            self.assertEqual(count, 1, "Múltiples pedidos PENDING creados")

        asyncio.run(run())

    def test_caso4_ubicacion_guardada(self):
        async def run():
            svc = self._new_chat_service()
            cid, _, _, _, _ = await self._chat(svc, "Quiero una Mesa de comedor (120x80cm)", None)
            await self._chat(svc, "Andrés", cid)
            await self._chat(svc, "Domicilio", cid)
            await self._chat(svc, "Calle 50 #123", cid)

            cid, _, tools, state, _ = await self._location(svc, cid, 19.5, -99.1)
            self.assertEqual(state, "CONFIRMING_ORDER")

            uid = self._customer_id()
            st = svc.get_conversation_state(cid, uid, "CUSTOMER")
            self.assertAlmostEqual(st["latitude"], 19.5)
            self.assertAlmostEqual(st["longitude"], -99.1)

            from database.db import get_db

            with get_db() as conn:
                order = conn.execute(
                    "SELECT latitude, longitude FROM orders WHERE conversation_id = ? ORDER BY id DESC LIMIT 1",
                    (cid,),
                ).fetchone()
            self.assertIsNotNone(order["latitude"])

        asyncio.run(run())

    def test_caso3_frontend_manejo_errores(self):
        app_js = (ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        checks = [
            "SpeechRecognition",
            "webkitSpeechRecognition",
            "recognition.onerror",
            "navigator.geolocation",
            "showStatusBanner",
            "No se pudo obtener la ubicación",
            "Tu navegador no soporta voz",
            "carpinteria_auth",
            "Authorization",
            "extractAssistantText",
            "CHAT RESPONSE:",
            "LOCATION_STATES",
            "ORDER_FLOW_STATES",
            "CONFIRMING_STATES",
        ]
        for check in checks:
            self.assertIn(check, app_js, f"Falta manejo frontend: {check}")

    def test_confirm_order_idempotente(self):
        from tools.order_tools import create_order, confirm_order, get_active_order

        async def run():
            svc = self._new_chat_service()
            cid, _, _, _, cart = await self._chat(svc, "Quiero una Mesa de comedor (120x80cm)", None)
            order = create_order(
                conversation_id=cid,
                items=cart,
                delivery_type="recoger",
                customer_name="Test",
                status="PENDING",
            )
            r1 = confirm_order(order["order_id"])
            r2 = confirm_order(order["order_id"])
            self.assertTrue(r1["exito"])
            self.assertTrue(r2["exito"])
            self.assertIn("ya confirmado", r2.get("mensaje", "").lower())

        asyncio.run(run())


def run_audit():
    loader = unittest.TestLoader()
    suite = loader.loadTestsFromTestCase(AuditTests)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    return result.wasSuccessful()


if __name__ == "__main__":
    ok = run_audit()
    sys.exit(0 if ok else 1)
