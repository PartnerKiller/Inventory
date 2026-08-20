import uuid
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update
from fastapi import HTTPException, status
from app.models.auth import User, Role, Permission, RefreshTokenSession, user_roles_table
from app.core.security import verify_password, get_password_hash, create_access_token, create_refresh_token, decode_token
from app.schemas.auth import LoginRequest, TokenResponse, UserProfileResponse
from app.models.base import get_utc_now
from app.core.config import settings

class AuthService:
    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    @staticmethod
    async def authenticate_user(
        db: AsyncSession,
        login_data: LoginRequest,
        device_info: Optional[str] = "Web Browser"
    ) -> TokenResponse:
        stmt = select(User).where(User.email == login_data.email, User.is_deleted == False)
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()

        if not user or not verify_password(login_data.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is deactivated"
            )

        user.last_login_at = get_utc_now()

        role_names = [r.name for r in user.roles]
        permissions_set = set()
        for r in user.roles:
            for p in r.permissions:
                permissions_set.add(p.code)
        
        if user.is_superuser:
            permissions_set.add("*")

        wh_scopes = [w.id for w in user.warehouses]
        permissions_list = list(permissions_set)
        
        access_token = create_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            roles=role_names,
            permissions=permissions_list,
            warehouse_scopes=wh_scopes
        )
        refresh_token = create_refresh_token(subject=user.id, tenant_id=user.tenant_id)

        # Store persistent refresh token session in database
        token_hash = AuthService._hash_token(refresh_token)
        session_obj = RefreshTokenSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=token_hash,
            device_info=device_info,
            expires_at=get_utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            is_revoked=False,
            created_at=get_utc_now()
        )
        db.add(session_obj)
        await db.commit()

        user_profile = UserProfileResponse(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            roles=role_names,
            permissions=permissions_list,
            warehouse_scopes=wh_scopes,
            last_login_at=user.last_login_at,
            created_at=user.created_at
        )

        return TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user_profile
        )

    @staticmethod
    async def rotate_refresh_token(
        db: AsyncSession,
        old_refresh_token: str,
        device_info: Optional[str] = "Web Browser"
    ) -> TokenResponse:
        payload = decode_token(old_refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

        old_hash = AuthService._hash_token(old_refresh_token)
        stmt = select(RefreshTokenSession).where(
            RefreshTokenSession.token_hash == old_hash,
            RefreshTokenSession.is_revoked == False
        ).with_for_update()
        res = await db.execute(stmt)
        session_obj = res.scalar_one_or_none()

        now = get_utc_now()
        if not session_obj:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token revoked or invalid")

        session_exp = session_obj.expires_at
        if session_exp.tzinfo is None:
            session_exp = session_exp.replace(tzinfo=timezone.utc)

        if session_exp < now:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token session expired")

        # Invalidate old refresh session immediately (Token Rotation)
        session_obj.is_revoked = True

        # Fetch active user
        user_stmt = select(User).where(User.id == session_obj.user_id, User.is_deleted == False)
        user_res = await db.execute(user_stmt)
        user = user_res.scalar_one_or_none()

        if not user or not user.is_active:
            await db.commit()
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive or deleted")

        role_names = [r.name for r in user.roles]
        permissions_set = set()
        for r in user.roles:
            for p in r.permissions:
                permissions_set.add(p.code)
        if user.is_superuser:
            permissions_set.add("*")

        wh_scopes = [w.id for w in user.warehouses]

        # Issue new token pair
        new_access_token = create_access_token(
            subject=user.id,
            tenant_id=user.tenant_id,
            roles=role_names,
            permissions=list(permissions_set),
            warehouse_scopes=wh_scopes
        )
        new_refresh_token = create_refresh_token(subject=user.id, tenant_id=user.tenant_id)
        new_hash = AuthService._hash_token(new_refresh_token)

        new_session = RefreshTokenSession(
            id=str(uuid.uuid4()),
            user_id=user.id,
            tenant_id=user.tenant_id,
            token_hash=new_hash,
            device_info=device_info,
            expires_at=get_utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            is_revoked=False,
            created_at=get_utc_now()
        )
        db.add(new_session)
        await db.commit()

        user_profile = UserProfileResponse(
            id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            full_name=user.full_name,
            is_active=user.is_active,
            is_superuser=user.is_superuser,
            roles=role_names,
            permissions=list(permissions_set),
            warehouse_scopes=wh_scopes,
            last_login_at=user.last_login_at,
            created_at=user.created_at
        )

        return TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user_profile
        )

    @staticmethod
    async def revoke_refresh_token(db: AsyncSession, refresh_token: str) -> None:
        token_hash = AuthService._hash_token(refresh_token)
        stmt = (
            update(RefreshTokenSession)
            .where(RefreshTokenSession.token_hash == token_hash)
            .values(is_revoked=True)
        )
        await db.execute(stmt)
        await db.commit()
