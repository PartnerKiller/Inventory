import uuid
from sqlalchemy import Column, String, Integer, DateTime, JSON, Index, Boolean
from app.core.database import Base
from app.models.base import generate_uuid, get_utc_now

class EntityChangeFeed(Base):
    __tablename__ = "entity_change_feed"

    # Monotonic revision counter for incremental downstream sync
    revision_id = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(36), default=generate_uuid, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True) # ITEM, VARIANT, BIN, BALANCE, ORDER, PRICING, CUSTOMER
    entity_id = Column(String(36), nullable=False, index=True)
    change_type = Column(String(20), nullable=False) # CREATED, UPDATED, DELETED, STATUS_CHANGED
    payload_json = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False, index=True)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now, nullable=False)
    is_deleted = Column(Boolean, default=False, nullable=False)

    __table_args__ = (
        Index("idx_change_feed_tenant_rev", "tenant_id", "revision_id"),
        Index("idx_change_feed_tenant_entity", "tenant_id", "entity_type", "created_at"),
    )

