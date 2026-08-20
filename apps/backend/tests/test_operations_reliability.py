import os
import shutil
import tempfile
import pytest
import logging
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.core.config import settings
from app.core.logging import SensitiveDataFilter
from app.services.backup_service import BackupService
from app.services.integrity_service import IntegrityService
from app.models.ledger import StockBalanceCache

@pytest.mark.asyncio
async def test_health_and_readiness_endpoints(client: AsyncClient):
    """
    Verifies /health liveness and /ready readiness probes.
    """
    # 1. Health check
    res_health = await client.get("/health")
    assert res_health.status_code == 200
    data_health = res_health.json()
    assert data_health["status"] == "healthy"
    assert "uptime_seconds" in data_health
    assert data_health["version"] == settings.VERSION

    # 2. Readiness check
    res_ready = await client.get("/ready")
    assert res_ready.status_code == 200
    data_ready = res_ready.json()
    assert data_ready["status"] == "ready"
    assert data_ready["ready"] is True
    assert data_ready["checks"]["database"] == "connected"
    assert data_ready["checks"]["latency_ms"] >= 0

@pytest.mark.asyncio
async def test_request_correlation_and_error_propagation(client: AsyncClient):
    """
    Verifies request correlation ID extraction, header propagation, and RFC 7807 error attachment.
    """
    custom_req_id = "test-correlation-uuid-9999"
    res = await client.get("/health", headers={"X-Request-ID": custom_req_id})
    assert res.status_code == 200
    assert res.headers.get("X-Request-ID") == custom_req_id

    # Automatic generation when header not provided
    res_auto = await client.get("/health")
    assert res_auto.status_code == 200
    assert "X-Request-ID" in res_auto.headers
    assert len(res_auto.headers["X-Request-ID"]) > 10

    # RFC 7807 Error response contains correlation request_id
    res_err = await client.get("/api/v1/non-existent-endpoint", headers={"X-Request-ID": custom_req_id})
    assert res_err.status_code == 404
    data_err = res_err.json()
    assert data_err["request_id"] == custom_req_id

def test_sensitive_log_redaction():
    """
    Verifies SensitiveDataFilter redacts tokens, passwords, and private credentials.
    """
    filter_inst = SensitiveDataFilter()
    
    # Text redaction
    sample_text = "User login failed with password=super_secret_pass_123 and Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeak"
    redacted = filter_inst.redact_string(sample_text)
    assert "super_secret_pass_123" not in redacted
    assert "***REDACTED***" in redacted
    assert "Bearer ***REDACTED_TOKEN***" in redacted

    # Dict payload redaction
    sample_dict = {
        "user_email": "admin@aurastock.local",
        "password": "ClearTextPassword123!",
        "access_token": "secret_jwt_token_data",
        "nested": {
            "refresh_token": "secret_refresh_data",
            "safe_counter": 42
        }
    }
    redacted_dict = filter_inst.redact_dict(sample_dict)
    assert redacted_dict["password"] == "***REDACTED***"
    assert redacted_dict["access_token"] == "***REDACTED***"
    assert redacted_dict["nested"]["refresh_token"] == "***REDACTED***"
    assert redacted_dict["nested"]["safe_counter"] == 42
    assert redacted_dict["user_email"] == "admin@aurastock.local"

@pytest.mark.asyncio
async def test_database_backup_integrity_and_retention():
    """
    Verifies automated database snapshot creation, SHA-256 checksum integrity verification,
    and retention policy enforcement.
    """
    temp_backup_dir = tempfile.mkdtemp(prefix="aurastock_test_backups_")
    try:
        # Create backup
        backup_res = BackupService.create_backup(custom_dir=temp_backup_dir)
        assert backup_res["status"] == "SUCCESS"
        assert backup_res["verified"] is True
        assert os.path.exists(backup_res["filepath"])
        assert backup_res["size_bytes"] > 0
        assert len(backup_res["checksum_sha256"]) == 64

        # List backups
        listed = BackupService.list_backups(custom_dir=temp_backup_dir)
        assert len(listed) >= 1
        assert listed[0]["filename"] == backup_res["filename"]
        assert listed[0]["checksum_sha256"] == backup_res["checksum_sha256"]

        # Verify single file
        verification = BackupService.verify_backup_file(backup_res["filename"], custom_dir=temp_backup_dir)
        assert verification["valid"] is True
        assert verification["checksum_sha256"] == backup_res["checksum_sha256"]

        # Enforce retention pruning
        # Simulate creating multiple older files
        for i in range(10):
            dummy_file = os.path.join(temp_backup_dir, f"aurastock_old_2026010{i}_000000.sql.gz")
            with open(dummy_file, "wb") as f:
                f.write(f"backup content {i}".encode("utf-8"))
        
        # Apply pruning to keep only 5
        BackupService.prune_retention(temp_backup_dir, keep_count=5)
        remaining = BackupService.list_backups(custom_dir=temp_backup_dir)
        assert len(remaining) == 5

    finally:
        shutil.rmtree(temp_backup_dir, ignore_errors=True)

@pytest.mark.asyncio
async def test_read_only_data_integrity_check(client: AsyncClient, db_session: AsyncSession):
    """
    Verifies read-only invariant audit and discrepancy detection for available = on_hand - allocated.
    """
    tenant_id = settings.TENANT_DEFAULT_ID
    
    # 1. Clean run on seeded data
    report = await IntegrityService.run_full_integrity_check(db_session, tenant_id)
    assert report["overall_status"] == "HEALTHY"
    assert report["checks_performed"] > 0
    assert report["discrepancies_count"] == 0
    assert len(report["invariants_verified"]) >= 4

    # 2. Deliberately introduce over-receipt discrepancy in PO line
    from app.models.purchasing import POLineItem
    res_po = await db_session.execute(select(POLineItem))
    po_line = res_po.scalars().first()
    if po_line:
        orig_rcv = po_line.quantity_received
        orig_ord = po_line.quantity_ordered
        # Set received > ordered to trigger warning
        po_line.quantity_received = float(orig_ord) + 50.0
        await db_session.flush()

        corrupted_report = await IntegrityService.run_full_integrity_check(db_session, tenant_id)
        assert corrupted_report["overall_status"] == "DISCREPANCIES_DETECTED"
        assert corrupted_report["discrepancies_count"] >= 1
        mismatch_disc = [d for d in corrupted_report["discrepancies"] if d["code"] == "PO_OVER_RECEIPT_DETECTED"]
        assert len(mismatch_disc) >= 1

        # Revert change
        po_line.quantity_received = orig_rcv
        await db_session.flush()

@pytest.mark.asyncio
async def test_operations_api_endpoints_and_rbac(client: AsyncClient):
    """
    Verifies /api/v1/operations endpoints are accessible to Super Admin and protected against unauthenticated users.
    """
    # 1. Unauthenticated request receives 401
    res_unauth = await client.get("/api/v1/operations/status")
    assert res_unauth.status_code == 401

    # 2. Super Admin login
    login_res = await client.post("/api/v1/auth/login", json={
        "email": "admin@inventory.local",
        "password": "Admin123!"
    })
    assert login_res.status_code == 200
    token = login_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # 3. Super Admin status access
    res_status = await client.get("/api/v1/operations/status", headers=headers)
    assert res_status.status_code == 200
    data_status = res_status.json()
    assert data_status["status"] == "OPERATIONAL"
    assert data_status["database"]["connected"] is True
    assert "metrics_summary" in data_status
    assert "backup" in data_status

    # 4. Metrics endpoint
    res_metrics = await client.get("/api/v1/operations/metrics", headers=headers)
    assert res_metrics.status_code == 200
    data_metrics = res_metrics.json()
    assert "total_requests" in data_metrics
    assert "status_breakdown" in data_metrics

    # 5. List backups endpoint
    res_backups = await client.get("/api/v1/operations/backups", headers=headers)
    assert res_backups.status_code == 200
    assert isinstance(res_backups.json(), list)

    # 6. Integrity check endpoint
    res_integrity = await client.post("/api/v1/operations/integrity-check", headers=headers)
    assert res_integrity.status_code == 200
    assert res_integrity.json()["overall_status"] in ["HEALTHY", "DISCREPANCIES_DETECTED"]

@pytest.mark.asyncio
async def test_worker_scheduled_backup_cron():
    """
    Verifies that the ARQ worker recurring backup job invokes BackupService,
    produces a verified backup snapshot, and updates operational metrics.
    """
    from app.worker import scheduled_daily_backup, WorkerSettings
    
    # 1. Verify cron settings registration
    assert len(WorkerSettings.cron_jobs) >= 1
    assert scheduled_daily_backup in WorkerSettings.functions

    # 2. Execute scheduled backup job
    ctx = {}
    result = await scheduled_daily_backup(ctx)
    assert result["status"] == "SUCCESS"
    assert result["verified"] is True
    assert result["size_bytes"] > 0
    assert "checksum_sha256" in result
