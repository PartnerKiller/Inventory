import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, UniqueConstraint, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class SyncDevice(Base, BaseModelMixin):
    __tablename__ = "sync_devices"

    tenant_id = Column(String(36), nullable=False, index=True)
    device_identifier = Column(String(100), nullable=False, index=True) # Unique hardware GUID / fingerprint
    device_name = Column(String(150), nullable=False)
    platform = Column(String(50), default="WINDOWS_DESKTOP", nullable=False)
    app_version = Column(String(50), nullable=False)
    status = Column(String(30), default="ACTIVE", nullable=False) # ACTIVE, REVOKED, PENDING_PAIRING
    registered_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    active_lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)

    registered_by = relationship("User", foreign_keys=[registered_by_user_id], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "device_identifier", name="uq_tenant_device_identifier"),
        Index("idx_device_tenant_status", "tenant_id", "status"),
    )

class SyncIdempotencyLog(Base, BaseModelMixin):
    __tablename__ = "sync_idempotency_log"

    tenant_id = Column(String(36), nullable=False, index=True)
    client_transaction_id = Column(String(64), nullable=False, index=True) # UUIDv7 from desktop
    device_id = Column(String(100), nullable=False, index=True)
    user_id = Column(String(36), ForeignKey("users.id"), nullable=False)
    operation_type = Column(String(50), nullable=False) # RECEIVE_GOODS, PUTAWAY, PICK_ITEM, PACK_ITEM, BIN_TRANSFER, COUNT_SCAN
    server_transaction_id = Column(String(36), ForeignKey("stock_ledger_transactions.id"), nullable=True, index=True)
    status = Column(String(30), nullable=False) # COMMITTED, REJECTED, CONFLICT
    response_payload = Column(JSON, nullable=False)
    error_detail = Column(Text, nullable=True)
    processed_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)

    user = relationship("User", foreign_keys=[user_id], lazy="selectin")
    server_tx = relationship("StockLedgerTransaction", foreign_keys=[server_transaction_id], lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "client_transaction_id", name="uq_tenant_client_tx_id"),
        Index("idx_sync_lookup", "tenant_id", "client_transaction_id"),
    )
