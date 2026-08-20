import uuid
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class DocumentAttachment(Base, BaseModelMixin):
    __tablename__ = "document_attachments"

    tenant_id = Column(String(36), nullable=False, index=True)
    entity_type = Column(String(50), nullable=False, index=True) # PURCHASE_ORDER, SALES_ORDER, VENDOR_INVOICE, GOODS_RECEIPT, FIXED_ASSET, JOURNAL_VOUCHER, CONSOLIDATION_RUN
    entity_id = Column(String(36), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_size = Column(Integer, nullable=False) # Size in bytes
    mime_type = Column(String(100), default="application/pdf", nullable=False)
    sha256_hash = Column(String(64), nullable=False, index=True) # Cryptographic checksum
    file_content_base64 = Column(Text, nullable=False) # Base64 stored content
    version = Column(Integer, default=1, nullable=False)
    is_latest = Column(Boolean, default=True, nullable=False)
    uploaded_by_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    uploader = relationship("User", foreign_keys=[uploaded_by_user_id], lazy="selectin")
    sign_offs = relationship("DocumentSignOff", back_populates="attachment", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        Index("idx_doc_tenant_entity", "tenant_id", "entity_type", "entity_id"),
        Index("idx_doc_sha256", "sha256_hash"),
    )

class DocumentSignOff(Base, BaseModelMixin):
    __tablename__ = "document_sign_offs"

    tenant_id = Column(String(36), nullable=False, index=True)
    attachment_id = Column(String(36), ForeignKey("document_attachments.id", ondelete="CASCADE"), nullable=False, index=True)
    sign_off_role = Column(String(50), nullable=False) # INTERNAL_AUDITOR, CFO, QUALITY_MANAGER, COMPLIANCE_OFFICER
    signer_user_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(30), default="PENDING", nullable=False) # PENDING, SIGNED, REJECTED
    digital_signature = Column(String(128), nullable=True) # HMAC-SHA256 signature
    notes = Column(Text, nullable=True)
    signed_at = Column(DateTime(timezone=True), nullable=True)

    attachment = relationship("DocumentAttachment", back_populates="sign_offs", lazy="selectin")
    signer = relationship("User", foreign_keys=[signer_user_id], lazy="selectin")

    __table_args__ = (
        Index("idx_signoff_tenant_status", "tenant_id", "status"),
    )
