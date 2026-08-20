from datetime import datetime, timezone
from typing import Dict, Any
from fastapi import APIRouter, Depends, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text

from app.core.database import get_db
from app.models.general_ledger import GLAccount, JournalVoucher
from app.models.approval import ApprovalRequest
from app.models.audit import EventOutbox

router = APIRouter()

@router.get("/live")
async def liveness_probe():
    return {
        "status": "ALIVE",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "aurastock-backend"
    }

@router.get("/ready")
async def readiness_probe(db: AsyncSession = Depends(get_db)):
    try:
        # Check DB connectivity
        await db.execute(text("SELECT 1"))
        return {
            "status": "READY",
            "database": "CONNECTED",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
    except Exception as exc:
        return Response(
            content='{"status": "NOT_READY", "error": "Database connection failure"}',
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            media_type="application/json"
        )

@router.get("/subsystems")
async def subsystems_health_probe(db: AsyncSession = Depends(get_db)):
    subsystems: Dict[str, Any] = {}
    
    # 1. Database Connectivity
    try:
        await db.execute(text("SELECT 1"))
        subsystems["database"] = {"status": "HEALTHY", "driver": "sqlite/postgresql"}
    except Exception as exc:
        subsystems["database"] = {"status": "DEGRADED", "error": str(exc)}

    # 2. General Ledger Subsystem
    try:
        gl_count = (await db.execute(select(func.count(GLAccount.id)))).scalar() or 0
        jv_count = (await db.execute(select(func.count(JournalVoucher.id)))).scalar() or 0
        subsystems["general_ledger"] = {
            "status": "HEALTHY",
            "chart_of_accounts_count": gl_count,
            "journal_vouchers_posted": jv_count
        }
    except Exception as exc:
        subsystems["general_ledger"] = {"status": "DEGRADED", "error": str(exc)}

    # 3. Governance & Approval Engine
    try:
        pending_approvals = (await db.execute(
            select(func.count(ApprovalRequest.id)).where(ApprovalRequest.status.in_(["PENDING", "IN_REVIEW"]))
        )).scalar() or 0
        subsystems["approval_engine"] = {
            "status": "HEALTHY",
            "pending_approval_requests": pending_approvals
        }
    except Exception as exc:
        subsystems["approval_engine"] = {"status": "DEGRADED", "error": str(exc)}

    # 4. Outbox Relay
    try:
        pending_events = (await db.execute(
            select(func.count(EventOutbox.id)).where(EventOutbox.status == "PENDING")
        )).scalar() or 0
        subsystems["transactional_outbox"] = {
            "status": "HEALTHY",
            "pending_outbox_events": pending_events
        }
    except Exception as exc:
        subsystems["transactional_outbox"] = {"status": "DEGRADED", "error": str(exc)}

    return {
        "status": "HEALTHY" if all(v.get("status") == "HEALTHY" for v in subsystems.values()) else "DEGRADED",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "subsystems": subsystems
    }
