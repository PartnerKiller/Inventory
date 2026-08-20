import uuid
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from fastapi import HTTPException

from app.models.base import get_utc_now
from app.models.notifications import BackgroundJobRecord
from app.schemas.notifications import BackgroundJobCreate, BackgroundJobResponse

class JobService:
    @staticmethod
    async def enqueue_job(
        db: AsyncSession,
        tenant_id: str,
        job_in: BackgroundJobCreate
    ) -> BackgroundJobResponse:
        # Idempotency check
        existing = (await db.execute(
            select(BackgroundJobRecord).where(
                BackgroundJobRecord.tenant_id == tenant_id,
                BackgroundJobRecord.idempotency_key == job_in.idempotency_key
            )
        )).scalar_one_or_none()

        if existing:
            return BackgroundJobResponse(
                id=existing.id,
                job_type=existing.job_type,
                task_name=existing.task_name,
                payload_json=existing.payload_json,
                status=existing.status,
                attempt_count=existing.attempt_count,
                max_attempts=existing.max_attempts,
                scheduled_for=existing.scheduled_for,
                started_at=existing.started_at,
                completed_at=existing.completed_at,
                error_message=existing.error_message,
                idempotency_key=existing.idempotency_key,
                created_at=existing.created_at
            )

        job = BackgroundJobRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            job_type=job_in.job_type,
            task_name=job_in.task_name,
            payload_json=job_in.payload_json,
            status="QUEUED",
            attempt_count=0,
            max_attempts=job_in.max_attempts,
            scheduled_for=job_in.scheduled_for or get_utc_now(),
            idempotency_key=job_in.idempotency_key
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        return BackgroundJobResponse(
            id=job.id,
            job_type=job.job_type,
            task_name=job.task_name,
            payload_json=job.payload_json,
            status=job.status,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            scheduled_for=job.scheduled_for,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            idempotency_key=job.idempotency_key,
            created_at=job.created_at
        )

    @staticmethod
    async def run_job(
        db: AsyncSession,
        job_id: str,
        worker_fn: Callable[[Dict[str, Any]], Awaitable[None]]
    ) -> BackgroundJobRecord:
        job = (await db.execute(
            select(BackgroundJobRecord).where(BackgroundJobRecord.id == job_id).with_for_update()
        )).scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Background job not found")

        if job.status == "CANCELLED":
            raise HTTPException(status_code=400, detail="Cannot run a CANCELLED job")

        job.status = "RUNNING"
        job.started_at = get_utc_now()
        await db.commit()

        try:
            await worker_fn(job.payload_json)
            job.status = "SUCCEEDED"
            job.completed_at = get_utc_now()
            job.error_message = None
        except Exception as exc:
            job.attempt_count += 1
            job.error_message = str(exc)
            if job.attempt_count >= job.max_attempts:
                job.status = "DEAD_LETTER"
            else:
                job.status = "RETRYING"
                # Exponential backoff: 5 * 2^(attempt - 1) seconds
                backoff_seconds = 5 * (2 ** (job.attempt_count - 1))
                job.scheduled_for = get_utc_now() + timedelta(seconds=backoff_seconds)

        await db.commit()
        await db.refresh(job)
        return job

    @staticmethod
    async def retry_dead_letter_job(
        db: AsyncSession,
        tenant_id: str,
        job_id: str
    ) -> BackgroundJobResponse:
        job = (await db.execute(
            select(BackgroundJobRecord).where(
                BackgroundJobRecord.id == job_id,
                BackgroundJobRecord.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Background job not found")

        if job.status != "DEAD_LETTER":
            raise HTTPException(status_code=400, detail="Only DEAD_LETTER jobs can be re-queued via this endpoint")

        job.status = "QUEUED"
        job.attempt_count = 0
        job.scheduled_for = get_utc_now()
        job.error_message = None
        await db.commit()
        await db.refresh(job)

        return BackgroundJobResponse(
            id=job.id,
            job_type=job.job_type,
            task_name=job.task_name,
            payload_json=job.payload_json,
            status=job.status,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            scheduled_for=job.scheduled_for,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            idempotency_key=job.idempotency_key,
            created_at=job.created_at
        )

    @staticmethod
    async def cancel_job(
        db: AsyncSession,
        tenant_id: str,
        job_id: str
    ) -> BackgroundJobResponse:
        job = (await db.execute(
            select(BackgroundJobRecord).where(
                BackgroundJobRecord.id == job_id,
                BackgroundJobRecord.tenant_id == tenant_id
            ).with_for_update()
        )).scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Background job not found")

        if job.status in ("SUCCEEDED", "DEAD_LETTER"):
            raise HTTPException(status_code=400, detail=f"Cannot cancel job in {job.status} status")

        job.status = "CANCELLED"
        job.completed_at = get_utc_now()
        await db.commit()
        await db.refresh(job)

        return BackgroundJobResponse(
            id=job.id,
            job_type=job.job_type,
            task_name=job.task_name,
            payload_json=job.payload_json,
            status=job.status,
            attempt_count=job.attempt_count,
            max_attempts=job.max_attempts,
            scheduled_for=job.scheduled_for,
            started_at=job.started_at,
            completed_at=job.completed_at,
            error_message=job.error_message,
            idempotency_key=job.idempotency_key,
            created_at=job.created_at
        )
