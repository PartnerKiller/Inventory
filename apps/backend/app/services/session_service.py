import uuid
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, update
from fastapi import HTTPException

from app.core.config import settings
from app.models.base import get_utc_now
from app.models.auth_security import UserSessionRecord

class SessionService:
    @staticmethod
    def hash_token(raw_token: str) -> str:
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @staticmethod
    async def create_session(
        db: AsyncSession,
        tenant_id: str,
        user_id: str,
        user_type: str = "INTERNAL",
        device_name: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[UserSessionRecord, str]:
        family_id = str(uuid.uuid4())
        raw_refresh_token = f"rt_{uuid.uuid4().hex}_{secrets_token_hex(16)}"
        token_hash = SessionService.hash_token(raw_refresh_token)

        expires_at = get_utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

        session = UserSessionRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            user_type=user_type,
            user_id=user_id,
            family_id=family_id,
            refresh_token_hash=token_hash,
            device_name=device_name,
            ip_address=ip_address,
            user_agent=user_agent,
            status="ACTIVE",
            expires_at=expires_at,
            last_active_at=get_utc_now()
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return session, raw_refresh_token

    @staticmethod
    async def rotate_session(
        db: AsyncSession,
        raw_refresh_token: str,
        device_name: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> Tuple[UserSessionRecord, str]:
        token_hash = SessionService.hash_token(raw_refresh_token)

        session = (await db.execute(
            select(UserSessionRecord).where(UserSessionRecord.refresh_token_hash == token_hash).with_for_update()
        )).scalar_one_or_none()

        if not session:
            raise HTTPException(status_code=401, detail="Invalid refresh token")

        # 1. Reuse Detection: If an already-used token is presented, revoke the ENTIRE token family!
        if session.status == "USED":
            await db.execute(
                update(UserSessionRecord)
                .where(UserSessionRecord.family_id == session.family_id)
                .values(status="REVOKED")
            )
            await db.commit()
            raise HTTPException(
                status_code=401,
                detail="Security Alert: Refresh token reuse detected! Entire session family has been revoked."
            )

        if session.status == "REVOKED":
            raise HTTPException(status_code=401, detail="Session has been revoked")

        exp = session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=timezone.utc)
        if exp < get_utc_now():
            session.status = "REVOKED"
            await db.commit()
            raise HTTPException(status_code=401, detail="Refresh token expired")

        # 2. Normal rotation: Mark old token USED, create new token in same family
        session.status = "USED"

        new_raw_refresh_token = f"rt_{uuid.uuid4().hex}_{secrets_token_hex(16)}"
        new_token_hash = SessionService.hash_token(new_raw_refresh_token)

        new_session = UserSessionRecord(
            id=str(uuid.uuid4()),
            tenant_id=session.tenant_id,
            user_type=session.user_type,
            user_id=session.user_id,
            family_id=session.family_id,
            refresh_token_hash=new_token_hash,
            device_name=device_name or session.device_name,
            ip_address=ip_address or session.ip_address,
            user_agent=user_agent or session.user_agent,
            status="ACTIVE",
            expires_at=get_utc_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
            last_active_at=get_utc_now()
        )
        db.add(new_session)
        await db.commit()
        await db.refresh(new_session)
        return new_session, new_raw_refresh_token

    @staticmethod
    async def revoke_session(db: AsyncSession, session_id: str):
        session = (await db.execute(select(UserSessionRecord).where(UserSessionRecord.id == session_id))).scalar_one_or_none()
        if session:
            session.status = "REVOKED"
            await db.commit()

    @staticmethod
    async def revoke_all_user_sessions(db: AsyncSession, tenant_id: str, user_id: str):
        """Global session invalidation across all devices for a user."""
        await db.execute(
            update(UserSessionRecord)
            .where(
                UserSessionRecord.tenant_id == tenant_id,
                UserSessionRecord.user_id == user_id,
                UserSessionRecord.status != "REVOKED"
            )
            .values(status="REVOKED")
        )
        await db.commit()

def secrets_token_hex(nbytes: int) -> str:
    import secrets
    return secrets.token_hex(nbytes)
