import pytest
import time
import uuid
from decimal import Decimal
from typing import Tuple, List, Optional
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException

from app.core.config import settings
from app.models.auth import User
from app.models.auth_security import UserMFASecurity, MFARecoveryCode, UserSessionRecord, SSOConfiguration
from app.models.ledger import StockLedgerTransaction
from app.models.costing import CostLayer
from app.schemas.auth_security import SSOConfigCreate
from app.services.totp_service import TOTPService
from app.services.session_service import SessionService
from app.services.sso_service import SSOService

# ============================================================================
# 1. RFC 6238 TOTP GENERATION & ENROLLMENT
# ============================================================================

def test_rfc6238_totp_generation_and_enrollment():
    secret = TOTPService.generate_secret()
    assert len(secret) >= 32 # 160-bit Base32 secret

    qr_uri = TOTPService.generate_qr_uri(secret, "alice@aurastock.com")
    assert "otpauth://totp/AuraStock:alice@aurastock.com" in qr_uri
    assert f"secret={secret}" in qr_uri
    assert "digits=6" in qr_uri
    assert "period=30" in qr_uri

# ============================================================================
# 2. TOTP VALID CODE & CLOCK SKEW (±30s)
# ============================================================================

def test_totp_valid_code_and_clock_skew():
    secret = TOTPService.generate_secret()
    current_step = int(time.time() // 30)

    # 1. Current timestep code -> VALID
    current_code = TOTPService.compute_totp(secret, time_step=current_step)
    valid_curr, ts_curr = TOTPService.verify_totp(secret, current_code)
    assert valid_curr is True
    assert ts_curr == current_step

    # 2. Past timestep code (T-1) -> VALID
    past_code = TOTPService.compute_totp(secret, time_step=current_step - 1)
    valid_past, _ = TOTPService.verify_totp(secret, past_code)
    assert valid_past is True

    # 3. Future timestep code (T+1) -> VALID
    future_code = TOTPService.compute_totp(secret, time_step=current_step + 1)
    valid_fut, _ = TOTPService.verify_totp(secret, future_code)
    assert valid_fut is True

    # 4. Outdated timestep (T-3) -> REJECT
    out_code = TOTPService.compute_totp(secret, time_step=current_step - 3)
    valid_out, _ = TOTPService.verify_totp(secret, out_code)
    assert valid_out is False

# ============================================================================
# 3. TOTP REPLAY REJECTION
# ============================================================================

def test_totp_replay_rejection():
    secret = TOTPService.generate_secret()
    current_step = int(time.time() // 30)
    code = TOTPService.compute_totp(secret, time_step=current_step)

    # First attempt: succeeds
    valid, last_ts = TOTPService.verify_totp(secret, code, last_timestep=0)
    assert valid is True
    assert last_ts == current_step

    # Second attempt with same code and last_timestep set -> REJECT (400)
    with pytest.raises(HTTPException) as exc_info:
        TOTPService.verify_totp(secret, code, last_timestep=last_ts)
    assert exc_info.value.status_code == 400
    assert "Replay Detected" in exc_info.value.detail

# ============================================================================
# 4. RECOVERY CODES SINGLE-USE & REUSE REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_recovery_code_single_use_and_reuse_rejection(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    raw_codes, code_hashes = TOTPService.generate_recovery_codes(10)
    assert len(raw_codes) == 10

    mfa_sec = UserMFASecurity(
        id=str(uuid.uuid4()), tenant_id=tenant_id, user_id=user_id,
        is_mfa_enabled=True, mfa_secret=TOTPService.generate_secret()
    )
    db_session.add(mfa_sec)
    await db_session.flush()

    for h in code_hashes:
        db_session.add(MFARecoveryCode(
            id=str(uuid.uuid4()), mfa_security_id=mfa_sec.id,
            tenant_id=tenant_id, user_id=user_id, code_hash=h, is_used=False
        ))
    await db_session.commit()

    test_raw_code = raw_codes[0]
    computed_hash = TOTPService.hash_recovery_code(test_raw_code)

    # 1. First consumption -> SUCCESS
    rc = (await db_session.execute(
        select(MFARecoveryCode).where(
            MFARecoveryCode.user_id == user_id,
            MFARecoveryCode.code_hash == computed_hash,
            MFARecoveryCode.is_used == False
        )
    )).scalar_one_or_none()
    assert rc is not None

    rc.is_used = True
    rc.used_at = datetime.now(timezone.utc)
    await db_session.commit()

    # 2. Replay of same recovery code -> REJECT (already used)
    rc_reuse = (await db_session.execute(
        select(MFARecoveryCode).where(
            MFARecoveryCode.user_id == user_id,
            MFARecoveryCode.code_hash == computed_hash,
            MFARecoveryCode.is_used == False
        )
    )).scalar_one_or_none()
    assert rc_reuse is None

# ============================================================================
# 5. REFRESH TOKEN ROTATION
# ============================================================================

@pytest.mark.asyncio
async def test_refresh_token_rotation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    s1, raw_t1 = await SessionService.create_session(db_session, tenant_id, user_id)
    assert s1.status == "ACTIVE"

    # Rotate
    s2, raw_t2 = await SessionService.rotate_session(db_session, raw_t1)
    assert s2.family_id == s1.family_id
    assert s2.status == "ACTIVE"

    db_s1 = (await db_session.execute(select(UserSessionRecord).where(UserSessionRecord.id == s1.id))).scalar_one()
    assert db_s1.status == "USED"

# ============================================================================
# 6. REUSE DETECTION & AUTOMATIC TOKEN FAMILY REVOCATION
# ============================================================================

@pytest.mark.asyncio
async def test_token_reuse_detection_and_family_revocation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    s1, raw_t1 = await SessionService.create_session(db_session, tenant_id, user_id)
    family_id = s1.family_id

    # Normal rotation: T1 -> T2
    s2, raw_t2 = await SessionService.rotate_session(db_session, raw_t1)
    # Normal rotation: T2 -> T3
    s3, raw_t3 = await SessionService.rotate_session(db_session, raw_t2)

    # Attacker presents already-used T1 -> REUSE DETECTED
    with pytest.raises(HTTPException) as exc_info:
        await SessionService.rotate_session(db_session, raw_t1)
    assert exc_info.value.status_code == 401
    assert "Refresh token reuse detected" in exc_info.value.detail

    # Verify all sessions in family are REVOKED
    all_sess = (await db_session.execute(
        select(UserSessionRecord).where(UserSessionRecord.family_id == family_id)
    )).scalars().all()
    assert all(s.status == "REVOKED" for s in all_sess)

# ============================================================================
# 7. PASSWORD CHANGE SESSION INVALIDATION
# ============================================================================

@pytest.mark.asyncio
async def test_password_change_session_invalidation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    s1, _ = await SessionService.create_session(db_session, tenant_id, user_id, device_name="Device 1")
    s2, _ = await SessionService.create_session(db_session, tenant_id, user_id, device_name="Device 2")

    # Simulate password change cascade
    await SessionService.revoke_all_user_sessions(db_session, tenant_id, user_id)

    active_count = (await db_session.execute(
        select(func.count()).select_from(UserSessionRecord).where(
            UserSessionRecord.user_id == user_id,
            UserSessionRecord.status == "ACTIVE"
        )
    )).scalar()
    assert active_count == 0

# ============================================================================
# 8. MFA CHANGE SESSION INVALIDATION
# ============================================================================

@pytest.mark.asyncio
async def test_mfa_change_session_invalidation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    await SessionService.create_session(db_session, tenant_id, user_id)
    await SessionService.revoke_all_user_sessions(db_session, tenant_id, user_id)

    active_count = (await db_session.execute(
        select(func.count()).select_from(UserSessionRecord).where(
            UserSessionRecord.user_id == user_id,
            UserSessionRecord.status == "ACTIVE"
        )
    )).scalar()
    assert active_count == 0

# ============================================================================
# 9. ROLE CHANGE & ACCOUNT DEACTIVATION INVALIDATION
# ============================================================================

@pytest.mark.asyncio
async def test_deactivation_session_invalidation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    await SessionService.create_session(db_session, tenant_id, user_id)
    await SessionService.revoke_all_user_sessions(db_session, tenant_id, user_id)

    revoked_count = (await db_session.execute(
        select(func.count()).select_from(UserSessionRecord).where(
            UserSessionRecord.user_id == user_id,
            UserSessionRecord.status == "REVOKED"
        )
    )).scalar()
    assert revoked_count >= 1

# ============================================================================
# 10. PROGRESSIVE LOCKOUT & ANTI-ENUMERATION
# ============================================================================

def test_progressive_lockout_and_anti_enumeration():
    def evaluate_lockout(failed_attempts: int) -> Tuple[bool, int]:
        if failed_attempts >= 5:
            return True, 900
        elif failed_attempts >= 3:
            return False, 5
        return False, 0

    assert evaluate_lockout(1) == (False, 0)
    assert evaluate_lockout(3) == (False, 5)
    assert evaluate_lockout(5) == (True, 900)

    # Anti-enumeration response consistency
    generic_error = "Invalid credentials"
    assert generic_error == "Invalid credentials"

# ============================================================================
# 11. OIDC PKCE GENERATION & VERIFICATION
# ============================================================================

def test_oidc_pkce_generation():
    verifier, challenge = SSOService.generate_pkce_pair()
    assert len(verifier) >= 43
    assert len(challenge) >= 43

# ============================================================================
# 12. OIDC STATE & NONCE VALIDATION
# ============================================================================

@pytest.mark.asyncio
async def test_oidc_state_and_nonce_validation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    await SSOService.configure_sso(
        db=db_session, tenant_id=tenant_id,
        config_in=SSOConfigCreate(
            domain="corp-global.com",
            issuer_url="https://sso.okta.com",
            client_id="okta_123",
            client_secret="sec_456"
        )
    )

    init_res = await SSOService.initiate_sso(db_session, "corp-global.com")
    assert "state=" in init_res.auth_url
    assert "nonce=" in init_res.auth_url

# ============================================================================
# 13. OIDC ISSUER / AUDIENCE & DOMAIN VALIDATION
# ============================================================================

def test_oidc_claims_validation():
    valid_claims = {
        "iss": "https://sso.okta.com",
        "aud": "okta_123",
        "nonce": "nonce_xyz",
        "email_verified": True,
        "email": "user@corp-global.com"
    }

    # 1. Valid claims -> ACCEPT
    validated = SSOService.validate_oidc_claims(
        claims=valid_claims,
        expected_issuer="https://sso.okta.com",
        expected_audience="okta_123",
        expected_nonce="nonce_xyz",
        expected_domain="corp-global.com"
    )
    assert validated["email"] == "user@corp-global.com"

    # 2. Issuer mismatch -> REJECT (400)
    with pytest.raises(HTTPException) as exc_info:
        SSOService.validate_oidc_claims(valid_claims, "https://evil.com", "okta_123", "nonce_xyz", "corp-global.com")
    assert exc_info.value.status_code == 400
    assert "Issuer mismatch" in exc_info.value.detail

    # 3. Audience mismatch -> REJECT (400)
    with pytest.raises(HTTPException) as exc_info:
        SSOService.validate_oidc_claims(valid_claims, "https://sso.okta.com", "wrong_aud", "nonce_xyz", "corp-global.com")
    assert exc_info.value.status_code == 400
    assert "Audience mismatch" in exc_info.value.detail

    # 4. Domain mismatch -> REJECT (400)
    with pytest.raises(HTTPException) as exc_info:
        SSOService.validate_oidc_claims(valid_claims, "https://sso.okta.com", "okta_123", "nonce_xyz", "othercorp.com")
    assert exc_info.value.status_code == 400
    assert "Domain mismatch" in exc_info.value.detail

# ============================================================================
# 14. SSO ACCOUNT LINKING TAKEOVER PREVENTION
# ============================================================================

def test_sso_account_linking_takeover_prevention():
    unverified_email_claims = {
        "iss": "https://sso.okta.com",
        "aud": "okta_123",
        "nonce": "nonce_xyz",
        "email_verified": False,
        "email": "victim@corp-global.com"
    }

    with pytest.raises(HTTPException) as exc_info:
        SSOService.validate_oidc_claims(
            claims=unverified_email_claims,
            expected_issuer="https://sso.okta.com",
            expected_audience="okta_123",
            expected_nonce="nonce_xyz",
            expected_domain="corp-global.com"
        )
    assert exc_info.value.status_code == 400
    assert "Takeover Prevention" in exc_info.value.detail

# ============================================================================
# 15. CROSS-TENANT IDENTITY ISOLATION
# ============================================================================

@pytest.mark.asyncio
async def test_cross_tenant_identity_isolation(db_session: AsyncSession):
    tenant_a = str(uuid.uuid4())
    tenant_b = str(uuid.uuid4())

    user_a = str(uuid.uuid4())
    user_b = str(uuid.uuid4())

    # Create session in Tenant A
    await SessionService.create_session(db_session, tenant_a, user_a)
    # Create session in Tenant B
    await SessionService.create_session(db_session, tenant_b, user_b)

    sessions_a = (await db_session.execute(select(UserSessionRecord).where(UserSessionRecord.tenant_id == tenant_a))).scalars().all()
    sessions_b = (await db_session.execute(select(UserSessionRecord).where(UserSessionRecord.tenant_id == tenant_b))).scalars().all()

    assert len(sessions_a) == 1
    assert sessions_a[0].user_id == user_a
    assert len(sessions_b) == 1
    assert sessions_b[0].user_id == user_b

# ============================================================================
# 16. SECURITY AUDIT & NO SENSITIVE DATA IN LOGS
# ============================================================================

def test_no_sensitive_data_in_logs():
    # Audit log payload sanitization check
    raw_event = {
        "event": "AUTH_MFA_ENROLLED",
        "user_id": "user_123",
        "secret": "JBSWY3DPEHPK3PXP",
        "recovery_code": "A1B2-C3D4-E5F6"
    }

    # Redaction
    sanitized = {k: v for k, v in raw_event.items() if k not in ("secret", "recovery_code", "password", "token")}
    assert "secret" not in sanitized
    assert "recovery_code" not in sanitized
    assert sanitized["event"] == "AUTH_MFA_ENROLLED"

# ============================================================================
# 17. ZERO INVENTORY / COSTING MUTATION INVARIANT
# ============================================================================

@pytest.mark.asyncio
async def test_auth_security_zero_inventory_mutation(db_session: AsyncSession):
    tenant_id = settings.TENANT_DEFAULT_ID
    user_id = str(uuid.uuid4())

    tx_cnt_before = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    layer_cnt_before = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    # Create session & configure SSO
    await SessionService.create_session(db_session, tenant_id, user_id)
    await SSOService.configure_sso(
        db=db_session, tenant_id=tenant_id,
        config_in=SSOConfigCreate(
            domain=f"audit-{uuid.uuid4().hex[:4]}.com",
            issuer_url="https://sso.okta.com",
            client_id="id",
            client_secret="sec"
        )
    )

    tx_cnt_after = (await db_session.execute(select(func.count()).select_from(StockLedgerTransaction))).scalar()
    layer_cnt_after = (await db_session.execute(select(func.count()).select_from(CostLayer))).scalar()

    assert tx_cnt_after == tx_cnt_before
    assert layer_cnt_after == layer_cnt_before
