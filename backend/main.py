import json
import os
import subprocess
import sys

from contextlib import asynccontextmanager
from pathlib import Path

from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from backend.auth_deps import get_current_user, require_admin
from database.db import init_db
from models.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationOut,
    ConversationStateOut,
    LocationRequest,
    LoginRequest,
    LoginResponse,
    MessageOut,
    ProductUpdateRequest,
    RegisterRequest,
    UserOut,
    WoodTypeOut,
    WoodTypeCreate,
    WoodTypeUpdate,
    ProductSizeOut,
    ProductSizeCreate,
    ProductSizeUpdate,
)
from services.activity_service import list_activity, log_activity
from services.auth_service import (
    authenticate,
    create_session,
    delete_session,
    list_users,
    register_user,
)
from services.chat_service import ChatService
from services.order_display import build_order_card
from tools.carpentry_tools import (
    actualizar_producto,
    consultar_inventario,
    obtener_stats_dashboard,
    obtener_tipos_madera,
    crear_tipo_madera,
    actualizar_tipo_madera,
    eliminar_tipo_madera,
    obtener_tamanos_producto,
    crear_tamano_producto,
    actualizar_tamano_producto,
    eliminar_tamano_producto,
    obtener_catalogo_completo,
)
from tools.order_tools import cancel_order, get_user_orders, list_all_orders

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

chat_service = ChatService()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Agente IA Carpintería",
    description="Agente conversacional con autenticación, roles y cotizaciones para carpintería",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def serve_landing():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/login")
async def serve_login():
    return FileResponse(FRONTEND_DIR / "login.html")


@app.get("/app")
async def serve_app():
    return FileResponse(FRONTEND_DIR / "app.html")


app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Auth ──

@app.post("/auth/login", response_model=LoginResponse)
async def login(body: LoginRequest):
    user = authenticate(body.username, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Usuario o contraseña incorrectos")
    token = create_session(user["id"])
    log_activity(user["id"], "LOGIN", {"username": user["username"]})
    return LoginResponse(
        token=token,
        user=UserOut(
            id=user["id"],
            username=user["username"],
            full_name=user["full_name"],
            role=user["role"],
        ),
    )


@app.post("/auth/register", response_model=LoginResponse)
async def register(body: RegisterRequest):
    if not body.username.strip() or not body.password or not body.full_name.strip():
        raise HTTPException(status_code=400, detail="Todos los campos son obligatorios")
    if len(body.password) < 6:
        raise HTTPException(status_code=400, detail="La contraseña debe tener al menos 6 caracteres")
    user = register_user(body.username, body.password, body.full_name)
    if not user:
        raise HTTPException(status_code=400, detail="El nombre de usuario ya existe")
    token = create_session(user["id"])
    log_activity(user["id"], "LOGIN", {"username": user["username"], "registered": True})
    return LoginResponse(
        token=token,
        user=UserOut(
            id=user["id"],
            username=user["username"],
            full_name=user["full_name"],
            role=user["role"],
        ),
    )


@app.post("/auth/logout")
async def logout(
    user: dict = Depends(get_current_user),
    authorization: Annotated[str | None, Header()] = None,
):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ").strip()
        delete_session(token)
    log_activity(user["id"], "LOGOUT", {"username": user["username"]})
    return {"ok": True}


@app.get("/auth/me", response_model=UserOut)
async def me(user: dict = Depends(get_current_user)):
    return UserOut(
        id=user["id"],
        username=user["username"],
        full_name=user["full_name"],
        role=user["role"],
    )


# ── Chat (autenticado) ──

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, user: dict = Depends(get_current_user)):
    try:
        conversation_id, response, tools_used, state, cart = await chat_service.process_message(
            request.message, user["id"], user["role"], request.conversation_id
        )
        order_card = None
        if "confirm_order" in tools_used:
            orders = get_user_orders(user["id"], limit=1)
            if orders:
                order_card = build_order_card(orders[0])
        return ChatResponse(
            conversation_id=conversation_id,
            response=response,
            tools_used=tools_used,
            conversation_state=state,
            cart=cart,
            order_card=order_card,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error procesando mensaje: {e}")


@app.post("/location", response_model=ChatResponse)
async def save_location(request: LocationRequest, user: dict = Depends(get_current_user)):
    try:
        conversation_id, response, tools_used, state, cart = await chat_service.process_location(
            request.conversation_id,
            request.latitude,
            request.longitude,
            user["id"],
            user["role"],
        )
        order_card = None
        if "confirm_order" in tools_used:
            orders = get_user_orders(user["id"], limit=1)
            if orders:
                order_card = build_order_card(orders[0])
        return ChatResponse(
            conversation_id=conversation_id,
            response=response,
            tools_used=tools_used,
            conversation_state=state,
            cart=cart,
            order_card=order_card,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error guardando ubicación: {e}")


@app.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(user: dict = Depends(get_current_user)):
    return chat_service.list_conversations(user["id"], user["role"])


@app.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
async def get_messages(conversation_id: str, user: dict = Depends(get_current_user)):
    try:
        return chat_service.get_conversation_messages(conversation_id, user["id"], user["role"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@app.get("/conversations/{conversation_id}/state", response_model=ConversationStateOut)
async def get_state(conversation_id: str, user: dict = Depends(get_current_user)):
    try:
        state = chat_service.get_conversation_state(conversation_id, user["id"], user["role"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return ConversationStateOut(
        conversation_id=conversation_id,
        state=state["state"],
        cart=state.get("cart") or [],
        collected=state.get("collected") or {},
    )

@app.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, user: dict = Depends(get_current_user)):
    try:
        result = chat_service.delete_conversation(conversation_id, user["id"], user["role"])
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not result.get("exito"):
        raise HTTPException(status_code=400, detail=result.get("mensaje", "No se pudo eliminar la conversación"))
    return result

# ── Pedidos/Cotizaciones cliente ──

@app.get("/my/orders")
async def my_orders(user: dict = Depends(get_current_user)):
    return get_user_orders(user["id"])


@app.post("/my/orders/{order_id}/cancel")
async def cancel_my_order(order_id: int, user: dict = Depends(get_current_user)):
    result = cancel_order(order_id, user_id=user["id"])
    if not result.get("exito"):
        raise HTTPException(status_code=400, detail=result.get("mensaje"))
    log_activity(user["id"], "CANCEL_ORDER", {"order_id": order_id})
    return result


# ── Admin ──

@app.get("/admin/users")
async def admin_users(admin: dict = Depends(require_admin)):
    return list_users()


@app.get("/admin/orders")
async def admin_orders(admin: dict = Depends(require_admin)):
    return list_all_orders()


@app.get("/admin/conversations")
async def admin_conversations(admin: dict = Depends(require_admin)):
    return chat_service.list_conversations(admin["id"], admin["role"])


@app.get("/admin/activity")
async def admin_activity(admin: dict = Depends(require_admin)):
    return list_activity()


@app.get("/admin/dashboard")
async def admin_dashboard(admin: dict = Depends(require_admin)):
    return obtener_stats_dashboard()


@app.get("/admin/products")
async def admin_products(admin: dict = Depends(require_admin)):
    return consultar_inventario()


@app.patch("/admin/products/{product_id}")
async def admin_update_product(
    product_id: int,
    body: ProductUpdateRequest,
    admin: dict = Depends(require_admin),
):
    result = actualizar_producto(
        product_id,
        stock=body.stock,
        price=body.price,
        menu_visible=body.menu_visible,
    )
    if not result.get("exito"):
        raise HTTPException(status_code=400, detail=result.get("mensaje"))
    return result


@app.get("/inventory")
async def get_inventory(user: dict = Depends(require_admin)):
    return consultar_inventario()


# ── Catálogo endpoints ────────────────────────────────────────────────────────

@app.get("/catalog/wood-types", response_model=list[WoodTypeOut])
async def catalog_wood_types():
    """Obtiene los tipos de madera activos para el catálogo."""
    return obtener_tipos_madera(active_only=True)


@app.get("/catalog/products/{product_id}/sizes", response_model=list[ProductSizeOut])
async def catalog_product_sizes(product_id: int):
    """Obtiene los tamaños configurados para un producto."""
    return obtener_tamanos_producto(product_id)


@app.get("/catalog/full")
async def catalog_full():
    """Catálogo completo con precios base, rangos, maderas y tamaños disponibles."""
    return obtener_catalogo_completo()


# ── Admin Wood Types endpoints ────────────────────────────────────────────────

@app.get("/admin/wood-types", response_model=list[WoodTypeOut])
async def admin_get_wood_types(admin: dict = Depends(require_admin)):
    """Obtiene todos los tipos de madera (activos e inactivos)."""
    return obtener_tipos_madera(active_only=False)


@app.post("/admin/wood-types", response_model=dict)
async def admin_create_wood_type(body: WoodTypeCreate, admin: dict = Depends(require_admin)):
    """Crea un nuevo tipo de madera."""
    res = crear_tipo_madera(body.name, body.price_modifier, body.description)
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje"))
    return res


@app.patch("/admin/wood-types/{wood_type_id}", response_model=dict)
async def admin_update_wood_type(
    wood_type_id: int,
    body: WoodTypeUpdate,
    admin: dict = Depends(require_admin),
):
    """Actualiza modificador, descripción o estado activo de un tipo de madera."""
    res = actualizar_tipo_madera(
        wood_type_id,
        price_modifier=body.price_modifier,
        description=body.description,
        active=body.active,
    )
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje"))
    return res


@app.delete("/admin/wood-types/{wood_type_id}", response_model=dict)
async def admin_delete_wood_type(wood_type_id: int, admin: dict = Depends(require_admin)):
    """Desactiva un tipo de madera."""
    res = eliminar_tipo_madera(wood_type_id)
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje"))
    return res


# ── Admin Product Sizes endpoints ─────────────────────────────────────────────

@app.get("/admin/products/{product_id}/sizes", response_model=list[ProductSizeOut])
async def admin_get_product_sizes(product_id: int, admin: dict = Depends(require_admin)):
    """Obtiene los tamaños de un producto para administración."""
    return obtener_tamanos_producto(product_id)


@app.post("/admin/products/{product_id}/sizes", response_model=dict)
async def admin_create_product_size(
    product_id: int,
    body: ProductSizeCreate,
    admin: dict = Depends(require_admin),
):
    """Añade un tamaño con su modificador a un producto."""
    res = crear_tamano_producto(product_id, body.size_label, body.price_modifier, body.dimensions)
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje"))
    return res


@app.patch("/admin/products/sizes/{size_id}", response_model=dict)
async def admin_update_product_size(
    size_id: int,
    body: ProductSizeUpdate,
    admin: dict = Depends(require_admin),
):
    """Actualiza dimensiones o modificador de un tamaño de producto."""
    res = actualizar_tamano_producto(size_id, price_modifier=body.price_modifier, dimensions=body.dimensions)
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje"))
    return res


@app.delete("/admin/products/sizes/{size_id}", response_model=dict)
async def admin_delete_product_size(size_id: int, admin: dict = Depends(require_admin)):
    """Elimina un tamaño de un producto."""
    res = eliminar_tamano_producto(size_id)
    if not res.get("exito"):
        raise HTTPException(status_code=400, detail=res.get("mensaje"))
    return res


# ── Evaluación ──────────────────────────────────────────────────────────────

REPORT_PATH = Path(os.getenv("REPORT_PATH", str(Path(__file__).resolve().parent.parent / "reporte_evaluacion.pdf")))


@app.post("/admin/evaluate")
async def run_evaluation(admin: dict = Depends(require_admin)):
    """Ejecuta el script de evaluación LLM-as-Judge y genera el PDF."""
    import io
    logs = []
    try:
        proc = subprocess.run(
            [sys.executable, "scripts/evaluar_agente.py"],
            capture_output=True,
            text=True,
            timeout=600,
            cwd=str(Path(__file__).resolve().parent.parent),
        )
        logs = proc.stdout.splitlines()[-30:]
        if proc.returncode != 0:
            logs += proc.stderr.splitlines()[-20:]
    except subprocess.TimeoutExpired:
        return {"exito": False, "mensaje": "La evaluación tardó más de 10 minutos"}
    except Exception as e:
        return {"exito": False, "mensaje": f"Error: {e}"}

    if not REPORT_PATH.exists():
        return {"exito": False, "mensaje": "No se generó el PDF", "logs": logs}

    return {
        "exito": True,
        "mensaje": "Evaluación completada",
        "report_size_kb": round(REPORT_PATH.stat().st_size / 1024, 1),
        "download_url": "/admin/evaluate/report",
        "logs": logs,
    }


@app.get("/admin/evaluate/report")
async def download_evaluation_report(admin: dict = Depends(require_admin)):
    """Descarga el PDF del reporte de evaluación."""
    if not REPORT_PATH.exists():
        raise HTTPException(status_code=404, detail="No hay reporte disponible. Ejecuta /admin/evaluate primero.")
    return FileResponse(
        str(REPORT_PATH),
        media_type="application/pdf",
        filename="reporte_evaluacion.pdf",
    )

