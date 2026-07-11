import json
import os
import re
from typing import Any

import httpx

from tools.carpentry_tools import TOOL_REGISTRY
from tools.tool_definitions import ADMIN_SYSTEM_PROMPT, OLLAMA_ADMIN_TOOLS

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
MODEL = os.getenv("OLLAMA_MODEL", "llama3:latest")
MAX_TOOL_ITERATIONS = 5

CARPINTERIA_IA_SYSTEM_PROMPT = """Eres el asistente virtual oficial de Carpintería IA.

Eres un asistente de la carpintería y tu única función es ayudar con el catálogo de servicios, productos de madera, cotizaciones, horarios y servicios de Carpintería IA.
Responde únicamente en español.
Usa solamente la información proporcionada en el contexto.
No inventes productos, precios, servicios, horarios, materiales, disponibilidad ni ningún dato.
Si no tienes la información en el contexto, indica que no cuentas con ella y redirige al catálogo de servicios disponible.
No respondas preguntas ajenas al negocio.
Si el mensaje no corresponde a Carpintería IA, responde:
"Soy el asistente virtual de Carpintería IA y únicamente puedo ayudarte con información sobre nuestros servicios de carpintería, productos de madera y cotizaciones. Si lo deseas, puedo ayudarte a conocer nuestros muebles, puertas, closets o servicios de remodelación disponibles."
Responde de forma clara, amable, profesional, breve y natural.
No repitas la misma frase.
No menciones estados internos, JSON ni que eres un modelo de lenguaje.
Usa máximo 1 emoji por mensaje cuando sea natural."""

QUOTE_EMPLOYEE_PROMPT = """Eres el asistente virtual oficial de Carpintería IA que atiende cotizaciones y pedidos.

Personalidad:
- Natural, cálido y conversacional.
- Mantén el contexto de la cotización y no cambies de tema.
- Confirma información antes de avanzar.

Reglas estrictas:
- Responde SIEMPRE en español.
- Usa SOLO servicios, precios y datos del catálogo activo del contexto.
- No inventes nada.
- Si no hay información suficiente, di que no cuentas con ella y ofrece conocer el catálogo de servicios disponible.
- No abandones el flujo de cotización. Si el cliente cambia de tema, redirige a la cotización o al catálogo.
- Haz UNA sola pregunta por mensaje.
- Avanza paso a paso: servicios → nombre → tipo entrega → dirección → ubicación → confirmación.
- Sé breve pero amable. Máximo 1 emoji por mensaje.
- No menciones estados internos, JSON, bases de datos ni que eres una IA.
- Cierra la cotización con entusiasmo cuando se confirme.
- no quiero que puedan hacer preguntas de otros temas que no sean cotizaciones
- no pueden ser productos perzonalizados"""

EXTRACT_PRODUCTS_PROMPT = """Extrae los servicios/productos de carpintería y cantidades del mensaje del cliente.
Responde SOLO con JSON válido en este formato:
{{"productos": [{{"nombre": "nombre del servicio", "cantidad": 1}}]}}

Catálogo de servicios disponible:
{menu}

Si no detectas servicios concretos, devuelve {{"productos": []}}.
Si no se indica cantidad, usa 1.
Normaliza nombres al catálogo cuando sea posible (ej: "quiero un closet" -> "Closet")."""


class OllamaService:
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = MODEL):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def chat_with_tools(self, messages: list[dict[str, Any]]) -> tuple[str, list[str]]:
        """Envía mensajes a Ollama con function calling para tareas administrativas."""
        full_messages = [{"role": "system", "content": ADMIN_SYSTEM_PROMPT}, *messages]
        tools_used: list[str] = []

        async with httpx.AsyncClient(timeout=120.0) as client:
            for _ in range(MAX_TOOL_ITERATIONS):
                response = await client.post(
                    f"{self.base_url}/api/chat",
                    json={
                        "model": self.model,
                        "messages": full_messages,
                        "tools": OLLAMA_ADMIN_TOOLS,
                        "stream": False,
                    },
                )
                response.raise_for_status()
                data = response.json()
                assistant_msg = data["message"]

                if not assistant_msg.get("tool_calls"):
                    return assistant_msg.get("content", ""), tools_used

                full_messages.append(assistant_msg)

                for tool_call in assistant_msg["tool_calls"]:
                    fn = tool_call["function"]
                    name = fn["name"]
                    raw_args = fn.get("arguments", {})

                    if isinstance(raw_args, str):
                        try:
                            args = json.loads(raw_args) if raw_args else {}
                        except json.JSONDecodeError:
                            args = {}
                    else:
                        args = raw_args or {}

                    if name not in tools_used:
                        tools_used.append(name)

                    result = self._execute_tool(name, args)
                    full_messages.append(
                        {
                            "role": "tool",
                            "tool_name": name,
                            "content": json.dumps(result, ensure_ascii=False),
                        }
                    )

        return "Lo siento, no pude completar la solicitud después de varios intentos.", tools_used

    async def extract_order_products(
        self, user_message: str, menu_products: list[str]
    ) -> list[dict[str, Any]]:
        """Usa el LLM para extraer servicios y cantidades del mensaje."""
        menu_text = "\n".join(f"- {p}" for p in menu_products)
        system = EXTRACT_PRODUCTS_PROMPT.format(menu=menu_text)

        raw = await self._chat_json(system, user_message)
        productos = raw.get("productos", [])
        if not isinstance(productos, list):
            return []
        return [
            {"nombre": str(p.get("nombre", "")).strip(), "cantidad": float(p.get("cantidad", 1) or 1)}
            for p in productos
            if p.get("nombre")
        ]

    async def generate_conversational_response(
        self,
        user_message: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Respuesta conversacional general (sin flujo de cotización)."""
        system = f"{CARPINTERIA_IA_SYSTEM_PROMPT}\n\nInformación relevante:\n{context}"
        messages = list(history or [])[-8:]
        messages.append({"role": "user", "content": user_message})

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "system", "content": system}, *messages],
                    "stream": False,
                },
            )
            response.raise_for_status()
            return response.json()["message"].get("content", "")

    async def generate_employee_response(
        self,
        instruction: str,
        context: str,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        """Genera una respuesta natural de empleado de carpintería."""
        system = f"{QUOTE_EMPLOYEE_PROMPT}\n\nContexto actual:\n{context}"
        messages = list(history or [])[-6:]
        messages.append({"role": "user", "content": instruction})

        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={"model": self.model, "messages": [{"role": "system", "content": system}, *messages], "stream": False},
            )
            response.raise_for_status()
            return response.json()["message"].get("content", "")

    async def _chat_json(self, system: str, user_content: str) -> dict:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                    "format": "json",
                    "stream": False,
                },
            )
            response.raise_for_status()
            content = response.json()["message"].get("content", "{}")
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                match = re.search(r"\{.*\}", content, re.DOTALL)
                if match:
                    try:
                        return json.loads(match.group())
                    except json.JSONDecodeError:
                        pass
                return {}

    def _execute_tool(self, name: str, args: dict[str, Any]) -> dict:
        func = TOOL_REGISTRY.get(name)
        if not func:
            return {"error": f"Herramienta '{name}' no encontrada."}
        try:
            return func(**args)
        except TypeError as e:
            return {"error": f"Argumentos inválidos para '{name}': {e}"}
        except Exception as e:
            return {"error": f"Error ejecutando '{name}': {e}"}
