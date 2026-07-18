import json
import logging
from typing import Any

import httpx

from services.intent_service import (
    ChatMode,
    ACTIVE_ORDER_STATES,
    is_greeting,
    is_farewell,
    is_identity_question,
    is_capabilities_question,
    is_clear_order_intent,
    is_product_inquiry,
    is_admin_query,
    is_menu_request,
    is_stock_inquiry,
    is_hours_question,
)

logger = logging.getLogger(__name__)

ROUTER_SYSTEM_PROMPT = """Eres un ruteador de mensajes para un sistema de carpintería. Analiza el mensaje del usuario y determina qué agente debe procesarlo.

Agentes disponibles:
- RAG: Para preguntas sobre productos, servicios, tipos de madera, precios, cuidado, instalación, procesos de fabricación, preguntas frecuentes. Cualquier consulta informativa.
- TRANSACTIONAL: Para solicitar cotizaciones, pedidos, cancelaciones, gestionar inventario, operaciones de administrador. Cualquier acción que modifique datos.
- GENERAL: Para saludos, despedidas, preguntas sobre identidad, conversación general, solicitudes fuera del dominio.

Responde SOLO con JSON: {"agent": "RAG|TRANSACTIONAL|GENERAL", "reason": "breve razón"}"""


class RouterAgent:
    """Multi-agent router that analyzes user messages and routes to the appropriate specialist agent."""

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model: str = "llama3:latest",
    ) -> None:
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = model

    async def route(
        self,
        message: str,
        role: str,
        conversation_state: str,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        """Determine which specialist agent should handle the message.

        Returns:
            {"agent": str, "reason": str, "confidence": float}
        """
        try:
            return await self._llm_route(message, role, conversation_state)
        except Exception:
            logger.exception("LLM routing failed, falling back to rule-based routing")
            return self._rule_based_route(message, role, conversation_state)

    async def _llm_route(
        self,
        message: str,
        role: str,
        conversation_state: str,
    ) -> dict[str, Any]:
        """LLM-based routing using Ollama's chat API."""
        context_parts = [f"Mensaje del usuario: {message}"]
        if role:
            context_parts.append(f"Rol del usuario: {role}")
        if conversation_state:
            context_parts.append(f"Estado de la conversación: {conversation_state}")
        user_prompt = "\n".join(context_parts)

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": ROUTER_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "format": "json",
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.ollama_base_url}/api/chat",
                json=payload,
            )
            response.raise_for_status()

        data = response.json()
        content = data.get("message", {}).get("content", "").strip()
        return self._parse_llm_response(content, message, role, conversation_state)

    def _parse_llm_response(
        self,
        content: str,
        message: str,
        role: str,
        conversation_state: str,
    ) -> dict[str, Any]:
        """Parse the LLM JSON response into a routing decision."""
        try:
            parsed = json.loads(content)
            agent = parsed.get("agent", "GENERAL")
            reason = parsed.get("reason", "")

            if agent not in ("RAG", "TRANSACTIONAL", "GENERAL"):
                logger.warning("LLM returned unknown agent '%s', defaulting to GENERAL", agent)
                agent = "GENERAL"
                reason = f"Agente desconocido: {parsed.get('agent')}"

            return {
                "agent": agent,
                "reason": reason,
                "confidence": 0.85,
            }
        except (json.JSONDecodeError, KeyError, TypeError):
            logger.warning("Failed to parse LLM routing response: %s", content)
            return self._rule_based_route(message, role, conversation_state)

    def _rule_based_route(
        self,
        message: str,
        role: str,
        conversation_state: str,
    ) -> dict[str, Any]:
        """Fallback rule-based routing when LLM is unavailable."""
        from models.user import UserRole

        msg = message.strip()

        if conversation_state in ACTIVE_ORDER_STATES:
            return {
                "agent": "TRANSACTIONAL",
                "reason": f"Conversación en estado activo de pedido: {conversation_state}",
                "confidence": 0.95,
            }

        if is_clear_order_intent(msg):
            return {
                "agent": "TRANSACTIONAL",
                "reason": "Intención clara de pedir o cotizar",
                "confidence": 0.9,
            }

        if is_admin_query(msg) and role == UserRole.ADMIN.value:
            return {
                "agent": "TRANSACTIONAL",
                "reason": "Consulta de administrador",
                "confidence": 0.9,
            }

        if is_greeting(msg):
            return {
                "agent": "GENERAL",
                "reason": "Saludo detectado",
                "confidence": 0.95,
            }

        if is_farewell(msg):
            return {
                "agent": "GENERAL",
                "reason": "Despedida detectada",
                "confidence": 0.95,
            }

        if is_identity_question(msg):
            return {
                "agent": "GENERAL",
                "reason": "Pregunta de identidad del asistente",
                "confidence": 0.95,
            }

        if is_capabilities_question(msg):
            return {
                "agent": "GENERAL",
                "reason": "Pregunta sobre capacidades del asistente",
                "confidence": 0.9,
            }

        if is_stock_inquiry(msg):
            return {
                "agent": "RAG",
                "reason": "Consulta de inventario/stock",
                "confidence": 0.8,
            }

        if is_menu_request(msg):
            return {
                "agent": "RAG",
                "reason": "Solicitud de menú/catálogo",
                "confidence": 0.85,
            }

        if is_product_inquiry(msg):
            return {
                "agent": "RAG",
                "reason": "Consulta informativa sobre productos o servicios",
                "confidence": 0.8,
            }

        if is_hours_question(msg):
            return {
                "agent": "RAG",
                "reason": "Consulta de horarios",
                "confidence": 0.8,
            }

        return {
            "agent": "GENERAL",
            "reason": "Sin coincidencia con patrones específicos, ruteando a general",
            "confidence": 0.5,
        }

    def detect_mode(
        self,
        message: str,
        role: str,
        conversation_state: str,
    ) -> ChatMode:
        """Compatibility method that returns ChatMode enum matching the old intent_service.detect_mode."""
        result = self._rule_based_route(message, role, conversation_state)

        agent_to_mode = {
            "RAG": ChatMode.GENERAL_CHAT,
            "TRANSACTIONAL": ChatMode.ORDER_FLOW,
            "GENERAL": ChatMode.GENERAL_CHAT,
        }
        mode = agent_to_mode.get(result["agent"], ChatMode.GENERAL_CHAT)

        if result["agent"] == "TRANSACTIONAL":
            from models.user import UserRole
            if role == UserRole.ADMIN.value and is_admin_query(message):
                mode = ChatMode.ADMIN_ASSISTANT

        return mode
