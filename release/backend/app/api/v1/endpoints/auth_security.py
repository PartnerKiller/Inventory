from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.core.database import get_db
from app.core.permissions import get_current_user_claims, require_permission
from app.models.auth_security import UserMFASecurity, MFARecoveryCode, UserSessionRecord, SSOConfiguration
from app.schemas.auth_security import (
    MFAEnrollResponse,
    MFAVerifyActivateRequest,
    MFADisableRequest,
    UserSessionResponse,
    SSOConfigCreate,
    SSOConfigResponse,
    SSOInitiateResponse
)
from app.services.totp_service import TOTPService
from app.services.session_service import SessionService
from app.services.sso_service import SSOService
from app.models.base import get_utc_now

router = APIRouter()

# ============================================================================
# MFA ENDPOINTS
# ============================================================================

@router.post("/mfa/enroll", response_model=MFAEnrollResponse)
async def enroll_mfa(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]
    email = claims.get("email", f"user_{user_id[:8]}@aurastock.com")

    secret = TOTPService.generate_secret()
    qr_uri = TOTPService.generate_qr_uri(secret, email)
    raw_codes, code_hashes = TOTPService.generate_recovery_codes(10)

    mfa_sec = (await db.execute(
        select(UserMFASecurity).where(
            UserMFASecurity.tenant_id == tenant_id,
            UserMFASecurity.user_id == user_id
        )
    )).scalar_one_or_none()

    if not mfa_sec:
        mfa_sec = UserMFASecurity(
            id=str(uuid_gen()),
            tenant_id=tenant_id,
            user_type=claims.get("user_type", "INTERNAL"),
            user_id=user_id,
            is_mfa_enabled=False,
            mfa_secret=secret
        )
        db.add(mfa_sec)
        await db.flush()
    else:
        mfa_sec.mfa_secret = secret
        mfa_sec.is_mfa_enabled = False

    # Save recovery code hashes
    for h in code_hashes:
        db.add(MFARecoveryCode(
            id=str(uuid_gen()),
            mfa_security_id=mfa_sec.id,
            tenant_id=tenant_id,
            user_id=user_id,
            code_hash=h,
            is_used=False
        ))

    await db.commit()

    return MFAEnrollResponse(
        secret=secret,
        qr_uri=qr_uri,
        recovery_codes=raw_codes
    )

@router.post("/mfa/activate")
async def activate_mfa(
    req: MFAVerifyActivateRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]

    mfa_sec = (await db.execute(
        select(UserMFASecurity).where(
            UserMFASecurity.tenant_id == tenant_id,
            UserMFASecurity.user_id == user_id
        )
    )).scalar_one_or_none()

    if not mfa_sec or not mfa_sec.mfa_secret:
        raise HTTPException(status_code=400, detail="MFA enrollment must be initiated first")

    is_valid, timestep = TOTPService.verify_totp(mfa_sec.mfa_secret, req.totp_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid TOTP verification code")

    mfa_sec.is_mfa_enabled = True
    mfa_sec.last_totp_timestep = timestep
    mfa_sec.enrolled_at = get_utc_now()
    await db.commit()

    # Cascade session invalidation
    await SessionService.revoke_all_user_sessions(db, tenant_id, user_id)

    return {"message": "MFA successfully activated"}

@router.post("/mfa/disable")
async def disable_mfa(
    req: MFADisableRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]

    mfa_sec = (await db.execute(
        select(UserMFASecurity).where(
            UserMFASecurity.tenant_id == tenant_id,
            UserMFASecurity.user_id == user_id
        )
    )).scalar_one_or_none()

    if not mfa_sec or not mfa_sec.is_mfa_enabled:
        raise HTTPException(status_code=400, detail="MFA is not enabled")

    is_valid, _ = TOTPService.verify_totp(mfa_sec.mfa_secret, req.totp_code)
    if not is_valid:
        raise HTTPException(status_code=400, detail="Invalid TOTP verification code")

    mfa_sec.is_mfa_enabled = False
    mfa_sec.mfa_secret = None
    await db.commit()

    # Cascade session invalidation
    await SessionService.revoke_all_user_sessions(db, tenant_id, user_id)

    return {"message": "MFA successfully disabled"}

# ============================================================================
# SESSION MANAGEMENT ENDPOINTS
# ============================================================================

@router.get("/sessions", response_model=List[UserSessionResponse])
async def list_active_sessions(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]

    sessions = (await db.execute(
        select(UserSessionRecord).where(
            UserSessionRecord.tenant_id == tenant_id,
            UserSessionRecord.user_id == user_id
        ).order_by(desc(UserSessionRecord.last_active_at))
    )).scalars().all()

    return [
        UserSessionResponse(
            id=s.id,
            user_id=s.user_id,
            family_id=s.family_id,
            device_name=s.device_name,
            ip_address=s.ip_address,
            user_agent=s.user_agent,
            status=s.status,
            expires_at=s.expires_at,
            last_active_at=s.last_active_at
        )
        for s in sessions
    ]

@router.post("/sessions/{session_id}/revoke")
async def revoke_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    await SessionService.revoke_session(db, session_id)
    return {"message": "Session revoked"}

@router.post("/sessions/revoke-all")
async def revoke_all_sessions(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(get_current_user_claims)
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]
    await SessionService.revoke_all_user_sessions(db, tenant_id, user_id)
    return {"message": "All sessions revoked"}

# ============================================================================
# SSO ENDPOINTS
# ============================================================================

@router.post("/sso/config", response_model=SSOConfigResponse)
async def configure_sso(
    config_in: SSOConfigCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("settings:manage"))
):
    tenant_id = claims["tenant_id"]
    return await SSOService.configure_sso(db, tenant_id, config_in)

@router.get("/sso/initiate", response_model=SSOInitiateResponse)
async def initiate_sso(
    domain: str = Query(..., description="Tenant corporate email domain e.g. acme.com"),
    db: AsyncSession = Depends(get_db)
):
    return await SSOService.initiate_sso(db, domain)

def uuid_gen() -> str:
    import uuid
    return str(uuid.uuid4())
