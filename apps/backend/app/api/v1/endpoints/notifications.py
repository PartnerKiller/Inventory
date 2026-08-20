from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc

from app.core.database import get_db
from app.core.permissions import require_permission
from app.models.notifications import (
    InAppNotification,
    NotificationTemplate,
    OutboundWebhookEndpoint
)
from app.schemas.notifications import (
    NotificationTemplateCreate,
    NotificationTemplateResponse,
    InAppNotificationResponse,
    InAppNotificationMarkReadRequest,
    OutboundWebhookCreate,
    OutboundWebhookResponse
)
from app.services.notification_service import NotificationService

router = APIRouter()

@router.get("/inbox", response_model=List[InAppNotificationResponse])
async def list_user_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("notifications:read"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]

    stmt = select(InAppNotification).where(
        InAppNotification.tenant_id == tenant_id,
        InAppNotification.user_id == user_id
    )
    if unread_only:
        stmt = stmt.where(InAppNotification.is_read == False)
    stmt = stmt.order_by(desc(InAppNotification.created_at)).limit(limit)

    results = (await db.execute(stmt)).scalars().all()
    return [
        InAppNotificationResponse(
            id=n.id,
            user_id=n.user_id,
            title=n.title,
            body=n.body,
            event_type=n.event_type,
            entity_type=n.entity_type,
            entity_id=n.entity_id,
            is_read=n.is_read,
            read_at=n.read_at,
            created_at=n.created_at
        )
        for n in results
    ]

@router.post("/inbox/mark-read", status_code=status.HTTP_200_OK)
async def mark_notifications_read(
    req: InAppNotificationMarkReadRequest,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("notifications:read"))
):
    tenant_id = claims["tenant_id"]
    user_id = claims["sub"]

    stmt = select(InAppNotification).where(
        InAppNotification.id.in_(req.notification_ids),
        InAppNotification.tenant_id == tenant_id,
        InAppNotification.user_id == user_id
    )
    items = (await db.execute(stmt)).scalars().all()
    for item in items:
        item.is_read = True
    await db.commit()
    return {"marked_read_count": len(items)}

@router.post("/templates", response_model=NotificationTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_notification_template(
    template_in: NotificationTemplateCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("notification_templates:manage"))
):
    tenant_id = claims["tenant_id"]
    return await NotificationService.create_template(db, tenant_id, template_in)

@router.post("/webhooks", response_model=OutboundWebhookResponse, status_code=status.HTTP_201_CREATED)
async def register_webhook_endpoint(
    webhook_in: OutboundWebhookCreate,
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("webhooks:manage"))
):
    tenant_id = claims["tenant_id"]
    return await NotificationService.register_webhook_endpoint(db, tenant_id, webhook_in)

@router.get("/webhooks", response_model=List[OutboundWebhookResponse])
async def list_webhook_endpoints(
    db: AsyncSession = Depends(get_db),
    claims: dict = Depends(require_permission("webhooks:manage"))
):
    tenant_id = claims["tenant_id"]
    endpoints = (await db.execute(
        select(OutboundWebhookEndpoint).where(OutboundWebhookEndpoint.tenant_id == tenant_id)
    )).scalars().all()
    return [
        OutboundWebhookResponse(
            id=e.id,
            name=e.name,
            url=e.url,
            subscribed_events=e.subscribed_events,
            is_active=e.is_active,
            failure_count=e.failure_count,
            last_triggered_at=e.last_triggered_at,
            created_at=e.created_at
        )
        for e in endpoints
    ]
