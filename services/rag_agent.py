import logging
import os
import httpx
from rag.pipeline import RAGPipeline

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Eres el asistente de información de Carpintería IA. "
    "Responde preguntas sobre productos, servicios, tipos de madera, precios, "
    "cuidado, instalación y procesos de fabricación.\n\n"
    "INSTRUCCIONES:\n"
    "- Usa SOLO la información del contexto proporcionado para responder.\n"
    "- Si la información no está en el contexto, indica que no cuentas con esa información específica.\n"
    "- No inventes datos, precios ni especificaciones.\n"
    "- Responde de forma clara, amable y profesional en español.\n"
    "- Sé conciso pero completo.\n"
    "- Si es relevante, menciona precios aproximados o rangos.\n"
    "- No menciones que eres un modelo de lenguaje ni que estás usando un sistema RAG.\n"
    "- Usa máximo 1 emoji por mensaje cuando sea natural."
)

FALLBACK_INIT_ERROR = (
    "Lo siento, estoy teniendo problemas para inicializar el sistema de información. "
    "Por favor, intenta nuevamente en unos momentos."
)
FALLBACK_NO_CONTEXT = (
    "No encontré información relevante en nuestros documentos sobre tu pregunta. "
    "¿Podrías reformularla o preguntar sobre otro tema?"
)
FALLBACK_LLM_ERROR = (
    "Lo siento, estoy teniendo problemas para generar una respuesta en este momento. "
    "Por favor, intenta nuevamente."
)


class RAGAgent:

    def __init__(
        self,
        ollama_base_url: str = "http://localhost:11434",
        model: str = "llama3:latest",
    ):
        self.ollama_base_url = ollama_base_url.rstrip("/")
        self.model = os.getenv("OLLAMA_MODEL", model)
        self.rag_pipeline: RAGPipeline | None = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return
        try:
            self.rag_pipeline = RAGPipeline(
                ollama_base_url=self.ollama_base_url,
                persist_dir="data/vector_store",
                documents_dir="documents",
            )
            await self.rag_pipeline.initialize()
            self._initialized = True
            logger.info("RAG pipeline initialized successfully")
        except Exception as e:
            logger.error("Failed to initialize RAG pipeline: %s", e)
            self._initialized = False

    def is_initialized(self) -> bool:
        return self._initialized

    def get_stats(self) -> dict:
        if not self._initialized or self.rag_pipeline is None:
            return {"initialized": False}
        try:
            return self.rag_pipeline.get_stats()
        except Exception as e:
            logger.error("Error getting RAG stats: %s", e)
            return {"initialized": True, "error": str(e)}

    async def handle(self, message: str, history: list[dict] | None = None) -> str:
        try:
            if not self._initialized:
                await self.initialize()

            context = await self._retrieve_context(message)

            if not context:
                return FALLBACK_NO_CONTEXT

            return await self._generate_response(message, context, history)
        except Exception as e:
            logger.error("Error in RAGAgent.handle: %s", e)
            return FALLBACK_INIT_ERROR

    async def _retrieve_context(self, question: str) -> str:
        if self.rag_pipeline is None:
            return ""
        try:
            result = await self.rag_pipeline.query(question, top_k=3)
            return result.get("context", "") or ""
        except Exception as e:
            logger.error("Error retrieving context: %s", e)
            return ""

    async def _generate_response(
        self,
        question: str,
        context: str,
        history: list[dict] | None = None,
    ) -> str:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "system",
                "content": f"Contexto relevante:\n\n{context}",
            },
        ]

        if history:
            for entry in history[-10:]:
                messages.append(
                    {"role": entry.get("role", "user"), "content": entry.get("content", "")}
                )

        messages.append({"role": "user", "content": question})

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{self.ollama_base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                return data["message"]["content"]
        except httpx.ConnectError:
            logger.error("Cannot connect to Ollama at %s", self.ollama_base_url)
            return FALLBACK_LLM_ERROR
        except httpx.TimeoutException:
            logger.error("Ollama request timed out")
            return FALLBACK_LLM_ERROR
        except httpx.HTTPStatusError as e:
            logger.error("Ollama HTTP error: %s", e.response.status_code)
            return FALLBACK_LLM_ERROR
        except Exception as e:
            logger.error("Unexpected error calling Ollama: %s", e)
            return FALLBACK_LLM_ERROR
