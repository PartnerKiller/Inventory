import uuid
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models.base import get_utc_now
from app.models.audit import EventOutbox
from app.schemas.notifications import DomainEventEnvelope

class OutboxService:
    @staticmethod
    async def publish_event(
        db: AsyncSession,
        tenant_id: str,
        event_type: str,
        aggregate_type: str,
        aggregate_id: str,
        payload: Dict[str, Any],
        actor_id: Optional[str] = None,
        correlation_id: Optional[str] = None
    ) -> EventOutbox:
        """
        Publishes a domain event atomically within the caller's active database transaction.
        Guarantees that if the transaction commits, the event is saved; if the transaction rolls back,
        the event is discarded.
        """
        event_id = str(uuid.uuid4())
        envelope = DomainEventEnvelope(
            event_id=event_id,
            event_type=event_type,
            version="1.0",
            tenant_id=tenant_id,
            entity_type=aggregate_type,
            entity_id=aggregate_id,
            occurred_at=get_utc_now(),
            correlation_id=correlation_id,
            actor_id=actor_id,
            payload=payload
        )

        outbox_entry = EventOutbox(
            id=event_id,
            event_type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            payload=envelope.model_dump(mode="json"),
            status="PENDING",
            created_at=get_utc_now()
        )
        db.add(outbox_entry)
        return outbox_entry

    @staticmethod
    async def get_pending_events(db: AsyncSession, limit: int = 50) -> List[EventOutbox]:
        stmt = (
            select(EventOutbox)
            .where(EventOutbox.status == "PENDING")
            .order_by(EventOutbox.created_at.asc())
            .limit(limit)
        )
        return (await db.execute(stmt)).scalars().all()

    @staticmethod
    async def mark_event_processed(db: AsyncSession, event_id: str):
        ev = (await db.execute(select(EventOutbox).where(EventOutbox.id == event_id))).scalar_one_or_none()
        if ev:
            ev.status = "PROCESSED"
            ev.processed_at = get_utc_now()
            await db.commit()
