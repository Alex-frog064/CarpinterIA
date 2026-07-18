import json
import uuid

from database.db import get_db
from models.conversation_state import ConversationState
from models.user import UserRole
from services.activity_service import log_activity
from services.audit_log import tools_logger
from services.conversation_state_service import get_conversation_state, _ensure_state_row
from services.general_chat_service import GeneralChatService
from services.ollama_service import OllamaService
from services.router_agent import RouterAgent
from services.rag_agent import RAGAgent
from services.transactional_agent import TransactionalAgent


class ChatService:
    def __init__(self):
        self.ollama = OllamaService()
        self.router = RouterAgent()
        self.rag_agent = RAGAgent()
        self.transactional_agent = TransactionalAgent()
        self.general_chat = GeneralChatService(self.ollama)

    def _ensure_conversation(self, conversation_id: str | None, user_id: int) -> str:
        cid = conversation_id or str(uuid.uuid4())
        with get_db() as conn:
            exists = conn.execute(
                "SELECT id, user_id FROM conversations WHERE id = ?", (cid,)
            ).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO conversations (id, user_id) VALUES (?, ?)",
                    (cid, user_id),
                )
                conn.execute(
                    """
                    INSERT INTO conversation_state (conversation_id, current_state, cart_json, collected_data_json)
                    VALUES (?, ?, ?, ?)
                    """,
                    (cid, ConversationState.IDLE.value, "[]", "{}"),
                )
            else:
                _ensure_state_row(cid)
                if exists["user_id"] and exists["user_id"] != user_id:
                    raise PermissionError("Conversación no pertenece al usuario")
                if not exists["user_id"]:
                    conn.execute(
                        "UPDATE conversations SET user_id = ? WHERE id = ?",
                        (user_id, cid),
                    )
        return cid

    def _verify_conversation_access(self, conversation_id: str, user_id: int, role: str):
        with get_db() as conn:
            row = conn.execute(
                "SELECT user_id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
        if not row:
            return
        if role != UserRole.ADMIN.value and row["user_id"] not in (None, user_id):
            raise PermissionError("Sin acceso a esta conversación")

    def _get_history(self, conversation_id: str) -> list[dict]:
        with get_db() as conn:
            rows = conn.execute(
                """
                SELECT role, content FROM messages
                WHERE conversation_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in rows]

    def _save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        tools_used: list[str] | None = None,
    ):
        tools_json = json.dumps(tools_used) if tools_used else None
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO messages (conversation_id, role, content, tools_used)
                VALUES (?, ?, ?, ?)
                """,
                (conversation_id, role, content, tools_json),
            )

    async def process_message(
        self,
        user_message: str,
        user_id: int,
        role: str,
        conversation_id: str | None = None,
    ) -> tuple[str, str, list[str], str, list[dict]]:
        if conversation_id:
            self._verify_conversation_access(conversation_id, user_id, role)

        cid = self._ensure_conversation(conversation_id, user_id)
        history = self._get_history(cid)
        state_data = get_conversation_state(cid)
        current_state = state_data["state"]

        self._save_message(cid, "user", user_message)
        log_activity(user_id, "SEND_MESSAGE", {"conversation_id": cid, "preview": user_message[:80]})

        # Use multi-agent router to determine intent
        routing = await self.router.route(
            message=user_message,
            role=role,
            conversation_state=current_state,
            history=history,
        )
        agent_type = routing["agent"]
        tools_logger.info(
            "Agente ruteado: %s (razón: %s) | conv=%s",
            agent_type, routing.get("reason", ""), cid[:8],
        )

        if agent_type == "TRANSACTIONAL":
            result = await self.transactional_agent.handle(
                conversation_id=cid,
                message=user_message,
                user_id=user_id,
                role=role,
                history=history,
                state_data=state_data,
            )
            if result is not None:
                assistant_response, tools_used, state = result
                if tools_used:
                    tools_logger.info("Herramientas ejecutadas: %s | conv=%s", tools_used, cid[:8])
                self._save_message(cid, "assistant", assistant_response, tools_used)
                cart = get_conversation_state(cid).get("cart") or []
                return cid, assistant_response, tools_used, state, cart

        if agent_type == "RAG":
            assistant_response = await self.rag_agent.handle(
                message=user_message,
                history=history,
            )
            self._save_message(cid, "assistant", assistant_response)
            state_data = get_conversation_state(cid)
            return cid, assistant_response, [], state_data["state"], state_data.get("cart") or []

        # GENERAL agent (default)
        assistant_response = await self.general_chat.handle(user_message, role, history)
        self._save_message(cid, "assistant", assistant_response)
        return cid, assistant_response, [], ConversationState.IDLE.value, state_data.get("cart") or []

    async def process_location(
        self,
        conversation_id: str,
        latitude: float,
        longitude: float,
        user_id: int,
        role: str,
    ) -> tuple[str, str, list[str], str, list[dict]]:
        self._verify_conversation_access(conversation_id, user_id, role)
        cid = self._ensure_conversation(conversation_id, user_id)
        response, tools_used, state = await self.transactional_agent.handle_location(
            cid, latitude, longitude
        )
        if tools_used:
            tools_logger.info("Herramientas ejecutadas: %s | conv=%s", tools_used, cid[:8])
        self._save_message(cid, "assistant", response, tools_used)
        cart = get_conversation_state(cid).get("cart") or []
        return cid, response, tools_used, state, cart

    def get_conversation_messages(self, conversation_id: str, user_id: int, role: str) -> list[dict]:
        self._verify_conversation_access(conversation_id, user_id, role)
        with get_db() as conn:
            conv = conn.execute(
                "SELECT id FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if not conv:
                return []

            rows = conn.execute(
                """
                SELECT id, conversation_id, role, content, tools_used, created_at
                FROM messages WHERE conversation_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (conversation_id,),
            ).fetchall()

        result = []
        for r in rows:
            msg = dict(r)
            if msg.get("tools_used"):
                try:
                    msg["tools_used"] = json.loads(msg["tools_used"])
                except json.JSONDecodeError:
                    msg["tools_used"] = None
            else:
                msg["tools_used"] = None
            result.append(msg)
        return result

    def get_conversation_state(self, conversation_id: str, user_id: int, role: str) -> dict:
        self._verify_conversation_access(conversation_id, user_id, role)
        return get_conversation_state(conversation_id)

    def list_conversations(self, user_id: int, role: str) -> list[dict]:
        with get_db() as conn:
            if role == UserRole.ADMIN.value:
                rows = conn.execute("""
                    SELECT c.id, c.created_at, c.user_id,
                           COALESCE(cs.current_state, 'IDLE') AS state,
                           COUNT(m.id) AS message_count,
                           u.username, u.full_name
                    FROM conversations c
                    LEFT JOIN conversation_state cs ON cs.conversation_id = c.id
                    LEFT JOIN messages m ON m.conversation_id = c.id
                    LEFT JOIN users u ON u.id = c.user_id
                    GROUP BY c.id
                    ORDER BY c.created_at DESC
                """).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT c.id, c.created_at, c.user_id,
                           COALESCE(cs.current_state, 'IDLE') AS state,
                           COUNT(m.id) AS message_count
                    FROM conversations c
                    LEFT JOIN conversation_state cs ON cs.conversation_id = c.id
                    LEFT JOIN messages m ON m.conversation_id = c.id
                    WHERE c.user_id = ?
                    GROUP BY c.id
                    ORDER BY c.created_at DESC
                    """,
                    (user_id,),
                ).fetchall()
        return [dict(r) for r in rows]

    def delete_conversation(self, conversation_id: str, user_id: int, role: str) -> dict:
        self._verify_conversation_access(conversation_id, user_id, role)
        with get_db() as conn:
            conn.execute("DELETE FROM messages WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM orders WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversation_state WHERE conversation_id = ?", (conversation_id,))
            conn.execute("DELETE FROM conversations WHERE id = ?", (conversation_id,))
        log_activity(user_id, "DELETE_CONVERSATION", {"conversation_id": conversation_id})
        return {"exito": True, "mensaje": "Conversación eliminada."}
