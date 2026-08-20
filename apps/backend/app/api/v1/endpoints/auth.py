from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status, Header, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from pydantic import BaseModel

from app.core.database import get_db
from app.core.rate_limiter import limiter
from app.schemas.auth import LoginRequest, TokenResponse, UserProfileResponse, UserSessionResponse
from app.services.auth_service import AuthService
from app.core.permissions import get_current_user_claims, get_current_active_user
from app.models.auth import User, RefreshTokenSession

router = APIRouter()

class RefreshRequest(BaseModel):
    refresh_token: str

@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    login_data: LoginRequest,
    user_agent: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Authenticate with email and password to receive access & refresh tokens."""
    return await AuthService.authenticate_user(db, login_data, device_info=user_agent or "Web Client")

@router.post("/refresh", response_model=TokenResponse)
async def refresh_access_token(
    refresh_req: RefreshRequest,
    user_agent: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db)
):
    """Rotate and refresh access token session."""
    return await AuthService.rotate_refresh_token(db, refresh_req.refresh_token, device_info=user_agent or "Web Client")

@router.post("/logout")
async def logout(
    refresh_req: RefreshRequest,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db)
):
    """Revoke active refresh token session."""
    await AuthService.revoke_refresh_token(db, refresh_req.refresh_token)
    return {"message": "Session successfully revoked"}

@router.get("/me", response_model=UserProfileResponse)
async def get_current_user_profile(
    current_user: User = Depends(get_current_active_user),
    claims: dict = Depends(get_current_user_claims)
):
    """Get the currently logged in user's profile and resolved permissions."""
    role_names = [r.name for r in current_user.roles]
    role_ids = [r.id for r in current_user.roles]
    return UserProfileResponse(
        id=current_user.id,
        tenant_id=current_user.tenant_id,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_superuser=current_user.is_superuser,
        roles=role_names,
        role_ids=role_ids,
        permissions=claims.get("permissions", []),
        warehouse_scopes=claims.get("warehouse_scopes", []),
        last_login_at=current_user.last_login_at,
        created_at=current_user.created_at
    )

@router.get("/sessions", response_model=List[UserSessionResponse])
async def list_active_sessions(
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db)
):
    """List active refresh-token sessions for the current authenticated user."""
    user_id = claims["sub"]
    stmt = (
        select(RefreshTokenSession)
        .where(
            RefreshTokenSession.user_id == user_id,
            RefreshTokenSession.is_revoked == False
        )
        .order_by(RefreshTokenSession.created_at.desc())
    )
    res = await db.execute(stmt)
    sessions = res.scalars().all()

    return [
        UserSessionResponse(
            id=s.id,
            user_id=s.user_id,
            device_info=s.device_info,
            created_at=s.created_at,
            expires_at=s.expires_at,
            is_current=False
        )
        for s in sessions
    ]

@router.delete("/sessions/{session_id}")
async def revoke_session(
    session_id: str,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db)
):
    """Revoke a specific active refresh-token session."""
    user_id = claims["sub"]
    stmt = (
        update(RefreshTokenSession)
        .where(
            RefreshTokenSession.id == session_id,
            RefreshTokenSession.user_id == user_id
        )
        .values(is_revoked=True)
    )
    await db.execute(stmt)
    await db.commit()
    return {"message": "Session successfully revoked"}

@router.post("/sessions/revoke-others")
async def revoke_other_sessions(
    refresh_req: RefreshRequest,
    claims: dict = Depends(get_current_user_claims),
    db: AsyncSession = Depends(get_db)
):
    """Revoke all active refresh-token sessions for the current user except the provided current session."""
    user_id = claims["sub"]
    current_token_hash = AuthService._hash_token(refresh_req.refresh_token)

    stmt = (
        update(RefreshTokenSession)
        .where(
            RefreshTokenSession.user_id == user_id,
            RefreshTokenSession.token_hash != current_token_hash,
            RefreshTokenSession.is_revoked == False
        )
        .values(is_revoked=True)
    )
    await db.execute(stmt)
    await db.commit()
    return {"message": "All other active sessions revoked"}
