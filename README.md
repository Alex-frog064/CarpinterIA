# Agente IA Cafetería

Backend FastAPI + SQLite + Ollama con function calling real y memoria persistente por `conversation_id`.

## Requisitos

- Python 3.11+
- [Ollama](https://ollama.com/) en ejecución con el modelo `llama3.1`:

```bash
ollama pull llama3.1
ollama serve
```

## Instalación

```bash
cd "tarea joel"
pip install uvicorn fastapi
pip install -r requirements.txt
py -m uvicorn backend.main:app --reload --port 8000
```

## Ejecutar

Desde la raíz del proyecto:

```bash
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

Documentación interactiva: http://localhost:8000/docs

## Uso del chat

```bash
# Nueva conversación
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "¿Qué productos tenemos en inventario?"}'

# Continuar conversación (usar el conversation_id devuelto)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Registra una venta de 2 Croissant", "conversation_id": "UUID-AQUI"}'
```

## Herramientas disponibles (Function Calling)

| Función | Descripción |
|---------|-------------|
| `consultar_inventario` | Inventario completo |
| `registrar_venta` | Registrar venta y descontar stock |
| `registrar_gasto` | Registrar gasto operativo |
| `obtener_producto_mas_vendido` | Producto top histórico |
| `obtener_ganancia_dia` | Ingresos, gastos y ganancia del día |
| `productos_bajo_stock` | Productos con stock bajo |
| `recomendar_compra` | Sugerencias de compra |

## Estructura

```
backend/     → FastAPI app
database/    → SQLite y conexión
models/      → Schemas Pydantic
services/    → Ollama + lógica de chat
tools/       → Funciones de negocio y definiciones para Ollama
```
