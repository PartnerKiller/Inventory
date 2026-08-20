from typing import List, Optional, Callable
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.database import get_db
from app.core.security import decode_token
from app.models.auth import User

security = HTTPBearer()

async def get_current_user_claims(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> dict:
    token = credentials.credentials
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials or token expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return payload

async def get_current_active_user(
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db)
) -> User:
    user_id = claims.get("sub")
    stmt = select(User).where(User.id == user_id, User.is_deleted == False)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found or inactive"
        )
    return user

def require_permission(required_permission: str) -> Callable:
    async def permission_checker(claims: dict = Depends(get_current_user_claims)) -> dict:
        permissions: List[str] = claims.get("permissions", [])
        if "*" in permissions or required_permission in permissions:
            return claims
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Missing required permission '{required_permission}'"
        )
    return permission_checker

def check_warehouse_scope(claims: dict, target_warehouse_id: Optional[str]) -> None:
    """
    Enforces warehouse-level authorization.
    Superusers or users without explicit warehouse restrictions pass.
    Users with designated warehouse_scopes receive 403 if target_warehouse_id is not permitted.
    """
    if not target_warehouse_id:
        return
    permissions: List[str] = claims.get("permissions", [])
    if "*" in permissions:
        return
    scopes: List[str] = claims.get("warehouse_scopes", [])
    if not scopes:
        return # Global access
    if target_warehouse_id not in scopes:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Forbidden: Warehouse '{target_warehouse_id}' is outside your authorized warehouse scope."
        )
