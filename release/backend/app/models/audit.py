from sqlalchemy import Column, String, ForeignKey, DateTime, JSON, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import generate_uuid, get_utc_now

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(String(36), primary_key=True, default=generate_uuid, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action = Column(String(50), nullable=False, index=True) # CREATE, UPDATE, DELETE, POST_LEDGER, APPROVE, DISPATCH
    entity_type = Column(String(100), nullable=False, index=True)
    entity_id = Column(String(36), nullable=False, index=True)
    ip_address = Column(String(45), nullable=True)
    client_type = Column(String(20), default="WEB", nullable=False) # WEB, DESKTOP_TAURI, API
    changes = Column(JSON, default=dict, nullable=False) # {"old_state": {...}, "new_state": {...}}
    timestamp = Column(DateTime(timezone=True), default=get_utc_now, nullable=False, index=True)

    user = relationship("User", lazy="selectin")

    __table_args__ = (
        Index("idx_audit_tenant_time", "tenant_id", "timestamp"),
        Index("idx_audit_entity", "entity_type", "entity_id"),
    )

class EventOutbox(Base):
    __tablename__ = "event_outbox"

    id = Column(String(36), primary_key=True, default=generate_uuid, index=True)
    event_type = Column(String(100), nullable=False, index=True)
    aggregate_type = Column(String(50), nullable=False)
    aggregate_id = Column(String(36), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(20), default="PENDING", nullable=False) # PENDING, PROCESSED, FAILED
    created_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("idx_outbox_status", "status", "created_at"),
    )
