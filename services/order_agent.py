import re
from datetime import datetime

from models.conversation_state import ConversationState, OrderStatus
from services.conversation_state_service import (
    get_conversation_state,
    reset_order_state,
    save_conversation_state,
)
from services.intent_service import is_clear_order_intent, is_product_inquiry
from services.order_extraction import (
    extract_generic_category,
    extract_order_from_text,
)
from services.ollama_service import OllamaService
from tools.carpentry_tools import obtener_menu
from tools.order_tools import (
    calculate_order_total,
    cancel_order,
    confirm_order,
    get_or_create_pending_order,
    merge_cart_items,
    save_customer_location,
    update_order,
)

CONFIRM_PATTERN = re.compile(
    r"^(s[ií]|confirmo|correcto|exacto|dale|ok|okay|est[aá]\s+bien|"
    r"perfecto|de\s+acuerdo|va|listo|claro|afirmativo)\b",
    re.IGNORECASE,
)

DENY_PATTERN = re.compile(
    r"^(no|nop|cancelar|cancela|me\s+equivoqu[eé]|cambiar|modificar)\b",
    re.IGNORECASE,
)

PICKUP_PATTERN = re.compile(
    r"\b(recoger|recojo|paso\s+por|pasar[eé]\s+por|take\s*away|para\s+llevar|"
    r"en\s+taller|en\s+tienda|tienda|taller|ah[ií]\s+mismo)\b",
    re.IGNORECASE,
)

DELIVERY_PATTERN = re.compile(
    r"\b(domicilio|delivery|a\s+casa|env[ií]o|enviar|mandar|entregar|"
    r"instalar|instalaci[oó]n|a\s+domicilio)\b",
    re.IGNORECASE,
)

NAME_PATTERN = re.compile(r"^[a-záéíóúñA-ZÁÉÍÓÚÑ\s]{2,40}$")

ORDER_START_HOUR = 8   # 8 AM
ORDER_END_HOUR = 18    # 6 PM


class OrderAgent:
    def __init__(self, ollama: OllamaService | None = None):
        self.ollama = ollama or OllamaService()

    def is_order_intent(self, message: str) -> bool:
        return is_clear_order_intent(message)

    @staticmethod
    def _is_within_order_hours() -> bool:
        """Verifica si la hora actual está dentro del horario de cotizaciones (8 AM - 6 PM)."""
        now = datetime.now()
        return ORDER_START_HOUR <= now.hour < ORDER_END_HOUR

    async def handle(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict[str, str]],
    ) -> tuple[str, list[str], str] | None:
        state_data = get_conversation_state(conversation_id)
        state = ConversationState(state_data["state"])

        if state == ConversationState.IDLE:
            if not self.is_order_intent(user_message):
                return None
            if not self._is_within_order_hours():
                return (
                    "⏰ Lo siento, las cotizaciones solo se pueden solicitar de 8:00 AM a 6:00 PM. "
                    "Nuestro horario de atención es de lunes a sábado de 08:00 a 18:00 hrs. "
                    "¿Puedo ayudarte con algo más, como ver el catálogo de servicios o la disponibilidad?",
                    [],
                    ConversationState.IDLE.value,
                )
            save_conversation_state(
                conversation_id, state=ConversationState.COLLECTING_ORDER.value
            )
            return await self._collecting_order(
                conversation_id, user_message, history, get_conversation_state(conversation_id)
            )

        handlers = {
            ConversationState.COLLECTING_ORDER: self._collecting_order,
            ConversationState.ASKING_CUSTOMER_NAME: self._asking_customer_name,
            ConversationState.ASKING_DELIVERY_TYPE: self._asking_delivery_type,
            ConversationState.ASKING_ADDRESS: self._asking_address,
            ConversationState.ASKING_LOCATION: self._asking_location,
            ConversationState.CONFIRMING_ORDER: self._confirming_order,
            ConversationState.ORDER_COMPLETED: self._order_completed,
        }

        handler = handlers.get(state)
        if not handler:
            return None

        return await handler(conversation_id, user_message, history, state_data)

    async def handle_location(
        self, conversation_id: str, latitude: float, longitude: float
    ) -> tuple[str, list[str], str]:
        """Procesa ubicación GPS del navegador y avanza a confirmación."""
        save_customer_location(conversation_id, latitude, longitude)
        state_data = get_conversation_state(conversation_id)
        cart = state_data.get("cart") or []

        if state_data["state"] != ConversationState.ASKING_LOCATION.value:
            return (
                "Ubicación recibida y guardada.",
                ["save_customer_location"],
                state_data["state"],
            )

        save_conversation_state(
            conversation_id, state=ConversationState.CONFIRMING_ORDER.value
        )

        order_id = state_data.get("order_id")
        if order_id:
            update_order(order_id, latitude=latitude, longitude=longitude)

        response, tools, state = await self._show_summary(
            conversation_id,
            cart,
            [],
            state_data.get("delivery_type") or "domicilio",
            extra_instruction="Confirma que recibiste la ubicación GPS del cliente.",
        )
        tools = ["save_customer_location", *tools]
        return response, tools, state

    async def _collecting_order(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str]:
        cart: list[dict] = list(state_data.get("cart") or [])

        if self._is_confirmation(user_message) and cart:
            save_conversation_state(
                conversation_id,
                state=ConversationState.ASKING_CUSTOMER_NAME.value,
                cart=cart,
            )
            return await self._ask_customer_name(conversation_id, cart, history)

        if self._is_denial(user_message) and cart:
            cart = []
            save_conversation_state(conversation_id, cart=cart)
            response = await self.ollama.generate_employee_response(
                instruction="El cliente quiere corregir. Pregúntale amablemente qué servicio de carpintería desea cotizar.",
                context="Cotización vacía.",
                history=history,
            )
            return response, [], ConversationState.COLLECTING_ORDER.value

        if cart and not self._is_confirmation(user_message) and not self._is_denial(user_message):
            if not self._is_order_related(user_message):
                response = (
                    "Ya hay una cotización en curso. "
                    "Por favor mantengamos la conversación en la cotización actual. "
                    "Indica un servicio del siguiente catálogo, confirma la cotización o cancela.\n\n"
                    + self._render_menu_text()
                )
                return response, [], ConversationState.COLLECTING_ORDER.value

        extraction = await extract_order_from_text(user_message, self.ollama)
        extracted = extraction.get("productos_detectados") or []
        added, errors = merge_cart_items(cart, extracted)

        # If backend requires type selection for multi-type products, prompt user
        for err in errors:
            if isinstance(err, str) and err.startswith("ASK_FLAVORS:"):
                try:
                    _, categoria, cantidad = err.split(":")
                except Exception:
                    categoria = "este servicio"
                    cantidad = "varios"
                prompt = (
                    "Perfecto.\n\n¿Qué tipo de servicio deseas?\n\nPuedes elegir un tipo para cada uno.\n\n"
                    f"Por ejemplo para {cantidad} {categoria}s:\n2 Closets\n1 Librero\n\n"
                    "Indica los tipos y cantidades cuando quieras."
                )
                return prompt, ["extract_order_from_text"], ConversationState.COLLECTING_ORDER.value

        if errors and not cart:
            validation_messages = [err for err in errors if isinstance(err, str) and not err.startswith("ASK_FLAVORS:")]
            if validation_messages:
                response = "\n".join(validation_messages)
                if any("servicio no forma parte" in msg.lower() or "producto no forma parte" in msg.lower() for msg in validation_messages):
                    response += "\n\n" + self._render_menu_text()
                return response, ["extract_order_from_text"], ConversationState.COLLECTING_ORDER.value

        if cart and added:
            save_conversation_state(
                conversation_id,
                state=ConversationState.ASKING_CUSTOMER_NAME.value,
                cart=cart,
            )
            tools = ["extract_order_from_text"]
            return await self._ask_customer_name(
                conversation_id, cart, history, errors=errors, tools=tools
            )

        if not cart:
            if extraction.get("has_order_intent"):
                if errors:
                    return (
                        "No puedo añadir esos servicios a la cotización. Revisa el catálogo disponible:\n"
                        + self._render_menu_text(),
                        ["extract_order_from_text"],
                        ConversationState.COLLECTING_ORDER.value,
                    )

                category = extract_generic_category(user_message)
                if category:
                    menu_items = obtener_menu().get("productos") or []
                    matches = [
                        p["nombre"] for p in menu_items if category in p["nombre"].lower()
                    ]
                    if matches:
                        options = "\n".join(f"• {name}" for name in matches)
                        return (
                            f"Tenemos varias opciones de {category}s disponibles:\n{options}\n\n"
                            "¿Cuál prefieres?",
                            ["extract_order_from_text"],
                            ConversationState.COLLECTING_ORDER.value,
                        )

                return (
                    "No encuentro ese servicio en el catálogo. Revisa lo que tenemos disponible:\n"
                    + self._render_menu_text(),
                    ["extract_order_from_text"],
                    ConversationState.COLLECTING_ORDER.value,
                )

            if is_product_inquiry(user_message):
                return (
                    "No encontré ese servicio en el catálogo activo. Esto es lo que tenemos disponible:\n"
                    + self._render_menu_text(),
                    ["extract_order_from_text"],
                    ConversationState.COLLECTING_ORDER.value,
                )

            response = await self.ollama.generate_employee_response(
                instruction=(
                    "Saluda al cliente y pregúntale qué servicio de carpintería le gustaría cotizar. "
                    "Menciona muebles a medida, puertas, closets, cocinas integrales y restauración."
                ),
                context="Sin servicios detectados aún.",
                history=history,
            )
            save_conversation_state(conversation_id, cart=cart)
            return response, ["extract_order_from_text"], ConversationState.COLLECTING_ORDER.value

        save_conversation_state(conversation_id, cart=cart)

        if cart and not extracted and self._is_order_related(user_message):
            category = extract_generic_category(user_message)
            if category:
                menu_items = obtener_menu().get("productos") or []
                matches = [
                    p["nombre"] for p in menu_items if category in p["nombre"].lower()
                ]
                if matches:
                    options = "\n".join(f"• {name}" for name in matches)
                    return (
                        f"Tenemos varias opciones de {category}s disponibles:\n{options}\n\n"
                        "¿Cuál prefieres?",
                        [],
                        ConversationState.COLLECTING_ORDER.value,
                    )

            return (
                "No encontré los servicios solicitados en el catálogo actual. "
                "Por favor elige uno de los servicios disponibles a continuación, confirma la cotización actual o cancélala.\n\n"
                + self._render_menu_text(),
                [],
                ConversationState.COLLECTING_ORDER.value,
            )

        context = self._cart_context(cart)
        if errors:
            context += f"\nNo disponibles: {', '.join(errors)}"

        response = await self.ollama.generate_employee_response(
            instruction=(
                "Muestra la cotización detectada con cantidades. "
                "Pregunta si desea agregar algo más o si está correcta."
            ),
            context=context,
            history=history,
        )
        return response, ["extract_order_from_text"], ConversationState.COLLECTING_ORDER.value

    async def _ask_customer_name(
        self,
        conversation_id: str,
        cart: list[dict],
        history: list[dict],
        errors: list[str] | None = None,
        tools: list[str] | None = None,
    ) -> tuple[str, list[str], str]:
        context = self._cart_context(cart)
        if errors:
            context += f"\nServicios no encontrados: {', '.join(errors)}"

        response = await self.ollama.generate_employee_response(
            instruction=(
                "Confirma la cotización detectada listando servicios y cantidades. "
                "Pregunta ÚNICAMENTE a nombre de quién será la cotización."
            ),
            context=context,
            history=history,
        )
        return response, tools or [], ConversationState.ASKING_CUSTOMER_NAME.value

    def _render_menu_text(self) -> str:
        menu_items = obtener_menu().get("productos") or []
        if not menu_items:
            return "Por ahora no tenemos servicios activos en el catálogo."
        lines = [f"- {p['nombre']}: ${p['precio']:,.2f}" for p in menu_items]
        return "Catálogo de servicios disponible:\n" + "\n".join(lines)

    def _is_order_related(self, message: str) -> bool:
        return bool(
            is_product_inquiry(message)
            or is_clear_order_intent(message)
            or PICKUP_PATTERN.search(message)
            or DELIVERY_PATTERN.search(message)
        )

    async def _asking_customer_name(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str]:
        cart = state_data.get("cart") or []
        name = user_message.strip()

        if PICKUP_PATTERN.search(user_message) or DELIVERY_PATTERN.search(user_message):
            response = await self.ollama.generate_employee_response(
                instruction=(
                    "El cliente respondió con un tipo de entrega en lugar de su nombre. "
                    "Pide de nuevo el nombre de la persona a quien va la cotización."
                ),
                context=self._cart_context(cart),
                history=history,
            )
            return response, [], ConversationState.ASKING_CUSTOMER_NAME.value

        if not NAME_PATTERN.match(name) or len(name.split()) > 4:
            response = await self.ollama.generate_employee_response(
                instruction="Pide amablemente el nombre de la persona a quien va la cotización.",
                context=self._cart_context(cart),
                history=history,
            )
            return response, [], ConversationState.ASKING_CUSTOMER_NAME.value

        save_conversation_state(
            conversation_id,
            state=ConversationState.ASKING_DELIVERY_TYPE.value,
            customer_name=name,
        )

        response = await self.ollama.generate_employee_response(
            instruction=(
                f"Agradece a {name} por su nombre. "
                "Pregunta ÚNICAMENTE si será para recoger en taller o entrega/instalación a domicilio."
            ),
            context=f"{self._cart_context(cart)}\nCliente: {name}",
            history=history,
        )
        return response, [], ConversationState.ASKING_DELIVERY_TYPE.value

    async def _asking_delivery_type(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str]:
        cart = state_data.get("cart") or []
        customer_name = state_data.get("customer_name") or "Cliente"

        if PICKUP_PATTERN.search(user_message):
            save_conversation_state(
                conversation_id,
                state=ConversationState.CONFIRMING_ORDER.value,
                delivery_type="recoger",
            )
            order = get_or_create_pending_order(
                conversation_id=conversation_id,
                items=cart,
                delivery_type="recoger",
                customer_name=customer_name,
            )
            if not order.get("exito"):
                return await self._order_error_response(order, cart, history)
            save_conversation_state(conversation_id, order_id=order["order_id"])
            return await self._show_summary(conversation_id, cart, history, "recoger")

        if DELIVERY_PATTERN.search(user_message):
            save_conversation_state(
                conversation_id,
                state=ConversationState.ASKING_ADDRESS.value,
                delivery_type="domicilio",
            )
            order = get_or_create_pending_order(
                conversation_id=conversation_id,
                items=cart,
                delivery_type="domicilio",
                customer_name=customer_name,
            )
            if not order.get("exito"):
                return await self._order_error_response(order, cart, history)
            save_conversation_state(conversation_id, order_id=order["order_id"])

            response = await self.ollama.generate_employee_response(
                instruction="El cliente eligió entrega/instalación a domicilio. Pide ÚNICAMENTE la dirección de entrega.",
                context=f"Cliente: {customer_name}\n{self._cart_context(cart)}",
                history=history,
            )
            return response, ["create_order"], ConversationState.ASKING_ADDRESS.value

        response = await self.ollama.generate_employee_response(
            instruction="Pregunta de nuevo si prefiere recoger en taller o entrega/instalación a domicilio.",
            context=self._cart_context(cart),
            history=history,
        )
        return response, [], ConversationState.ASKING_DELIVERY_TYPE.value

    async def _asking_address(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str]:
        cart = state_data.get("cart") or []
        address = user_message.strip()

        if len(address) < 5:
            response = await self.ollama.generate_employee_response(
                instruction="Pide la dirección completa: calle, número y colonia.",
                context=self._cart_context(cart),
                history=history,
            )
            return response, [], ConversationState.ASKING_ADDRESS.value

        save_conversation_state(
            conversation_id,
            state=ConversationState.ASKING_LOCATION.value,
            address=address,
        )

        order_id = state_data.get("order_id")
        if order_id:
            update_order(order_id, address=address)

        response = await self.ollama.generate_employee_response(
            instruction=(
                "Agradece por la dirección. Pide ÚNICAMENTE que comparta su ubicación "
                "usando el botón de ubicación 📍 en el chat."
            ),
            context=f"{self._cart_context(cart)}\nDirección: {address}",
            history=history,
        )
        return response, ["update_order"], ConversationState.ASKING_LOCATION.value

    async def _asking_location(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str]:
        cart = state_data.get("cart") or []

        response = await self.ollama.generate_employee_response(
            instruction=(
                "Recuerda amablemente que debe usar el botón 📍 Compartir ubicación "
                "en la parte inferior del chat. No pidas otra información."
            ),
            context=self._cart_context(cart),
            history=history,
        )
        return response, [], ConversationState.ASKING_LOCATION.value

    async def _show_summary(
        self,
        conversation_id: str,
        cart: list[dict],
        history: list[dict],
        delivery_type: str,
        extra_instruction: str = "",
    ) -> tuple[str, list[str], str]:
        state_data = get_conversation_state(conversation_id)
        totals = calculate_order_total(cart, delivery_type)
        summary = self._build_summary(cart, delivery_type, totals, state_data)

        instruction = (
            "Presenta el resumen completo de la cotización: cliente, servicios, dirección si aplica, "
            "subtotal, envío si aplica y total. Pregunta ÚNICAMENTE si confirma la cotización."
        )
        if extra_instruction:
            instruction = f"{extra_instruction} {instruction}"

        response = await self.ollama.generate_employee_response(
            instruction=instruction,
            context=summary,
            history=history,
        )
        return response, ["calculate_order_total"], ConversationState.CONFIRMING_ORDER.value

    async def _confirming_order(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str]:
        cart = state_data.get("cart") or []
        delivery_type = state_data.get("delivery_type") or "recoger"
        order_id = state_data.get("order_id")

        if self._is_denial(user_message):
            if order_id:
                cancel_order(order_id)
            reset_order_state(conversation_id)
            response = await self.ollama.generate_employee_response(
                instruction="La cotización fue cancelada. Ofrece ayuda para una nueva cotización.",
                context="Cotización cancelada.",
                history=history,
            )
            return response, ["cancel_order"], ConversationState.IDLE.value

        if not self._is_confirmation(user_message):
            totals = calculate_order_total(cart, delivery_type)
            summary = self._build_summary(cart, delivery_type, totals, state_data)
            response = await self.ollama.generate_employee_response(
                instruction="Pide confirmación: responda sí para confirmar o no para cancelar.",
                context=summary,
                history=history,
            )
            return response, [], ConversationState.CONFIRMING_ORDER.value

        if not order_id:
            order = get_or_create_pending_order(
                conversation_id=conversation_id,
                items=cart,
                delivery_type=delivery_type,
                customer_name=state_data.get("customer_name"),
                address=state_data.get("delivery_address"),
            )
            order_id = order["order_id"]
            if state_data.get("latitude") and state_data.get("longitude"):
                update_order(
                    order_id,
                    latitude=state_data["latitude"],
                    longitude=state_data["longitude"],
                )
            save_conversation_state(conversation_id, order_id=order_id)

        result = confirm_order(order_id)
        tools_used = ["confirm_order", "registrar_venta", "create_order"]

        if not result.get("exito"):
            response = await self.ollama.generate_employee_response(
                instruction=f"Informa el problema: {result.get('mensaje')}. Ofrece alternativas.",
                context=self._cart_context(cart),
                history=history,
            )
            return response, tools_used, ConversationState.CONFIRMING_ORDER.value

        save_conversation_state(
            conversation_id, state=ConversationState.ORDER_COMPLETED.value
        )
        totals = calculate_order_total(cart, delivery_type)
        summary = self._build_summary(cart, delivery_type, totals, state_data)

        response = await self.ollama.generate_employee_response(
            instruction=(
                "Confirma que la cotización fue registrada exitosamente. "
                "Indica tiempo estimado (3-5 días para recoger, 5-10 días para entrega/instalación a domicilio). Despídete amablemente."
            ),
            context=f"{summary}\nNúmero de cotización: {order_id}",
            history=history,
        )
        return response, tools_used, ConversationState.ORDER_COMPLETED.value

    async def _order_completed(
        self,
        conversation_id: str,
        user_message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str] | None:
        if self.is_order_intent(user_message):
            reset_order_state(conversation_id)
            save_conversation_state(
                conversation_id, state=ConversationState.COLLECTING_ORDER.value
            )
            return await self._collecting_order(
                conversation_id,
                user_message,
                history,
                get_conversation_state(conversation_id),
            )
        reset_order_state(conversation_id)
        return None

    def _build_summary(
        self, cart: list[dict], delivery_type: str, totals: dict, state_data: dict
    ) -> str:
        lines = ["Resumen de la cotización:"]
        if state_data.get("customer_name"):
            lines.append(f"Cliente: {state_data['customer_name']}")
        lines.append("Servicios:")
        for item in cart:
            sub = item.get("subtotal", item["precio"] * item["cantidad"])
            lines.append(f"- {item['cantidad']}x {item['producto']} = ${sub:,.2f}")
        lines.append(f"Subtotal: ${totals['subtotal']:,.2f}")
        if delivery_type == "domicilio":
            lines.append(f"Envío/Instalación: ${totals['delivery_fee']:,.2f}")
            if state_data.get("delivery_address"):
                lines.append(f"Dirección: {state_data['delivery_address']}")
            if state_data.get("latitude") and state_data.get("longitude"):
                lines.append(
                    f"Ubicación GPS: {state_data['latitude']}, {state_data['longitude']}"
                )
        else:
            lines.append("Entrega: recoger en taller")
        lines.append(f"TOTAL: ${totals['total']:,.2f}")
        return "\n".join(lines)

    def _cart_context(self, cart: list[dict]) -> str:
        if not cart:
            return "Cotización vacía."
        lines = ["Cotización detectada:"]
        for item in cart:
            sub = item.get("subtotal", item["precio"] * item["cantidad"])
            lines.append(f"- {item['cantidad']}x {item['producto']} (${sub:,.2f})")
        return "\n".join(lines)

    def _is_confirmation(self, message: str) -> bool:
        text = message.strip()
        if DENY_PATTERN.search(text):
            return False
        return bool(CONFIRM_PATTERN.search(text))

    def _is_denial(self, message: str) -> bool:
        return bool(DENY_PATTERN.search(message.strip()))

    async def _order_error_response(
        self, order: dict, cart: list[dict], history: list[dict]
    ) -> tuple[str, list[str], str]:
        response = await self.ollama.generate_employee_response(
            instruction=f"Informa el error: {order.get('mensaje', 'No se pudo crear la cotización')}.",
            context=self._cart_context(cart),
            history=history,
        )
        return response, [], ConversationState.ASKING_DELIVERY_TYPE.value
