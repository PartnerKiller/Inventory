from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.notifications import BackgroundJobRecord
from app.schemas.notifications import (
    BackgroundJobCreate,
    BackgroundJobResponse
)
from app.services.job_service import JobService

router = APIRouter()

@router.post("/jobs", response_model=BackgroundJobResponse, status_code=status.HTTP_201_CREATED)
async def enqueue_background_job(
    job_in: BackgroundJobCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("automation:manage"))
):
    tenant_id = claims["tenant_id"]
    return await JobService.enqueue_job(db, tenant_id, job_in)

@router.post("/jobs/{job_id}/retry", response_model=BackgroundJobResponse)
async def retry_dead_letter_job(
    job_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("automation:manage"))
):
    tenant_id = claims["tenant_id"]
    return await JobService.retry_dead_letter_job(db, tenant_id, job_id)

@router.get("/jobs", response_model=List[BackgroundJobResponse])
async def list_background_jobs(
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("automation:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(BackgroundJobRecord).where(BackgroundJobRecord.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(BackgroundJobRecord.status == status)
    stmt = stmt.order_by(desc(BackgroundJobRecord.created_at)).limit(limit)

    jobs = (await db.execute(stmt)).scalars().all()
    return [
        BackgroundJobResponse(
            id=j.id,
            job_type=j.job_type,
            task_name=j.task_name,
            payload_json=j.payload_json,
            status=j.status,
            attempt_count=j.attempt_count,
            max_attempts=j.max_attempts,
            scheduled_for=j.scheduled_for,
            started_at=j.started_at,
            completed_at=j.completed_at,
            error_message=j.error_message,
            idempotency_key=j.idempotency_key,
            created_at=j.created_at
        )
        for j in jobs
    ]
