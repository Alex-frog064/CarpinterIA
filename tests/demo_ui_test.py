import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


class DemoUiTests(unittest.TestCase):
    def test_frontend_demo_components(self):
        app_js = (ROOT / "frontend" / "app.js").read_text()
        index_html = (ROOT / "frontend" / "index.html").read_text()
        style_css = (ROOT / "frontend" / "style.css").read_text()

        checks_js = [
            "renderOrderConfirmationCard",
            "renderOrderTimeline",
            "appendOrderConfirmationCard",
            "renderCustomerOrderCard",
            "splashScreen",
            "bootstrap",
            "saveProductRow",
            "/admin/dashboard",
        ]
        for check in checks_js:
            self.assertIn(check, app_js, f"Falta en app.js: {check}")

        self.assertIn("splash-screen", index_html)
        self.assertIn("dashboard-cards", index_html)
        self.assertIn("orders-list", index_html)

        css_checks = [
            "order-confirmed-card",
            "order-timeline",
            "dashboard-card",
            "splash-screen",
            "avatar-user",
            "toggle-switch",
        ]
        for check in css_checks:
            self.assertIn(check, style_css, f"Falta en style.css: {check}")

    def test_order_display_helper(self):
        from services.order_display import build_order_card, estimated_minutes

        card = build_order_card(
            {
                "id": 1,
                "customer_name": "Andrés",
                "items": [{"producto": "Frappe de oreo", "cantidad": 1}],
                "total": 90.0,
                "status": "CONFIRMED",
                "delivery_type": "domicilio",
            }
        )
        self.assertEqual(card["order_id"], 1)
        self.assertEqual(card["estimated_minutes"], 30)
        self.assertEqual(estimated_minutes("recoger"), 15)

    def test_dashboard_stats(self):
        import shutil
        import tempfile

        import database.db as db_module

        test_db = Path(tempfile.mkdtemp()) / "demo.db"
        db_module.DB_PATH = test_db
        from database.db import init_db
        from tools.carpentry_tools import obtener_stats_dashboard

        init_db()
        stats = obtener_stats_dashboard()
        self.assertIn("ventas_dia", stats)
        self.assertIn("pedidos_activos", stats)
        self.assertIn("pedidos_cancelados", stats)
        self.assertIn("usuarios_registrados", stats)
        self.assertGreaterEqual(stats["usuarios_registrados"], 2)
        if test_db.exists():
            test_db.unlink()
        shutil.rmtree(test_db.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
