from models.user import UserRole
from services.intent_service import (
    get_capabilities_text,
    is_capabilities_question,
    is_farewell,
    is_greeting,
    is_hours_question,
    is_identity_question,
    is_menu_request,
    is_product_inquiry,
    is_stock_inquiry,
)
from services.ollama_service import OllamaService
from tools.carpentry_tools import obtener_menu


class GeneralChatService:
    def __init__(self, ollama: OllamaService | None = None):
        self.ollama = ollama or OllamaService()

    def _build_context(self, message: str, role: str) -> str:
        parts: list[str] = []

        if is_menu_request(message):
            menu = obtener_menu().get("productos") or []
            if menu:
                lines = [
                    f"- {p['nombre']}: ${p['precio']:,.2f} (disponible: {int(p['stock'])})"
                    for p in menu
                ]
                parts.append("Catálogo de servicios de la carpintería:\n" + "\n".join(lines))
            else:
                parts.append("No hay servicios activos en el catálogo en este momento.")

        elif is_product_inquiry(message):
            menu = obtener_menu().get("productos") or []
            if menu:
                lines = [
                    f"- {p['nombre']}: ${p['precio']:,.2f} (disponible: {int(p['stock'])})"
                    for p in menu
                ]
                parts.append("Catálogo de servicios de la carpintería:\n" + "\n".join(lines))
            else:
                parts.append("No hay servicios activos en el catálogo en este momento.")

        elif is_stock_inquiry(message):
            menu = obtener_menu().get("productos") or []
            if menu:
                lines = [
                    f"- {p['nombre']}: {int(p['stock'])} unidades disponibles"
                    for p in menu
                ]
                parts.append("Disponibilidad de servicios de la carpintería:\n" + "\n".join(lines))
            else:
                parts.append("No hay servicios activos en el catálogo en este momento.")

        if is_capabilities_question(message):
            parts.append(get_capabilities_text(role))

        if is_hours_question(message):
            parts.append(
                "Horario de la carpintería: lunes a sábado de 8:00 a 18:00 hrs. "
                "Las cotizaciones se pueden solicitar en cualquier momento a través del chat."
            )

        if is_identity_question(message):
            parts.append(
                "Tu nombre es Carpintería IA. Eres el asistente virtual amigable de la carpintería."
            )

        if is_greeting(message):
            parts.append("El usuario te saluda. Responde cálido y pregunta en qué puedes ayudar.")

        if is_farewell(message):
            parts.append("El usuario se despide. Responde breve y amable.")

        if role == UserRole.ADMIN.value:
            parts.append("El usuario autenticado es administrador.")
        else:
            parts.append("El usuario autenticado es cliente.")

        if not parts:
            parts.append(
                "Responde de forma natural al mensaje. No insistas en que haga una cotización "
                "a menos que él lo pida."
            )

        return "\n\n".join(parts)

    async def handle(
        self,
        message: str,
        role: str,
        history: list[dict[str, str]],
    ) -> str:
        if is_menu_request(message):
            return self._render_menu()

        if is_stock_inquiry(message):
            return self._render_stock()

        context = self._build_context(message, role)
        try:
            return await self.ollama.generate_conversational_response(
                message, context, history
            )
        except Exception:
            return self._fallback(message, role)

    def _render_menu(self) -> str:
        menu = obtener_menu().get("productos") or []
        if not menu:
            return "Por ahora no tenemos servicios activos en el catálogo. ¿Te ayudo con algo más?"
        lines = [f"- {p['nombre']}: ${p['precio']:,.2f}" for p in menu]
        return "Este es nuestro catálogo de servicios disponibles:\n" + "\n".join(lines)

    def _render_stock(self) -> str:
        menu = obtener_menu().get("productos") or []
        if not menu:
            return "Por ahora no tenemos servicios activos en el catálogo. ¿Te ayudo con algo más?"
        lines = [f"- {p['nombre']}: {int(p['stock'])} disponibles (${p['precio']:,.2f} c/u)" for p in menu]
        return "🪵 Esta es la disponibilidad de nuestros servicios:\n" + "\n".join(lines) + "\n\n¿Te gustaría solicitar una cotización?"

    def _fallback(self, message: str, role: str) -> str:
        text = message.strip().lower()

        if is_menu_request(message):
            return self._render_menu()

        if is_greeting(message):
            return "¡Hola! Soy Carpintería IA, el asistente de la carpintería. ¿En qué te puedo ayudar hoy? 🪵"

        if is_farewell(message):
            return "¡Hasta pronto! Que tengas un excelente día. 🪵"

        if is_identity_question(message):
            return (
                "Soy Carpintería IA, el asistente virtual de la carpintería. "
                "Estoy aquí para platicar contigo, resolver dudas y ayudarte con cotizaciones cuando lo necesites."
            )

        if is_capabilities_question(message):
            caps = get_capabilities_text(role)
            return f"Claro, te cuento. {caps} ¿Qué te gustaría hacer?"

        if is_hours_question(message):
            return (
                "Abrimos de lunes a sábado, de 8:00 a 18:00 hrs. "
                "Las cotizaciones se pueden solicitar en cualquier momento a través del chat."
            )

        if is_stock_inquiry(message):
            return self._render_stock()

        if is_product_inquiry(message):
            menu = obtener_menu().get("productos") or []
            if not menu:
                return "Por ahora no tenemos servicios activos en el catálogo. ¿Te ayudo con algo más?"
            preview = ", ".join(p["nombre"] for p in menu[:6])
            extra = f" y {len(menu) - 6} más" if len(menu) > 6 else ""
            return (
                f"Tenemos en el catálogo: {preview}{extra}. "
                f"¿Te gustaría conocer precios o solicitar una cotización?"
            )

        if any(term in text for term in [
            "mundial", "programación", "historia", "videojuegos", "deportes", "política",
            "clima", "noticias", "medicina", "tecnología", "tareas",
        ]):
            return (
                "Soy el asistente virtual de Carpintería IA y únicamente puedo ayudarte con información relacionada con nuestros servicios de carpintería, productos de madera y cotizaciones. "
                "Si gustas, puedo mostrarte nuestros muebles, puertas, closets o servicios de remodelación disponibles."
            )

        if "gracias" in text:
            return "¡De nada! Para lo que necesites. 🪵"

        return (
            "Entiendo. Si quieres, puedo contarte del catálogo de servicios, horarios o ayudarte con una cotización. "
            "¿Qué te gustaría saber?"
        )
