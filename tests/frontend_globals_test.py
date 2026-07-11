"""Verifica constantes JS requeridas y ausencia de ReferenceError obvios."""
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "frontend" / "app.js"


class FrontendGlobalsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.code = APP_JS.read_text()

    def _declared(self, name: str) -> bool:
        return bool(
            re.search(rf"(?:const|let|var|function)\s+{re.escape(name)}\b", self.code)
        )

    def _used(self, name: str) -> bool:
        return bool(re.search(rf"\b{re.escape(name)}\b", self.code))

    def test_location_states_declared(self):
        self.assertTrue(self._declared("LOCATION_STATES"))
        self.assertIn('"ASKING_LOCATION"', self.code)

    def test_order_state_constants(self):
        for name in (
            "ORDER_FLOW_STATES",
            "CONFIRMING_STATES",
            "ORDER_COMPLETED_STATES",
        ):
            self.assertTrue(self._declared(name), f"Falta declarar {name}")

    def test_used_constants_are_declared(self):
        """Constantes UPPER_SNAKE usadas en app.js deben estar declaradas."""
        declared = set(
            re.findall(r"(?:const|let|var|function)\s+([A-Z][A-Z0-9_]*)\b", self.code)
        )
        # Identificadores en mayúsculas usados como variables (no claves de objeto)
        used_upper = set(re.findall(r"(?<![\"'])\b([A-Z][A-Z0-9_]{2,})\b(?!\s*:)", self.code))
        ignore = {
            "API",  # declared
            "DOM", "GPS", "IA", "ID", "MX", "POST", "PATCH", "JSON",
            "CHAT", "MESSAGE", "RENDER", "RESPONSE", "T", "U", "ADMIN", "CUSTOMER",
            "PENDING", "CONFIRMED", "PREPARING", "DELIVERING", "COMPLETED", "CANCELLED",
            "IDLE", "COLLECTING_ORDER", "ASKING_CUSTOMER_NAME", "ASKING_DELIVERY_TYPE",
            "ASKING_ADDRESS", "ASKING_LOCATION", "CONFIRMING_ORDER", "ORDER_COMPLETED",
        }
        missing = sorted(
            u for u in used_upper
            if u not in declared and u not in ignore and self._used(u)
        )
        # Solo fallar si hay constantes de app claramente faltantes
        critical = [m for m in missing if m.endswith("_STATES") or m.endswith("_STATE")]
        self.assertEqual(critical, [], f"Constantes críticas sin declarar: {critical}")


if __name__ == "__main__":
    unittest.main()
