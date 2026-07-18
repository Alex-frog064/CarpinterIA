import logging

from models.conversation_state import ConversationState
from models.user import UserRole
from services.cancel_service import CancelService
from services.intent_service import (
    ACTIVE_ORDER_STATES,
    is_admin_query,
    is_clear_order_intent,
)
from services.ollama_service import OllamaService
from services.order_agent import OrderAgent

logger = logging.getLogger(__name__)


class TransactionalAgent:
    """Specialist agent that handles order management, cancellations, and admin operations.

    Wraps the existing OrderAgent, CancelService, and OllamaService (admin tool calling)
    into a unified transactional interface.
    """

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model: str = "llama3:latest",
    ) -> None:
        self.ollama = OllamaService(base_url=ollama_base_url, model=model)
        self.order_agent = OrderAgent(self.ollama)
        self.cancel_service = CancelService(self.ollama)

    async def handle(
        self,
        conversation_id: str,
        message: str,
        user_id: int,
        role: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str] | None:
        """Main dispatcher for all transactional operations.

        Routing priority:
        1. Cancellation intent (customers only)
        2. Active order state (order flow)
        3. Admin queries (admin role only)
        4. New order intent

        Returns:
            (response, tools_used, state) if handled, None if this agent
            should not handle the message.
        """
        current_state = state_data["state"]

        # 1. Cancellation intent (customers only)
        if role == UserRole.CUSTOMER.value:
            cancel_result = await self.cancel_service.handle(
                user_id, conversation_id, message, history
            )
            if cancel_result is not None:
                logger.info(
                    "Routed to cancel flow | conv=%s", conversation_id[:8]
                )
                return cancel_result

        # 2. Active order state → continue order flow
        if current_state in ACTIVE_ORDER_STATES:
            logger.info(
                "Routed to order flow (active state=%s) | conv=%s",
                current_state,
                conversation_id[:8],
            )
            return await self.handle_order(
                conversation_id, message, history, state_data
            )

        # 3. Admin queries (admin role only)
        if role == UserRole.ADMIN.value and is_admin_query(message):
            logger.info(
                "Routed to admin assistant | conv=%s", conversation_id[:8]
            )
            return await self.handle_admin(message, history)

        # 4. New order intent
        if is_clear_order_intent(message):
            logger.info(
                "Routed to order flow (new intent) | conv=%s",
                conversation_id[:8],
            )
            return await self.handle_order(
                conversation_id, message, history, state_data
            )

        # Not a transactional request
        return None

    async def handle_admin(
        self, message: str, history: list[dict]
    ) -> tuple[str, list[str], str]:
        """Handle admin operations using Ollama function calling.

        Returns:
            (response, tools_used, state)
        """
        messages = list(history or []) + [{"role": "user", "content": message}]

        logger.info("Executing admin function calling | msg=%s", message[:80])

        try:
            response, tools_used = await self.ollama.chat_with_tools(messages)
        except Exception:
            logger.exception("Admin function calling failed")
            return (
                "Lo siento, hubo un problema al procesar tu solicitud. "
                "Intenta de nuevo.",
                [],
                ConversationState.IDLE.value,
            )

        if tools_used:
            logger.info("Admin tools executed: %s", tools_used)

        return response, tools_used, ConversationState.IDLE.value

    async def handle_cancel(
        self,
        user_id: int,
        conversation_id: str,
        message: str,
        history: list[dict],
    ) -> tuple[str, list[str], str] | None:
        """Handle the cancellation flow for a customer order.

        Returns:
            (response, tools_used, state) if cancellation was processed,
            None if no cancellation was detected.
        """
        logger.info("Processing cancel request | conv=%s", conversation_id[:8])

        result = await self.cancel_service.handle(
            user_id, conversation_id, message, history
        )

        if result is not None:
            response, tools_used, state = result
            if tools_used:
                logger.info(
                    "Cancel tools executed: %s | conv=%s",
                    tools_used,
                    conversation_id[:8],
                )
            return result

        return None

    async def handle_order(
        self,
        conversation_id: str,
        message: str,
        history: list[dict],
        state_data: dict,
    ) -> tuple[str, list[str], str] | None:
        """Handle the order/cotización flow.

        Returns:
            (response, tools_used, state) if the order agent handled the message,
            None if the order agent declined.
        """
        logger.info("Processing order request | conv=%s", conversation_id[:8])

        result = await self.order_agent.handle(conversation_id, message, history)

        if result is not None:
            response, tools_used, state = result
            if tools_used:
                logger.info(
                    "Order tools executed: %s | conv=%s",
                    tools_used,
                    conversation_id[:8],
                )
            return result

        return None

    async def handle_location(
        self,
        conversation_id: str,
        latitude: float,
        longitude: float,
    ) -> tuple[str, list[str], str]:
        """Process GPS location data from the browser for the order flow.

        Delegates directly to OrderAgent.handle_location().

        Returns:
            (response, tools_used, state)
        """
        logger.info(
            "Processing GPS location | conv=%s | lat=%.6f, lon=%.6f",
            conversation_id[:8],
            latitude,
            longitude,
        )

        response, tools_used, state = await self.order_agent.handle_location(
            conversation_id, latitude, longitude
        )

        if tools_used:
            logger.info(
                "Location tools executed: %s | conv=%s",
                tools_used,
                conversation_id[:8],
            )

        return response, tools_used, state
