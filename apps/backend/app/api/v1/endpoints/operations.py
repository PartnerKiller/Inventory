import time
import os
import shutil
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.core.permissions import require_permission
from app.core.config import settings
from app.services.metrics_service import metrics_service
from app.services.backup_service import BackupService
from app.services.integrity_service import IntegrityService

router = APIRouter()

@router.get("/status", summary="Operational System Status")
async def get_system_status(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("audit:read"))
) -> Dict[str, Any]:
    """
    Returns high-level operational status, database connectivity & latency,
    storage statistics, and backup recency for authorized administrators.
    """
    db_start = time.time()
    db_ok = False
    db_latency_ms = 0.0
    try:
        await db.execute(text("SELECT 1"))
        db_latency_ms = round((time.time() - db_start) * 1000, 2)
        db_ok = True
    except Exception:
        db_ok = False

    metrics_snap = metrics_service.get_metrics_snapshot()
    backups = BackupService.list_backups()
    latest_backup = backups[0] if backups else None

    # Disk usage for backup destination
    backup_dir = BackupService.get_backup_dir()
    disk_stat = shutil.disk_usage(backup_dir)

    return {
        "status": "OPERATIONAL" if db_ok else "DEGRADED",
        "service": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": "production",
        "database": {
            "connected": db_ok,
            "latency_ms": db_latency_ms,
            "engine": "PostgreSQL" if "postgres" in settings.DATABASE_URL else "SQLite"
        },
        "storage": {
            "total_bytes": disk_stat.total,
            "free_bytes": disk_stat.free,
            "free_percent": round((disk_stat.free / disk_stat.total) * 100, 1)
        },
        "metrics_summary": {
            "uptime_seconds": metrics_snap["uptime_seconds"],
            "total_requests": metrics_snap["total_requests"],
            "error_count": metrics_snap["error_count"],
            "avg_latency_ms": metrics_snap["latency_ms"]["avg"],
            "p95_latency_ms": metrics_snap["latency_ms"]["p95"]
        },
        "backup": {
            "total_backups": len(backups),
            "latest_backup": latest_backup,
            "retention_policy": "7 historical snapshots with SHA-256 verification"
        }
    }

@router.get("/metrics", summary="Operational Performance Metrics")
async def get_metrics(
    claims: dict = Depends(require_permission("audit:read"))
) -> Dict[str, Any]:
    """
    Returns thread-safe operational request counters, HTTP status code distributions,
    latency percentiles, and operational event history.
    """
    return metrics_service.get_metrics_snapshot()

@router.get("/backups", summary="List Database Backups")
async def list_backups(
    claims: dict = Depends(require_permission("settings:read"))
) -> List[Dict[str, Any]]:
    """
    Lists available verified database backups with file sizes, timestamps, and SHA-256 hashes.
    """
    return BackupService.list_backups()

@router.post("/backups", summary="Trigger On-Demand Verified Backup")
async def trigger_backup(
    claims: dict = Depends(require_permission("settings:write"))
) -> Dict[str, Any]:
    """
    Triggers an immediate database backup with SHA-256 integrity verification.
    """
    result = BackupService.create_backup()
    if result.get("status") == "FAILED":
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backup generation failed: {result.get('error')}"
        )
    return result

@router.post("/integrity-check", summary="Run Read-Only Data Integrity & Invariant Audit")
async def run_integrity_check(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("audit:read"))
) -> Dict[str, Any]:
    """
    Audits physical stock invariants (available = on_hand - allocated) and reconciles
    cumulative immutable stock ledger entries against balance cache projections.
    Strictly read-only; never mutates business records.
    """
    tenant_id = claims.get("tenant_id") or settings.TENANT_DEFAULT_ID
    return await IntegrityService.run_full_integrity_check(db, tenant_id)
