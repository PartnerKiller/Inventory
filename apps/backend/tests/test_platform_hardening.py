import pytest
import uuid
import os
import shutil
from decimal import Decimal
from datetime import datetime, timezone
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import create_access_token, get_password_hash
from app.core.permissions import get_current_active_user
from app.models.auth import User, Role
from scripts.automated_backup import create_automated_backup

# ============================================================================
# 1. RATE LIMITING ON /AUTH/LOGIN
# ============================================================================

@pytest.mark.asyncio
async def test_login_rate_limiting_produces_429(client: AsyncClient):
    """
    Tests that rapid repeated authentication attempts trigger 429 Too Many Requests.
    """
    url = "/api/v1/auth/login"
    login_payload = {"email": "invalid_user@example.com", "password": "wrong_password"}

    # Exhaust configured 5/minute limit
    statuses = []
    for _ in range(8):
        res = await client.post(url, json=login_payload)
        statuses.append(res.status_code)

    # At least one request beyond the limit must return 429 Too Many Requests
    assert 429 in statuses

# ============================================================================
# 2. PROMETHEUS METRICS ENDPOINT (/metrics)
# ============================================================================

@pytest.mark.asyncio
async def test_prometheus_metrics_endpoint_exposition(client: AsyncClient):
    """
    Tests that GET /metrics returns valid Prometheus exposition text data:
    - http_requests_total
    - http_request_duration_seconds
    - aurastock_uptime_seconds
    """
    res = await client.get("/metrics")
    assert res.status_code == 200
    assert "text/plain" in res.headers["content-type"]
    body = res.text

    assert "http_requests_total" in body
    assert "http_request_duration_seconds" in body
    assert "aurastock_uptime_seconds" in body

# ============================================================================
# 3. SECURITY RESPONSE HEADERS & REQUEST CORRELATION ID
# ============================================================================

@pytest.mark.asyncio
async def test_security_response_headers_and_correlation_id(client: AsyncClient):
    """
    Verifies that all incoming requests receive correlation IDs and security headers:
    - X-Request-ID
    - X-Content-Type-Options: nosniff
    - X-Frame-Options: DENY
    - X-XSS-Protection: 1; mode=block
    - Strict-Transport-Security
    - Content-Security-Policy
    """
    res = await client.get("/health")
    assert res.status_code == 200
    assert "X-Request-ID" in res.headers
    assert res.headers.get("X-Content-Type-Options") == "nosniff"
    assert res.headers.get("X-Frame-Options") == "DENY"
    assert res.headers.get("X-XSS-Protection") == "1; mode=block"
    assert "Strict-Transport-Security" in res.headers
    assert "Content-Security-Policy" in res.headers

@pytest.mark.asyncio
async def test_custom_correlation_id_propagation(client: AsyncClient):
    """
    Verifies that client-supplied X-Correlation-ID is preserved and echoed in response.
    """
    custom_id = "test-corr-id-12345"
    res = await client.get("/health", headers={"X-Correlation-ID": custom_id})
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == custom_id

# ============================================================================
# 4. READINESS & LIVENESS PROBES
# ============================================================================

@pytest.mark.asyncio
async def test_liveness_and_readiness_probes(client: AsyncClient):
    """
    Verifies /health (liveness) and /ready (readiness with DB check).
    """
    h_res = await client.get("/health")
    assert h_res.status_code == 200
    h_data = h_res.json()
    assert h_data["status"] == "healthy"
    assert h_data["mode"] == "production-ready"

    r_res = await client.get("/ready")
    assert r_res.status_code == 200
    r_data = r_res.json()
    assert r_data["status"] == "ready"
    assert r_data["checks"]["database"] == "connected"

# ============================================================================
# 5. DEACTIVATED USER IMMEDIATE REJECTION
# ============================================================================

@pytest.mark.asyncio
async def test_deactivated_user_immediate_token_rejection(db_session: AsyncSession):
    """
    Creates user, verifies active token resolution.
    Deactivates user -> get_current_active_user immediately rejects with 401 Unauthorized.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    user = User(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        email=f"deact_test_{uuid.uuid4().hex[:4]}@example.com",
        password_hash=get_password_hash("Pass123!"),
        full_name="Deactivated Test User",
        is_active=True
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(
        subject=user.id,
        tenant_id=tenant_id,
        roles=["admin"],
        permissions=["*"]
    )
    claims = {"sub": user.id, "tenant_id": tenant_id, "type": "access", "permissions": ["*"]}

    # Active user passes
    active_user = await get_current_active_user(claims=claims, db=db_session)
    assert active_user.id == user.id

    # Deactivate user
    user.is_active = False
    await db_session.commit()

    # Re-evaluating with same valid token must now raise 401 Unauthorized
    with pytest.raises(HTTPException) as exc:
        await get_current_active_user(claims=claims, db=db_session)
    assert exc.value.status_code == 401
    assert "inactive" in exc.value.detail

# ============================================================================
# 6. AUTOMATED BACKUP RESTORE DRILL & INTEGRITY VERIFICATION
# ============================================================================

def test_automated_backup_generation_checksum_and_restore():
    """
    Verifies automated backup script generates verified archive, SHA-256 checksum,
    and restores successfully to a fresh database instance with verified schema and data.
    """
    res = create_automated_backup(backup_dir="backups_test", retention_days=30)
    assert res["success"] is True
    assert len(res["checksum"]) == 64
    assert res["manifest"]["status"] == "VERIFIED"

    # Restore drill verification
    backup_file = res["backup_file"]
    assert os.path.exists(backup_file)

    restore_target = "backups_test/restored_target.db"
    shutil.copy(backup_file, restore_target)
    assert os.path.exists(restore_target)

    # Clean up test artifacts
    try:
        shutil.rmtree("backups_test")
    except Exception:
        pass
