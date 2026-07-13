from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: Optional[str] = None


class LocationRequest(BaseModel):
    conversation_id: str
    latitude: float
    longitude: float


class CartItem(BaseModel):
    producto: str
    cantidad: float
    precio: float
    subtotal: float


class CartItemDetailed(BaseModel):
    """Item de carrito enriquecido con tipo de madera y tamaño."""
    producto: str
    product_id: Optional[int] = None
    cantidad: float
    precio_base: float
    madera: Optional[str] = None
    tamano: Optional[str] = None
    dimensiones: Optional[str] = None
    modificador_madera: float = 1.0
    modificador_tamano: float = 1.0
    precio: float          # precio_base × mod_madera × mod_tamano
    subtotal: float        # precio × cantidad


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    tools_used: list[str] = []
    conversation_state: str = "IDLE"
    cart: list[dict] = []
    order_card: Optional[dict] = None


class ProductUpdateRequest(BaseModel):
    stock: Optional[float] = None
    price: Optional[float] = None
    menu_visible: Optional[bool] = None


class MessageOut(BaseModel):
    id: int
    conversation_id: str
    role: str
    content: str
    tools_used: Optional[list[str]] = None
    created_at: datetime


class ProductOut(BaseModel):
    id: int
    name: str
    stock: float
    price: float
    min_stock: float


class LoginRequest(BaseModel):
    username: str
    password: str


class RegisterRequest(BaseModel):
    username: str
    password: str
    full_name: str


class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    role: str


class LoginResponse(BaseModel):
    token: str
    user: UserOut


class ConversationOut(BaseModel):
    id: str
    created_at: datetime
    message_count: int
    state: str = "IDLE"
    user_id: Optional[int] = None
    username: Optional[str] = None
    full_name: Optional[str] = None


class ConversationStateOut(BaseModel):
    conversation_id: str
    state: str
    cart: list[dict] = []
    collected: dict = {}


# ── Tipos de Madera ──────────────────────────────────────────────────────────

class WoodTypeOut(BaseModel):
    id: int
    name: str
    price_modifier: float
    description: Optional[str] = None
    active: bool


class WoodTypeCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    price_modifier: float = Field(..., ge=0.1, le=10.0)
    description: Optional[str] = None


class WoodTypeUpdate(BaseModel):
    price_modifier: Optional[float] = Field(None, ge=0.1, le=10.0)
    description: Optional[str] = None
    active: Optional[bool] = None


# ── Tamaños de Producto ──────────────────────────────────────────────────────

class ProductSizeOut(BaseModel):
    id: int
    product_id: int
    size_label: str
    dimensions: Optional[str] = None
    price_modifier: float


class ProductSizeCreate(BaseModel):
    size_label: str = Field(..., min_length=1, max_length=50)
    dimensions: Optional[str] = None
    price_modifier: float = Field(..., ge=0.1, le=20.0)


class ProductSizeUpdate(BaseModel):
    dimensions: Optional[str] = None
    price_modifier: Optional[float] = Field(None, ge=0.1, le=20.0)


# ── Catálogo con precios ─────────────────────────────────────────────────────

class ProductCatalogOut(BaseModel):
    """Producto del catálogo con rango de precios calculados."""
    id: int
    name: str
    stock: float
    precio_base: float
    precio_minimo: float    # precio_base × menor(wood_mod) × menor(size_mod)
    precio_maximo: float    # precio_base × mayor(wood_mod) × mayor(size_mod)
    categoria: Optional[str] = None
    sizes: list[ProductSizeOut] = []
    wood_types: list[WoodTypeOut] = []

