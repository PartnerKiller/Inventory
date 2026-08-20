import uuid
from decimal import Decimal
from sqlalchemy import Column, String, Boolean, ForeignKey, Numeric, DateTime, JSON, Text, Integer, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.models.base import BaseModelMixin, get_utc_now

class GLAccount(Base, BaseModelMixin):
    __tablename__ = "gl_accounts"

    tenant_id = Column(String(36), nullable=False, index=True)
    account_code = Column(String(30), nullable=False, index=True) # e.g. 1000, 1100, 1200, 2000, 3000, 4000, 5000, 6000
    account_name = Column(String(100), nullable=False)
    account_class = Column(String(30), nullable=False) # ASSET, LIABILITY, EQUITY, REVENUE, COGS, EXPENSE
    account_type = Column(String(50), nullable=False) # CURRENT_ASSET, INVENTORY_ASSET, ACCOUNTS_RECEIVABLE, BANK_AND_CASH, CURRENT_LIABILITY, ACCOUNTS_PAYABLE, RETAINED_EARNINGS, OPERATING_REVENUE, DIRECT_COGS, OPERATING_EXPENSE
    currency = Column(String(10), default="USD", nullable=False)
    normal_balance = Column(String(10), nullable=False) # DEBIT, CREDIT
    parent_account_id = Column(String(36), ForeignKey("gl_accounts.id", ondelete="SET NULL"), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_system = Column(Boolean, default=False, nullable=False)
    description = Column(Text, nullable=True)

    parent_account = relationship("GLAccount", remote_side="GLAccount.id", lazy="selectin")
    entry_lines = relationship("JournalEntryLine", back_populates="account", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "account_code", name="uq_gl_account_code"),
        Index("idx_gl_account_tenant_class", "tenant_id", "account_class"),
    )

class JournalVoucher(Base, BaseModelMixin):
    __tablename__ = "journal_vouchers"

    tenant_id = Column(String(36), nullable=False, index=True)
    voucher_number = Column(String(50), nullable=False, index=True) # JV-YYYYMMDD-XXXX
    voucher_date = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    source_document_type = Column(String(50), nullable=False) # GRN, SALES_DISPATCH, CUSTOMER_INVOICE, CUSTOMER_PAYMENT, VENDOR_INVOICE, VENDOR_PAYMENT, WORK_ORDER, INVENTORY_ADJUSTMENT, MANUAL
    source_document_id = Column(String(100), nullable=True, index=True)
    status = Column(String(30), default="POSTED", nullable=False) # DRAFT, POSTED, VOIDED
    posted_at = Column(DateTime(timezone=True), default=get_utc_now, nullable=False)
    notes = Column(Text, nullable=True)
    created_by_user_id = Column(String(36), ForeignKey("users.id"), nullable=True)

    lines = relationship("JournalEntryLine", back_populates="voucher", cascade="all, delete-orphan", lazy="selectin")

    __table_args__ = (
        UniqueConstraint("tenant_id", "voucher_number", name="uq_jv_tenant_number"),
        Index("idx_jv_tenant_date", "tenant_id", "voucher_date"),
        Index("idx_jv_tenant_source", "tenant_id", "source_document_type", "source_document_id"),
    )

class JournalEntryLine(Base, BaseModelMixin):
    __tablename__ = "journal_entry_lines"

    voucher_id = Column(String(36), ForeignKey("journal_vouchers.id", ondelete="CASCADE"), nullable=False, index=True)
    account_id = Column(String(36), ForeignKey("gl_accounts.id"), nullable=False, index=True)
    debit_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    credit_amount = Column(Numeric(18, 4), default=0.0, nullable=False)
    currency = Column(String(10), default="USD", nullable=False)
    cost_center_id = Column(String(36), ForeignKey("cost_centers.id", ondelete="SET NULL"), nullable=True, index=True)
    memo = Column(String(255), nullable=True)

    voucher = relationship("JournalVoucher", back_populates="lines")
    account = relationship("GLAccount", back_populates="entry_lines", lazy="selectin")
