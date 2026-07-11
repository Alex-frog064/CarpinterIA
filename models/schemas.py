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
