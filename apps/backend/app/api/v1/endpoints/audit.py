import math
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func, and_
from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.audit import AuditLog
from app.schemas.audit import AuditLogResponse
from app.schemas.common import PaginatedResponse, PaginationMeta

router = APIRouter()

@router.get("", response_model=PaginatedResponse[AuditLogResponse])
async def list_audit_logs(
    entity_type: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    user_id: Optional[str] = Query(None),
    entity_id: Optional[str] = Query(None),
    start_date: Optional[datetime] = Query(None),
    end_date: Optional[datetime] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("audit:read"))
):
    tenant_id = claims["tenant_id"]

    conditions = [AuditLog.tenant_id == tenant_id]
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    if action:
        conditions.append(AuditLog.action == action)
    if user_id:
        conditions.append(AuditLog.user_id == user_id)
    if entity_id:
        conditions.append(AuditLog.entity_id == entity_id)
    if start_date:
        conditions.append(AuditLog.timestamp >= start_date)
    if end_date:
        conditions.append(AuditLog.timestamp <= end_date)

    count_stmt = select(func.count(AuditLog.id)).where(and_(*conditions))
    total_res = await db.execute(count_stmt)
    total_items = total_res.scalar() or 0
    total_pages = math.ceil(total_items / page_size) if total_items > 0 else 0

    offset = (page - 1) * page_size
    paged_stmt = (
        select(AuditLog)
        .where(and_(*conditions))
        .order_by(desc(AuditLog.timestamp))
        .offset(offset)
        .limit(page_size)
    )
    res = await db.execute(paged_stmt)
    logs = res.scalars().all()

    out = [
        AuditLogResponse(
            id=log.id,
            tenant_id=log.tenant_id,
            user_id=log.user_id,
            user_name=log.user.full_name if log.user else None,
            user_email=log.user.email if log.user else None,
            action=log.action,
            entity_type=log.entity_type,
            entity_id=log.entity_id,
            ip_address=log.ip_address,
            client_type=log.client_type,
            changes=log.changes,
            timestamp=log.timestamp
        ) for log in logs
    ]

    return PaginatedResponse(
        items=out,
        pagination=PaginationMeta(
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
            has_next=page < total_pages,
            has_prev=page > 1
        )
    )

@router.get("/{log_id}", response_model=AuditLogResponse)
async def get_audit_log(
    log_id: str,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("audit:read"))
):
    tenant_id = claims["tenant_id"]
    stmt = select(AuditLog).where(AuditLog.id == log_id, AuditLog.tenant_id == tenant_id)
    res = await db.execute(stmt)
    log = res.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Audit log entry not found")

    return AuditLogResponse(
        id=log.id,
        tenant_id=log.tenant_id,
        user_id=log.user_id,
        user_name=log.user.full_name if log.user else None,
        user_email=log.user.email if log.user else None,
        action=log.action,
        entity_type=log.entity_type,
        entity_id=log.entity_id,
        ip_address=log.ip_address,
        client_type=log.client_type,
        changes=log.changes,
        timestamp=log.timestamp
    )
