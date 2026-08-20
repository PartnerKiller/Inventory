from sqlalchemy import Column, String, Integer, DateTime, Index, UniqueConstraint
from app.core.database import Base
from app.models.base import BaseModelMixin, generate_uuid, get_utc_now

class DocumentSequence(Base):
    __tablename__ = "document_sequences"

    id = Column(String(36), primary_key=True, default=generate_uuid, index=True)
    tenant_id = Column(String(36), nullable=False, index=True)
    document_type = Column(String(50), nullable=False, index=True) # PURCHASE_ORDER, SALES_ORDER, GOODS_RECEIPT, TRANSFER, ADJUSTMENT, SHIPMENT, RETURN
    prefix = Column(String(20), nullable=False)
    date_key = Column(String(8), nullable=False) # YYYYMMDD
    current_number = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), default=get_utc_now, onupdate=get_utc_now, nullable=False)

    __table_args__ = (
        UniqueConstraint("tenant_id", "document_type", "date_key", name="uq_tenant_doc_type_date"),
        Index("idx_doc_seq_lookup", "tenant_id", "document_type", "date_key"),
    )
