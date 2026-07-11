from fastapi import Depends, HTTPException, Header
from typing import Annotated

from models.user import UserRole
from services.auth_service import get_user_by_token


async def get_current_user(authorization: Annotated[str | None, Header()] = None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="No autenticado")
    token = authorization.removeprefix("Bearer ").strip()
    user = get_user_by_token(token)
    if not user:
        raise HTTPException(status_code=401, detail="Sesión inválida o expirada")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Acceso solo para administradores")
    return user


async def require_customer(user: dict = Depends(get_current_user)) -> dict:
    if user["role"] != UserRole.CUSTOMER.value:
        raise HTTPException(status_code=403, detail="Acceso solo para clientes")
    return user
